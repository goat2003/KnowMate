import os
import unittest

from app.config import LLMSettings, OpenAISettings
from app.tools.llm_tool import LLMClient, LLMTool, MockLLMClient, SummaryLLMOutput, build_llm_client


class BadThenGoodClient(LLMClient):
    provider_name = "bad-then-good"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return "not-json"
        return '{"summary":"修复后的摘要","issues":[]}'


class BadAlwaysClient(LLMClient):
    provider_name = "bad-always"

    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        return '{"summary": "", "issues": []}'


class LLMToolTest(unittest.TestCase):
    def test_mock_summary_output_is_valid_schema(self) -> None:
        tool = LLMTool(MockLLMClient())
        output = tool.summarize(
            {"title": "AI workflow", "raw_text": "A practical article about agent workflow."},
            {"interests": "AI"},
            "summary skill",
        )

        self.assertIsInstance(output, SummaryLLMOutput)
        self.assertTrue(output.summary.startswith("这篇文章"))
        self.assertEqual(output.issues, [])

    def test_json_repair_retry(self) -> None:
        client = BadThenGoodClient()
        tool = LLMTool(client)
        output = tool.summarize({"title": "T", "raw_text": "body"}, {}, "")

        self.assertEqual(output.summary, "修复后的摘要")
        self.assertEqual(client.calls, 2)

    def test_fallback_when_parse_and_repair_fail(self) -> None:
        tool = LLMTool(BadAlwaysClient())
        output = tool.summarize({"title": "T", "raw_text": "body"}, {}, "")

        self.assertTrue(output.summary)
        self.assertTrue(output.issues)
        self.assertIn("llm_fallback:bad-always", output.issues[0])

    def test_openai_without_api_key_falls_back_to_mock(self) -> None:
        os.environ.pop("MISSING_OPENAI_KEY", None)
        client, warnings = build_llm_client(
            LLMSettings(
                provider="openai",
                openai=OpenAISettings(api_key_env="MISSING_OPENAI_KEY"),
            )
        )

        self.assertIsInstance(client, MockLLMClient)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
