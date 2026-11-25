import json
import os
import unittest
from unittest.mock import patch

from dba_agent.config import Config
from dba_agent.llm import LLMClient


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": '{"ok": true}'}}]
        }).encode("utf-8")


class LLMClientTests(unittest.TestCase):
    @patch("dba_agent.llm.urllib.request.urlopen", return_value=_Response())
    def test_anonymous_request_omits_authorization_header(self, urlopen):
        client = LLMClient(Config(api_key=""))

        result = client._http(
            "https://ai-gateway.kilo.ai/api/v1/chat/completions",
            "",
            {"model": "kilo-auto/free", "messages": []},
            10,
        )

        request = urlopen.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(result, '{"ok": true}')

    @patch("dba_agent.llm.urllib.request.urlopen", return_value=_Response())
    def test_authenticated_request_uses_bearer_header(self, urlopen):
        client = LLMClient(Config(api_key="secret"))

        client._http(
            "https://ai-gateway.kilo.ai/api/v1/chat/completions",
            "secret",
            {"model": "some/paid-model", "messages": []},
            10,
        )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_kilo_api_key_is_supported_as_fallback(self):
        with patch.dict(os.environ, {"KILO_API_KEY": "kilo-secret"}, clear=True):
            self.assertEqual(Config.from_env().api_key, "kilo-secret")

    def test_project_api_key_takes_precedence(self):
        values = {"DBA_AGENT_API_KEY": "project-secret", "KILO_API_KEY": "kilo-secret"}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(Config.from_env().api_key, "project-secret")


if __name__ == "__main__":
    unittest.main()
