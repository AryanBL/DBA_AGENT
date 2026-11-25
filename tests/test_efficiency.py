"""Offline regression coverage for context budgets, usage and caching."""
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from dba_agent import Config, Session
from dba_agent.context import interview_summary, repair_context, sql_design
from dba_agent.llm import LLMClient, LLMError, NetworkError
from tests import test_pipeline as pipeline


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Config(output_dir=Path(temp.name), api_key="test-private-key")

    def test_usage_cache_and_redaction(self):
        calls = []

        def transport(*args):
            calls.append(args)
            return {"choices": [{"message": {"content": '{"ok":true}'}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128}}

        client = LLMClient(self.config, transport)
        for _ in range(2):
            client.ask("intake", "intake", {"description": self.config.api_key}, session_id="session")
        self.assertEqual(len(calls), 1)
        self.assertEqual(client.totals["total_tokens"], 128)
        self.assertEqual(client.session_totals["session"]["cache_hits"], 1)
        self.assertNotIn(self.config.api_key, client.log_path.read_text())
        self.assertNotIn(self.config.api_key, repr(self.config))

        client.transport = lambda *args: json.dumps({"echo": self.config.api_key})
        client.ask("intake", "intake", {"description": "different"})
        self.assertNotIn(self.config.api_key, client.log_path.read_text())

    def test_cache_invalidation_and_validation_not_cached(self):
        client = LLMClient(self.config, lambda *args: '{"ok":true}')
        client.ask("intake", "intake", {"description": "one"})
        client.ask("intake", "intake", {"description": "two"})
        client.config = replace(self.config, model="changed")
        client.ask("intake", "intake", {"description": "two"})
        client.config = replace(self.config, base_url="https://other.example/v1")
        client.ask("intake", "intake", {"description": "two"})
        prompts = Path(self.config.output_dir) / "prompts"
        prompts.mkdir()
        (prompts / "intake.txt").write_text("different prompt")
        client.config = replace(self.config, prompt_dir=prompts)
        client.ask("intake", "intake", {"description": "two"})
        self.assertEqual(client.totals["cache_hits"], 0)
        self.assertEqual(client.totals["estimated_calls"], 5)
        before = len(client.cache)
        with self.assertRaises(ValueError):
            client.ask("intake", "intake", {}, validator=lambda value: self.reject())
        self.assertEqual(len(client.cache), before)
        self.assertEqual(client.records[-1]["error_kind"], "validation")

    def test_hidden_context_invalidates_cache(self):
        client = LLMClient(self.config, lambda *args: '{"ok":true}')
        for context in ({"requirements": "one"}, {"requirements": "two"},
                        {"design": "changed"}, {"dbms_choice": "changed"}):
            client.ask("intake", "intake", {}, cache_context=context)
        self.assertEqual(client.totals["cache_hits"], 0)

    def test_http_usage_is_captured(self):
        from tests.test_llm import _Response

        class Response(_Response):
            def read(self):
                return json.dumps({"choices": [{"message": {"content": '{"ok":true}'}}],
                                   "usage": {"prompt_tokens": 10, "completion_tokens": 3}}).encode()

        with patch("dba_agent.llm.urllib.request.urlopen", return_value=Response()):
            client = LLMClient(self.config)
            client.ask("intake", "intake", {})
        self.assertEqual(client.totals["total_tokens"], 13)
        self.assertEqual(client.records[-1]["usage_source"], "provider")

    def test_partial_provider_usage_estimates_only_missing_count(self):
        response = {"choices": [{"message": {"content": '{"ok":true}'}}],
                    "usage": {"prompt_tokens": 10}}
        client = LLMClient(self.config, lambda *args: response)
        client.ask("intake", "intake", {})
        self.assertEqual(client.totals["input_tokens"], 10)
        self.assertGreater(client.totals["output_tokens"], 0)
        self.assertEqual(client.records[-1]["usage_source"], "mixed")

    @staticmethod
    def reject():
        raise ValueError("invalid shape")

    def test_network_and_json_retry_categories(self):
        client = LLMClient(self.config, lambda *args: "invalid json")
        with self.assertRaises(LLMError):
            client.ask("intake", "intake", {})
        self.assertEqual(client.records[-1]["error_kind"], "invalid_json")
        bodies = []

        def failing(url, key, body, timeout):
            bodies.append(json.dumps(body))
            raise NetworkError(key)

        client = LLMClient(self.config, failing)
        with self.assertRaises(LLMError) as error:
            client.ask("intake", "intake", {})
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(client.records[-1]["error_kind"], "network")
        self.assertNotIn(self.config.api_key, str(error.exception))
        self.assertNotIn(self.config.api_key, client.log_path.read_text())

    def test_deepseek_environment(self):
        with patch.dict(os.environ, {"DBA_AGENT_BASE_URL": "https://api.gapgpt.app/v1",
                        "DBA_AGENT_MODEL": "gapgpt-deepseek-v4.1-flash", "DBA_AGENT_API_KEY": "private"}, clear=True):
            config = Config.from_env()
        self.assertEqual(config.model, "gapgpt-deepseek-v4.1-flash")
        self.assertEqual(config.base_url, "https://api.gapgpt.app/v1")
        self.assertEqual(config.api_key, "private")

    def test_compact_interview_preserves_facts_and_history(self):
        session = Session()
        fact = "A detailed user fact. " * 100
        session.interview_rounds = [{"questions": [f"Question {i}"], "answers": {f"Question {i}": fact}} for i in range(6)]
        session.metadata["last_assessment"] = {"coverage": {"volume": True}, "missing_topics": ["backup"],
                                                "critical_contradictions": ["two limits"]}
        summary = interview_summary(session)
        self.assertEqual(summary["established_facts"], [fact.strip()])
        self.assertEqual(len(summary["previously_asked_questions"]), 6)
        self.assertEqual(summary["covered_categories"], ["volume"])
        self.assertEqual(summary["contradictions"], ["two limits"])
        self.assertEqual(len(summary["answer_facts"]), 6)
        self.assertLess(len(json.dumps(summary)), len(json.dumps(session.interview_rounds)) / 2)
        self.assertEqual(len(Session.from_dict(session.to_dict()).interview_rounds), 6)

    def test_reduced_sql_and_localized_repair(self):
        design = pipeline.model()
        reduced = sql_design(design)
        self.assertNotIn("normalization", reduced)
        self.assertEqual(reduced["tables"], design["tables"])
        local = repair_context("large schema", "large seed", design, "seed.sql does not populate customers", "SQLite")
        self.assertEqual(local["mode"], "append_seed")
        self.assertNotIn("previous_schema", local)
        fallback = repair_context("schema", "seed", design, "unknown syntax failure", "SQLite")
        self.assertEqual(fallback["design"], design)


class PayloadTests(unittest.TestCase):
    def interview_fixture(self):
        fixture = pipeline.PipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        agent, transport = fixture.service([
            {"actors": ["Customer"], "entities": ["customer", "order"],
             "processes": ["place order"], "requirements": ["keep records"], "ambiguities": []},
            {"questions": ["How many customers?"]},
        ])
        session = agent.create("Customers place orders")
        return fixture, agent, session

    def test_first_round_uses_one_call_even_when_ready(self):
        fixture, agent, session = self.interview_fixture()
        follow_up = {**fixture.assessment, "questions": ["What is peak writer concurrency?"]}
        follow_up.pop("requirements")
        agent.llm.transport = pipeline.ScriptedTransport([follow_up])
        session = agent.answer(session.session_id, {"How many customers?": "1000"})
        self.assertEqual(agent.llm.transport.calls, 1)
        self.assertEqual(session.pending_questions, follow_up["questions"])
        self.assertEqual(session.state, pipeline.Stage.INTERVIEWING)
        self.assertEqual(session.requirements, {})
        self.assertEqual(session.interview_rounds[0]["answers"]["How many customers?"], "1000")

    def test_bad_follow_up_keeps_answer_checkpoint_retryable(self):
        fixture, agent, session = self.interview_fixture()
        agent.llm.transport = lambda *args: json.dumps({**fixture.assessment, "questions": []})
        with self.assertRaises(pipeline.StateError):
            agent.answer(session.session_id, {"How many customers?": "1000"})
        saved = agent.get(session.session_id)
        self.assertEqual(len(saved.interview_rounds), 1)
        self.assertEqual(saved.interview_assessment, {})
        self.assertEqual(saved.pending_questions, [])
        follow_up = {**fixture.assessment, "questions": ["What is peak writer concurrency?"]}
        agent.llm.transport = pipeline.ScriptedTransport([follow_up])
        resumed = agent.advance(session.session_id)
        self.assertEqual(resumed.pending_questions, follow_up["questions"])

    def test_legacy_assessment_checkpoint_still_gets_questions(self):
        fixture, agent, session = self.interview_fixture()
        session.add_interview_round(session.pending_questions, {"How many customers?": "1000"})
        session.assess_interview(fixture.assessment)
        agent.store.save(session)
        agent.llm.transport = pipeline.ScriptedTransport([{"questions": ["What is peak concurrency?"]}])
        resumed = agent.advance(session.session_id)
        self.assertEqual(resumed.pending_questions, ["What is peak concurrency?"])

    def test_final_requirements_are_validated_before_checkpointing(self):
        fixture, agent, session = self.interview_fixture()
        session.add_interview_round(session.pending_questions, {"How many customers?": "1000"})
        session.set_questions(["What is peak concurrency?"])
        agent.store.save(session)
        invalid = {**fixture.assessment, "requirements": {"entities": "Customers"}}
        agent.llm.transport = lambda *args: json.dumps(invalid)
        with self.assertRaises(ValueError):
            agent.answer(session.session_id, {"What is peak concurrency?": "10 writers"})
        saved = agent.get(session.session_id)
        self.assertEqual(len(saved.interview_rounds), 2)
        self.assertEqual(saved.interview_assessment, {})
        self.assertEqual(saved.state, pipeline.Stage.INTERVIEWING)

    def test_localized_index_repair_executes_complete_scripts(self):
        fixture = pipeline.PipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        agent, session = fixture.through_design()
        agent.approve(session.session_id)
        broken = dict(fixture.sql)
        broken["schema_sql"] = broken["schema_sql"].split("CREATE INDEX")[0]
        responses = iter([broken, {"schema_fragment": "CREATE INDEX idx_order_customer ON orders(customer_id);"}])
        agent.llm.transport = lambda *args: json.dumps(next(responses))
        result = agent.generate_sql(session.session_id, verify_sqlite=True)
        self.assertTrue(result["verified_sqlite"])
        self.assertEqual(result["attempts"], 2)
        repair = agent.llm.records[-1]["input"]
        self.assertEqual(repair["mode"], "append_schema")
        self.assertNotIn("previous_schema", repair)
        self.assertNotIn("design", repair)

    def test_stage_payloads_and_persisted_usage(self):
        fixture = pipeline.PipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        agent, session = fixture.through_design()
        records = agent.llm.records
        interview = [r["input"] for r in records if r["stage"] == "interview"]
        self.assertTrue(all("interview_summary" in p and "rounds" not in p for p in interview))
        design = next(r["input"] for r in records if r["stage"] == "design")
        self.assertNotIn("intake", design)
        self.assertEqual(list(design["dbms_choice"]), ["selected"])
        self.assertGreater(agent.get(session.session_id).metadata["usage"]["input_tokens"], 0)

        output = {"reason": "Keep facts", "requirements": session.requirements, "design": session.design.model}
        agent.llm.transport = lambda *args: json.dumps(output)
        revised = agent.revise(session.session_id, "Clarify the customer description")
        payload = agent.llm.records[-1]["input"]
        self.assertNotIn("intake", payload)
        self.assertEqual(payload["dbms_choice"], {"selected": "SQLite"})
        self.assertEqual(revised.dbms_choice, session.dbms_choice)
