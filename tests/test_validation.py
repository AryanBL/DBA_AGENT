import unittest

from dba_agent.model import validate_design
from dba_agent.session import StateError
from dba_agent.sql import validate_sql_artifacts, execute_sqlite
from tests.test_pipeline import model


class ValidationTests(unittest.TestCase):
    def test_quoted_names_pass_coverage_checks(self):
        validate_sql_artifacts('CREATE TABLE "customers" (id INTEGER);', 'INSERT INTO "customers" (id) VALUES (1);', ["customers"])
        validate_sql_artifacts('CREATE TABLE [dbo].[customers] (id int);', 'INSERT INTO [dbo].[customers] VALUES (1);', ["customers"])

    def test_foreign_key_must_reference_unique_columns(self):
        d = model()
        d["tables"][1]["foreign_keys"][0]["references_columns"] = ["name"]
        with self.assertRaises(StateError):
            validate_design(d)

    def test_sqlite_rejects_disk_attachment(self):
        with self.assertRaises(StateError):
            execute_sqlite("CREATE TABLE customers (id INTEGER); ATTACH DATABASE '/tmp/not-allowed-by-dba-agent.db' AS x;", "INSERT INTO customers VALUES (1);", ["customers"])


if __name__ == "__main__":
    unittest.main()
