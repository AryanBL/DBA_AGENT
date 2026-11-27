"""Offline checks for the separate, no-pull container execution command."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dba_agent.docker_sql import execute_docker_sql
from dba_agent.session import StateError


def result(code=0, output=""):
    return subprocess.CompletedProcess([], code, output, "")


class DockerSqlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.schema, self.seed = folder / "schema.sql", folder / "seed.sql"
        self.schema.write_text("CREATE TABLE items (id int);", encoding="utf-8")
        self.seed.write_text("INSERT INTO items VALUES (1);", encoding="utf-8")
        self.args = dict(container="db", database="example", username="admin", password="secret")

    def test_both_files_required_before_docker_access(self):
        self.seed.unlink()
        with patch("dba_agent.docker_sql._docker") as docker:
            with self.assertRaisesRegex(StateError, "missing or empty"):
                execute_docker_sql(self.schema, self.seed, dbms="PostgreSQL", **self.args)
            docker.assert_not_called()

    def test_missing_local_image_never_runs_sql_or_pulls(self):
        with patch("dba_agent.docker_sql._docker", side_effect=[
            result(output="sha256:abc|true\n"), result(code=1)
        ]) as docker, patch("dba_agent.docker_sql.subprocess.run") as run:
            with self.assertRaisesRegex(StateError, "not available locally"):
                execute_docker_sql(self.schema, self.seed, dbms="PostgreSQL", **self.args)
            run.assert_not_called()
            self.assertEqual([call.args[0:2] for call in docker.call_args_list],
                             [("container", "inspect"), ("image", "inspect")])

    def test_postgres_runs_schema_then_seed_with_psql(self):
        seen = []

        def run(command, **kwargs):
            seen.append((command, Path(kwargs["stdin"].name).name, kwargs["env"]["PGPASSWORD"]))
            return result()

        with patch("dba_agent.docker_sql._docker", side_effect=[
            result(output="sha256:abc|true\n"), result(output="sha256:abc\n"), result(output="psql 16\n")
        ]), patch("dba_agent.docker_sql.subprocess.run", side_effect=run):
            output = execute_docker_sql(self.schema, self.seed, dbms="PostgreSQL", **self.args)
        self.assertEqual([entry[1] for entry in seen], ["schema.sql", "seed.sql"])
        self.assertTrue(all("ON_ERROR_STOP=1" in entry[0] and "-e" in entry[0] for entry in seen))
        self.assertTrue(all(entry[2] == "secret" and "secret" not in entry[0] for entry in seen))
        self.assertEqual(output["database"], "example")

    def test_sqlcmd_failure_stops_before_seed(self):
        with patch("dba_agent.docker_sql._docker", side_effect=[
            result(output="sha256:abc|true\n"), result(output="sha256:abc\n"), result()
        ]), patch("dba_agent.docker_sql.subprocess.run", return_value=result(code=1)) as run:
            with self.assertRaisesRegex(StateError, "schema.sql failed in sqlcmd"):
                execute_docker_sql(self.schema, self.seed, dbms="SQL Server", **self.args)
            self.assertEqual(run.call_count, 1)
            self.assertIn("-b", run.call_args.args[0])

    def test_mysql_and_mariadb_clients_run_both_files(self):
        for available_client in ("mariadb", "mysql"):
            with self.subTest(client=available_client):
                checks = [result(output="sha256:abc|true\n"), result(output="sha256:abc\n")]
                if available_client == "mysql":
                    checks.append(result(code=1))
                checks.append(result(output=f"{available_client} 11\n"))
                seen = []

                def run(command, **kwargs):
                    seen.append((command, Path(kwargs["stdin"].name).name,
                                 kwargs["env"]["MYSQL_PWD"]))
                    return result()

                with patch("dba_agent.docker_sql._docker", side_effect=checks), \
                     patch("dba_agent.docker_sql.subprocess.run", side_effect=run):
                    output = execute_docker_sql(self.schema, self.seed, dbms="MySQL/MariaDB", **self.args)
                self.assertEqual([item[1] for item in seen], ["schema.sql", "seed.sql"])
                self.assertTrue(all(item[0][6] == available_client for item in seen))
                self.assertTrue(all("--batch" in item[0] and "--database=example" in item[0]
                                    for item in seen))
                self.assertTrue(all(item[2] == "secret" and "secret" not in item[0] for item in seen))
                self.assertTrue(output["executed"])


if __name__ == "__main__":
    unittest.main()
