import json

import unittest

from dba_agent import Session, SessionStore, Stage, StateError


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
    categories = {name: {} for name in ["entities", "relationships", "volume", "workload", "transactions", "security", "business_rules"]}
    with self.assertRaises(StateError):
        session.complete_requirements(categories)
    session.add_interview_round(["What entities exist?"], {"What entities exist?": "books"})
    session.add_interview_round(["How many books?"], {"How many books?": "1000"})
    session.complete_requirements(categories)
    assert session.state == Stage.REQUIREMENTS_COMPLETE


  def test_revision_clears_approval_and_sql_requires_active_approval(self):
    session = Session(state=Stage.DESIGN_READY)
    session.approve()
    session.require_sql_approval()
    session.revise({"entities": ["customer"]})
    with self.assertRaises(StateError):
        session.require_sql_approval()


if __name__ == "__main__":
  unittest.main()

