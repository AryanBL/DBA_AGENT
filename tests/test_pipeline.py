"""Offline end-to-end test with a deterministic scripted LLM; real SQL execution in SQLite."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dba_agent import AgentService, Config, Stage, StateError
from dba_agent.llm import LLMClient


REQUIREMENTS = {
    "entities": "Customers and orders, each with ID; customers have names",
    "relationships": "A customer has many orders; every order has one customer",
    "volume": "1000 customers and 5000 orders initially; 20 percent annual growth",
    "workload": "Most reads are customer order histories, and new orders are frequently written",
    "transactions": "Order creation is atomic; multiple writers may be active",
    "security": "Staff can see orders, only admins delete customer profiles",
    "business_rules": "Every order references an existing customer, amount must be positive",
}
COVERAGE = {key: True for key in REQUIREMENTS}


def model():
    return {
        "tables": [
            {"name": "customers", "description": "People placing orders", "columns": [{"name": "customer_id", "type": "INTEGER", "nullable": False}, {"name": "name", "type": "TEXT", "nullable": False}], "primary_key": ["customer_id"], "uniques": [], "foreign_keys": [], "checks": [], "indexes": []},
            {"name": "orders", "description": "Orders placed by customers", "columns": [{"name": "order_id", "type": "INTEGER", "nullable": False}, {"name": "customer_id", "type": "INTEGER", "nullable": False}, {"name": "amount", "type": "REAL", "nullable": False}], "primary_key": ["order_id"], "uniques": [], "foreign_keys": [{"columns": ["customer_id"], "references_table": "customers", "references_columns": ["customer_id"], "on_delete": "RESTRICT", "on_update": "CASCADE"}], "checks": ["amount > 0"], "indexes": [{"name": "idx_order_customer", "columns": ["customer_id"]}]},
        ],
        "relationships": [{"from": "customers", "to": "orders", "cardinality": "1 to many", "description": "Orders belong to customers"}],
        "functional_dependencies": [{"table": "customers", "determinant": ["customer_id"], "dependents": ["name"]}, {"table": "orders", "determinant": ["order_id"], "dependents": ["customer_id", "amount"]}],
        "normalization": [{"table": "customers", "normal_form": "3NF", "justification": "Atomic data, single-column key and no transitive dependencies"}, {"table": "orders", "normal_form": "3NF", "justification": "Atomic fields, non-key columns depend only on order_id"}],
        "assumptions": ["Amounts are in a single currency"], "ambiguities": ["Currency is not specified"],
        "business_rules": [{"rule": "Order amount is positive", "implementation": "CHECK amount > 0"}],
    }


def dbms_choice():
    names = ["PostgreSQL", "MySQL/MariaDB", "SQLite", "SQL Server"]
    return {"selected": "SQLite", "rationale": "Selected for a small self-contained local demonstration; concurrency needs must be revisited for production", "comparison": [{"dbms": name, "advantages": "Supports relational integrity", "tradeoffs": "Deployment/performance tradeoffs", "fit": "SQLite best for local proof of concept"} for name in names], "rejected": {name: "Requires additional server setup for the demo" for name in names if name != "SQLite"}}


class ScriptedTransport:
    def __init__(self, outputs):
        self.outputs = [json.dumps(item) for item in outputs]
        self.calls = 0

    def __call__(self, url, key, body, timeout):
        response = self.outputs[self.calls]
        self.calls += 1
        return response


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cfg = Config(state_dir=root / "sessions", output_dir=root / "outputs")
        self.assessment = {"ready": True, "coverage": COVERAGE, "critical_contradictions": [], "missing_topics": [], "reason": "Enough information", "requirements": REQUIREMENTS}
        self.sql = {
            "schema_sql": "CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT NOT NULL); CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(customer_id) ON DELETE RESTRICT ON UPDATE CASCADE, amount REAL NOT NULL CHECK (amount > 0)); CREATE INDEX idx_order_customer ON orders(customer_id);",
            "seed_sql": "INSERT INTO customers (customer_id,name) VALUES (1,'Jules Anderson'),(2,'Mina Park'); INSERT INTO orders (order_id,customer_id,amount) VALUES (10,1,25.40),(11,1,19.00),(12,2,100.00);",
        }

    def service(self, outputs):
        scripted = ScriptedTransport(outputs)
        agent = AgentService(self.cfg, LLMClient(self.cfg, transport=scripted))
        return agent, scripted

    def through_design(self):
        intro = {"actors": ["Customer"], "entities": ["customer", "order"], "processes": ["place order"], "requirements": ["keep order records"], "ambiguities": []}
        outputs = [intro, {"questions": ["How many customers?"]}, {**self.assessment, "ready": False}, {"questions": ["Does an order need a customer?"]}, self.assessment, dbms_choice(), {"design": model()}]
        agent, transport = self.service(outputs)
        session = agent.create("Customers place orders")
        self.assertEqual(session.state, Stage.INTERVIEWING)
        session = agent.answer(session.session_id, {"How many customers?": "1000"})
        self.assertEqual(len(session.interview_rounds), 1)
        session = agent.answer(session.session_id, {"Does an order need a customer?": "Yes"})
        self.assertEqual(session.state, Stage.DESIGN_READY)
        self.assertEqual(transport.calls, len(outputs))
        return agent, session

    def test_all_stages_through_real_sqlite(self):
        agent, session = self.through_design()
        folder = self.cfg.output_dir / session.session_id / "v1"
        for name in ("requirements.md", "dbms-choice.md", "conceptual-model.md", "logical-schema.md", "normalization.md", "assumptions.md"):
            self.assertTrue((folder / name).exists(), name)
        self.assertIn("erDiagram", (folder / "conceptual-model.md").read_text())
        with self.assertRaises(StateError):
            agent.generate_sql(session.session_id, verify_sqlite=True)
        agent.approve(session.session_id)
        agent.llm.transport = ScriptedTransport([self.sql])
        result = agent.generate_sql(session.session_id, verify_sqlite=True)
        self.assertTrue(result["verified_sqlite"])
        self.assertEqual(result["counts"], {"customers": 2, "orders": 3})
        self.assertEqual(agent.get(session.session_id).state, Stage.SQL_GENERATED)
        self.assertEqual(len((self.cfg.output_dir / "llm-calls.jsonl").read_text().splitlines()), 8)

    def test_revision_creates_new_version_and_invalidates_approval(self):
        agent, session = self.through_design()
        agent.approve(session.session_id)
        new_design = model()
        new_design["tables"][0]["columns"].append({"name": "email", "type": "TEXT", "nullable": True})
        agent.llm.transport = ScriptedTransport([{"reason": "Customer email needed", "requirements": {**REQUIREMENTS, "entities": "Customers have optional emails"}, "dbms_choice": dbms_choice(), "design": new_design}])
        revised = agent.revise(session.session_id, "Add optional customer email")
        self.assertEqual(revised.active_version, 2)
        self.assertIsNone(revised.approval_version)
        self.assertEqual(revised.state, Stage.DESIGN_READY)
        self.assertTrue((self.cfg.output_dir / revised.session_id / "v1" / "conceptual-model.md").exists())
        self.assertIn("email", (self.cfg.output_dir / revised.session_id / "v2" / "logical-schema.md").read_text())
        self.assertIn("optional customer email", (self.cfg.output_dir / revised.session_id / "changelog.md").read_text())
        with self.assertRaises(StateError):
            agent.generate_sql(session.session_id)

    def test_bad_model_does_not_advance_state(self):
        agent, session = self.through_design()
        agent.llm.transport = ScriptedTransport([{"reason": "invalid model", "requirements": REQUIREMENTS, "dbms_choice": dbms_choice(), "design": {}}])
        with self.assertRaises(StateError):
            agent.revise(session.session_id, "add new entity")
        self.assertEqual(agent.get(session.session_id).active_version, 1)

    def test_sql_repair_uses_validation_error(self):
        agent, session = self.through_design()
        agent.approve(session.session_id)
        bad = {"schema_sql": self.sql["schema_sql"], "seed_sql": "INSERT INTO customers (customer_id,name) VALUES (1,'Jules');"}
        agent.llm.transport = ScriptedTransport([bad, self.sql])
        result = agent.generate_sql(session.session_id, verify_sqlite=True)
        self.assertEqual(result["attempts"], 2)
        self.assertTrue((self.cfg.output_dir / "sql-validation.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
