import json

import unittest

from dba_agent import Session, SessionStore, Stage, StateError


def dbms_choice():
  names = ["PostgreSQL", "MySQL/MariaDB", "SQLite", "SQL Server"]
  return {
      "selected": "PostgreSQL",
      "rationale": "The workload needs strong transactions, reporting, and concurrent access.",
      "comparison": {
          name: {
              "strengths": [f"Strength of {name}"],
              "limitations": [f"Limitation of {name}"],
              "fit": f"Fit assessment for {name}",
          }
          for name in names
      },
      "rejected": {
          name: f"{name} is less suitable for the stated workload."
          for name in names if name != "PostgreSQL"
      },
      "evidence": {
          "entities": "The system has several related entities.",
          "relationships": "Relationships require foreign keys and cardinality enforcement.",
          "volume": "The data volume is expected to grow steadily.",
          "workload": "Reports and concurrent reads are important.",
          "transactions": "Operations require atomic transactions.",
          "security": "Roles and access controls are required.",
          "business_rules": "Business rules require constraints and validation.",
      },
  }


class SessionTests(unittest.TestCase):
  def test_round_trip_preserves_state(self):
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
      session = Session(intake_text="A library system")
      session.intake_summary = {"actors": ["librarian"]}
      session.state = Stage.INTAKE_COMPLETE
      store = SessionStore(directory)
      path = store.save(session)
      restored = store.load(session.session_id)
      self.assertTrue(path.exists())
      self.assertEqual(restored.to_dict(), session.to_dict())


  def test_interview_requires_follow_up_and_all_categories(self):
    session = Session(state=Stage.INTAKE_COMPLETE)
    session.start_interview()
    categories = {name: "covered" for name in ["entities", "relationships", "volume", "workload", "transactions", "security", "business_rules"]}
    with self.assertRaises(StateError):
        session.complete_requirements(categories)
    session.add_interview_round(["What entities exist?"], {"What entities exist?": "books"})
    session.add_interview_round(["How many books?"], {"How many books?": "1000"})
    session.complete_requirements(categories)
    assert session.state == Stage.REQUIREMENTS_COMPLETE

  def test_dbms_selection_records_choice_and_renders_artifact(self):
    session = Session(state=Stage.REQUIREMENTS_COMPLETE)
    session.select_dbms(dbms_choice())
    self.assertEqual(session.state, Stage.DBMS_SELECTED)
    markdown = session.dbms_choice_markdown()
    self.assertIn("# DBMS Selection", markdown)
    self.assertIn("**PostgreSQL**", markdown)
    self.assertIn("| SQLite |", markdown)

  def test_dbms_selection_requires_all_supported_comparisons(self):
    session = Session(state=Stage.REQUIREMENTS_COMPLETE)
    choice = dbms_choice()
    del choice["comparison"]["SQLite"]
    with self.assertRaises(StateError):
      session.select_dbms(choice)


  def test_revision_clears_approval_and_sql_requires_active_approval(self):
    session = Session(state=Stage.DESIGN_READY)
    session.approve()
    session.require_sql_approval()
    session.revise({"entities": ["customer"]})
    with self.assertRaises(StateError):
        session.require_sql_approval()


if __name__ == "__main__":
  unittest.main()

