"""Unit tests for transitions, validation, persistence and approval invalidation."""
import tempfile
import unittest

from dba_agent import Session, SessionStore, Stage, StateError
from dba_agent.interview import REQUIRED_CATEGORIES


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.requirements = {key: f"Meaningful {key} answer" for key, _ in REQUIRED_CATEGORIES}
        self.coverage = {key: True for key, _ in REQUIRED_CATEGORIES}

    def interview_session(self):
        session = Session()
        session.complete_intake("A library lending service", {"actors": ["member"], "entities": ["books"], "processes": ["borrow"], "requirements": [], "ambiguities": []})
        session.start_interview()
        session.set_questions(["Which entities?"])
        session.add_interview_round(["Which entities?"], {"Which entities?": "Books and loans"})
        return session

    def test_round_trip_preserves_state(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.interview_session()
            store = SessionStore(directory)
            path = store.save(session)
            restored = store.load(session.session_id)
            self.assertTrue(path.exists())
            self.assertEqual(restored.to_dict(), session.to_dict())

    def test_interview_requires_follow_up_coverage_and_agent_decision(self):
        session = self.interview_session()
        assessment = {"ready": True, "coverage": self.coverage, "critical_contradictions": [], "requirements": self.requirements}
        session.assess_interview(assessment)
        with self.assertRaises(StateError):
            session.complete_requirements(self.requirements)
        session.set_questions(["How many users?"])
        session.add_interview_round(["How many users?"], {"How many users?": "1000"})
        with self.assertRaises(StateError):
            session.complete_requirements(self.requirements)
        session.assess_interview({**assessment, "ready": False})
        with self.assertRaises(StateError):
            session.complete_requirements(self.requirements)
        session.assess_interview(assessment)
        session.complete_requirements(self.requirements)
        self.assertEqual(session.state, Stage.REQUIREMENTS_COMPLETE)
        self.assertIn("Data volume and growth", session.requirements_markdown())

    def test_traversal_prevented(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(directory)
            with self.assertRaises(StateError):
                store.load("../secret")

    def test_revise_rejects_incomplete_model(self):
        session = Session(state=Stage.DESIGN_READY)
        with self.assertRaises(StateError):
            session.revise({}, reason="new request", request="add table")


if __name__ == "__main__":
    unittest.main()
