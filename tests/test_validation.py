import unittest

from dba_agent.model import validate_design
from dba_agent.session import StateError
from dba_agent.sql import validate_sql_artifacts, execute_sqlite
from dba_agent.sql_statements import split_sql
from dba_agent.sql_validation import SQLArtifacts, SQLConflict, validate_sqlite_seed
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

    def test_sqlite_preflight_attributes_constraint_conflicts_to_the_failing_insert(self):
        schema = (
            'CREATE TABLE parents (code TEXT, region TEXT, PRIMARY KEY (code, region));'
            'CREATE TABLE items (id INTEGER PRIMARY KEY, code TEXT, region TEXT, '
            'name TEXT COLLATE NOCASE NOT NULL, qty INT NOT NULL DEFAULT 1 CHECK (qty > 0), '
            'price REAL NOT NULL, total REAL AS (qty * price), '
            'FOREIGN KEY (code, region) REFERENCES parents(code, region));'
            'CREATE UNIQUE INDEX idx_name ON items(name);'
        )
        prefix = "INSERT INTO parents VALUES ('A','north'); INSERT INTO items (id,code,region,name,price) VALUES (1,'A','north','First',3);"
        for columns, values, error in (
            ("id,price,name", "1,3,'duplicate id'", "UNIQUE constraint failed: items.id"),
            ("id,price,name", "2,3,'first'", "UNIQUE constraint failed: items.name"),
            ("id,price,name", "2,3,NULL", "NOT NULL constraint failed"),
            ("id,price,name,qty", "2,3,'negative',-1", "CHECK constraint failed"),
            ("id,price,name,qty", "2,3,'invalid','abc'", "Incompatible SQLite type"),
            ("id,price,name,code,region", "2,3,'orphan','A','south'", "FOREIGN KEY constraint failed"),
            ("id,price,name,total", "2,3,'generated',3", "cannot INSERT into generated column"),
            ("id,price,name,missing", "2,3,'unknown',1", "has no column named missing"),
        ):
            with self.subTest(error=error):
                artifacts = SQLArtifacts(schema, prefix + f" INSERT INTO items ({columns}) VALUES ({values});", "SQLite")
                artifacts.preflight(["parents", "items"])
                with self.assertRaisesRegex(SQLConflict, error) as caught:
                    validate_sqlite_seed(artifacts, ["parents", "items"])
                self.assertEqual((caught.exception.file, caught.exception.statement), ("seed", 2))

    def test_sqlite_deferred_fk_is_attributed_to_the_offending_insert(self):
        schema = ("CREATE TABLE parents(id INT PRIMARY KEY); "
                  "CREATE TABLE children(id INT PRIMARY KEY, parent INT REFERENCES parents(id) DEFERRABLE INITIALLY DEFERRED);")
        seed = "BEGIN; INSERT INTO children VALUES (1,9); INSERT INTO children VALUES (2,2); INSERT INTO parents VALUES (2); COMMIT;"
        artifacts = SQLArtifacts(schema, seed, "SQLite")
        with self.assertRaisesRegex(SQLConflict, "FOREIGN KEY") as caught:
            validate_sqlite_seed(artifacts, ["parents", "children"])
        context = artifacts.repair_context(caught.exception, {"tables": []})
        self.assertIn("seed:2", context["editable"])
        self.assertNotIn("seed:3", context["statements"])
        self.assertNotIn("seed:5", context["statements"])
        artifacts.apply({"patches": {"seed:2": "INSERT INTO children VALUES (1,2);"}}, context["editable"])
        validate_sqlite_seed(artifacts, ["parents", "children"])

    def test_comments_and_string_literals_cannot_satisfy_table_coverage(self):
        artifacts = SQLArtifacts("CREATE TABLE items(id INT);", "-- INSERT INTO items VALUES (1);\nSELECT 'INSERT INTO items';", "SQLite")
        with self.assertRaisesRegex(SQLConflict, "does not populate items"):
            artifacts.preflight(["items"])

    def test_sqlite_fk_repair_omits_unrelated_parent_tables(self):
        schema = ("CREATE TABLE a(id INT PRIMARY KEY); CREATE TABLE b(id INT PRIMARY KEY); "
                  "CREATE TABLE items(a INT REFERENCES a(id), b INT REFERENCES b(id));")
        seed = "INSERT INTO a VALUES (1); INSERT INTO b VALUES (2); INSERT INTO items VALUES (1,3);"
        artifacts = SQLArtifacts(schema, seed, "SQLite")
        with self.assertRaises(SQLConflict) as caught:
            validate_sqlite_seed(artifacts, ["a", "b", "items"])
        context = artifacts.repair_context(caught.exception, {"tables": []})
        self.assertEqual(set(context["statements"]), {"schema:2", "schema:3", "seed:2", "seed:3"})

    def test_sql_split_respects_sqlite_triggers_and_postgres_dollar_quotes(self):
        trigger = "CREATE TRIGGER record AFTER INSERT ON items BEGIN INSERT INTO audit VALUES ('a;b'); END;"
        function = "CREATE FUNCTION sample() RETURNS text AS $fn$ SELECT 'a;b'; $fn$ LANGUAGE SQL;"
        for dbms, statement in (("SQLite", trigger), ("PostgreSQL", function)):
            parts = split_sql(f"{statement}\n-- separator\nINSERT INTO items VALUES (1);", dbms)
            self.assertEqual([part.text for part in parts], [statement, "INSERT INTO items VALUES (1);"])

    def test_preflight_rejects_sql_that_hides_data_conflicts(self):
        for dbms, schema, seed in (
            ("SQLite", "CREATE TABLE items(id INT);", "INSERT OR IGNORE INTO items VALUES (1);"),
            ("MySQL/MariaDB", "CREATE TABLE items(id INT) ENGINE=MyISAM;", "INSERT INTO items VALUES (1);"),
            ("MySQL/MariaDB", "CREATE TABLE items(id INT REFERENCES other(id));", "INSERT INTO items VALUES (1);"),
            ("PostgreSQL", "CREATE TABLE items(id INT);", "INSERT INTO items VALUES (1) ON CONFLICT (id) DO NOTHING;"),
        ):
            with self.subTest(dbms=dbms, seed=seed):
                with self.assertRaises(SQLConflict):
                    SQLArtifacts(schema, seed, dbms).preflight(["items"])


if __name__ == "__main__":
    unittest.main()
