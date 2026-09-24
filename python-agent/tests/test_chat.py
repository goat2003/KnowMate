import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.chat import chat


def provider(output):
    return SimpleNamespace(provider_name="openai", client=SimpleNamespace(complete_json=lambda *args: json.dumps(output)))


def test_only_current_user_evidence_can_create_memory():
    output = {"reply": "明白了", "memory_updates": [
        {"key": "interests", "value": "Go", "evidence": "喜欢 Go"},
        {"key": "goal", "value": "面试", "evidence": "其他人的目标是面试"}
    ]}
    result = chat(provider(output), "我喜欢 Go", {"memory": {}, "history": []}, True)
    assert [m["key"] for m in result["memory_updates"]] == ["interests"]
    assert chat(provider(output), "我喜欢 Go", {}, False)["memory_updates"] == []


def test_unknown_memory_category_rejected():
    with pytest.raises(ValidationError):
        chat(provider({"reply": "你好", "memory_updates": [{"key": "api_key", "value": "secret", "evidence": "secret"}]}), "secret", {}, True)


def test_mock_mode_is_explicit_and_remembers_only_explicit_command():
    tool = SimpleNamespace(provider_name="mock")
    result = chat(tool, "记住兴趣：Go, 数据库", {}, True)
    assert result["mock"] is True
    assert result["memory_updates"][0]["value"] == "Go, 数据库"
    assert chat(tool, "记住兴趣：Go", {}, False)["memory_updates"] == []
    typed = chat(tool, "记住兴趣:Go，数据库", {}, True)
    assert typed["memory_updates"][0]["value"] == "Go,数据库"
    assert typed["memory_updates"][0]["evidence"] == "记住兴趣:Go，数据库"


def test_recommendations_come_only_from_supplied_articles():
    article = {"article_id": "a1", "title": "Go database engineering", "url": "https://go.dev/blog/example",
               "source": "go.dev", "raw_text": "Go database engineering connection pool " * 100,
               "published_at": "2026-09-19T00:00:00Z", "tags": None}
    result = chat(provider({"reply": "看看这些文章", "recommend": True}), "推荐 Go 内容",
                  {"memory": {"interests": "Go, database"}, "articles": [article]}, False)
    assert result["recommendations"]
    assert all(item["id"] == "a1" and item["url"] == article["url"] for item in result["recommendations"])
    empty = chat(provider({"reply": "看看这些文章", "recommend": True}), "推荐内容", {}, False)
    assert empty["recommendations"] == []
    assert "没有足够匹配" in empty["reply"]


def test_failed_real_provider_never_falls_back_to_mock():
    def fail(*args):
        raise RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError):
        chat(SimpleNamespace(provider_name="openai", client=SimpleNamespace(complete_json=fail)), "你好", {}, False)
