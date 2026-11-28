"""Offline checks for the separate, no-pull container execution command."""
import subprocess
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dba_agent.docker_sql import _inspection_commands, execute_docker_sql, local_database_image, provision_docker_sql
from dba_agent.docker_validation import _execution_script, _native_error, docker_seed_validator
from dba_agent.session import StateError
from dba_agent.sql_validation import SQLArtifacts


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
        self.assertIn("pg_catalog.pg_tables", output["inspection_commands"]["list_tables"])
        self.assertEqual(shlex.split(output["inspection_commands"]["preview_rows"])[-1], "SELECT * FROM items LIMIT 10;")

    def test_inspection_commands_use_detected_client_and_qualified_table(self):
        for dbms, client, table, query in (
            ("PostgreSQL", "psql", '"sales"."Order Items"', 'SELECT * FROM "sales"."Order Items" LIMIT 10;'),
            ("MySQL/MariaDB", "mariadb", "`Order Items`", "SELECT * FROM `Order Items` LIMIT 10;"),
            ("SQL Server", "/opt/mssql-tools/bin/sqlcmd", "[sales].[Order Items]", "SELECT TOP (10) * FROM [sales].[Order Items];"),
        ):
            with self.subTest(dbms=dbms):
                self.schema.write_text(f"CREATE TABLE {table} (id INT);", encoding="utf-8")
                commands = _inspection_commands(self.schema, dbms, "local-db", client, "test database", "test user")
                self.assertEqual(shlex.split(commands["preview_rows"])[:6], ["docker", "exec", "-it", "--", "local-db", client])
                self.assertEqual(shlex.split(commands["preview_rows"])[-1], query)

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


class DockerValidationTests(unittest.TestCase):
    def test_native_errors_point_to_the_statement_in_the_failed_batch(self):
        artifacts = SQLArtifacts("", "INSERT INTO items VALUES (1);\nGO\n"
                                     "INSERT INTO items VALUES (2); INSERT INTO items VALUES (2);\nGO\n", "SQL Server")
        script, locations = _execution_script(artifacts, "seed", "mark_")
        self.assertIn("PRINT 'mark_1';\nGO", script)
        self.assertEqual(locations, [(0, 1), (1, 1), (1, 2)])
        result = subprocess.CompletedProcess([], 1, "mark_0\nmark_1\n",
                                             "Msg 2627, Level 14, State 1, Server test, Line 2\nDuplicate key.\n")
        conflict = _native_error("SQL Server", "seed", result, "mark_", locations)
        self.assertEqual(conflict.statement, 2)
        self.assertEqual(str(conflict), "seed.sql: Duplicate key.")

    def test_disposable_server_uses_local_image_and_cleans_up_on_failure(self):
        with patch("dba_agent.docker_validation._docker", return_value=result()) as docker, \
                patch("dba_agent.docker_validation.local_database_image", return_value="postgres:local"), \
                patch("dba_agent.docker_validation.database_client", return_value="psql"), \
                patch("dba_agent.docker_validation.DockerSeedValidator._run", return_value=result()):
            with self.assertRaisesRegex(StateError, "some failure"):
                with docker_seed_validator("PostgreSQL", "postgres:local"):
                    raise StateError("some failure")
            launch, cleanup = [call.args for call in docker.call_args_list]
            self.assertIn("--pull=never", launch)
            self.assertIn("--network=none", launch)
            self.assertEqual(launch[-1], "postgres:local")
            self.assertEqual(cleanup, ("rm", "-f", "-v", launch[launch.index("--name") + 1]))


class DockerProvisionTests(unittest.TestCase):
    def test_local_image_discovery_accepts_version_tags_and_prefers_mysql(self):
        listing = "mysql-client\tlatest\nmariadb\t11.4\ncontainer-registry.oracle.com/mysql/community-server\t8.4\n"
        with patch("dba_agent.docker_sql._docker", return_value=result(output=listing)) as docker:
            self.assertEqual(local_database_image("MySQL/MariaDB"), "container-registry.oracle.com/mysql/community-server:8.4")
            self.assertEqual(docker.call_args.args[:2], ("image", "ls"))
            with self.assertRaisesRegex(StateError, "No compatible local image"):
                local_database_image("PostgreSQL")

    def test_provision_sets_shared_login_and_removes_its_container_if_seed_fails(self):
        with patch("dba_agent.docker_sql._require_sql_files"), \
                patch("dba_agent.docker_sql._inspection_commands"), \
                patch("dba_agent.docker_sql.local_database_image", return_value="mysql:8.4"), \
                patch("dba_agent.docker_sql.database_client", return_value="mysql"), \
                patch("dba_agent.docker_sql._wait_for_database"), \
                patch("dba_agent.docker_sql._run_sql_files", side_effect=StateError("seed.sql failed")), \
                patch("dba_agent.docker_sql._docker", return_value=result()) as docker:
            with self.assertRaisesRegex(StateError, "seed.sql failed"):
                provision_docker_sql(Path("schema.sql"), Path("seed.sql"), dbms="MySQL/MariaDB", database="test_db",
                                     username="shared_user", password="shared-password")
        create, start, cleanup = docker.call_args_list
        self.assertIn("--pull=never", create.args)
        self.assertNotIn("shared-password", create.args)
        self.assertEqual(create.kwargs["env"]["MYSQL_PASSWORD"], "shared-password")
        self.assertEqual(create.kwargs["env"]["MYSQL_USER"], "shared_user")
        self.assertEqual(create.kwargs["env"]["MYSQL_DATABASE"], "test_db")
        self.assertEqual(cleanup.args, ("rm", "-f", "-v", start.args[-1]))

    def test_sql_server_creates_shared_login_before_loading_sql(self):
        with patch.dict("os.environ", ACCEPT_EULA="Y"), \
                patch("dba_agent.docker_sql._require_sql_files"), \
                patch("dba_agent.docker_sql._inspection_commands"), \
                patch("dba_agent.docker_sql.local_database_image", return_value="mcr.microsoft.com/mssql/server:2022-latest"), \
                patch("dba_agent.docker_sql.database_client", return_value="sqlcmd"), \
                patch("dba_agent.docker_sql._wait_for_database"), \
                patch("dba_agent.docker_sql._query", return_value=result()) as setup, \
                patch("dba_agent.docker_sql._run_sql_files") as load, \
                patch("dba_agent.docker_sql._docker", return_value=result()):
            output = provision_docker_sql(Path("schema.sql"), Path("seed.sql"), dbms="SQL Server", database="test_db",
                                          username="shared_user", password="Example'9!password")
        self.assertIn("CREATE DATABASE [test_db]", setup.call_args.args[2])
        self.assertIn("CREATE LOGIN [shared_user] WITH PASSWORD = N'Example''9!password'", setup.call_args.args[2])
        self.assertIn("ALTER ROLE db_owner ADD MEMBER [shared_user]", setup.call_args.args[2])
        self.assertIn("shared_user", load.call_args.args[2])
        self.assertEqual(load.call_args.args[3]["SQLCMDPASSWORD"], "Example'9!password")
        self.assertEqual(output["username"], "shared_user")


if __name__ == "__main__":
    unittest.main()
