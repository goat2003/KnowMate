"""Bounded rehearsal-only chat acceptance; keeps visibly named test users."""
import json
import time
import uuid

from local_server import compose, folder, request, write


def api(path, body=None, method=None):
    status, raw = request("rehearsal", "/api" + path, body=body, method=method)
    data = json.loads(raw)
    if status != 200 or data.get("ok") is False:
        raise RuntimeError(f"{path}: HTTP {status}, {data}")
    return data


def send(uid, text, remember=True):
    body = {"user_id": uid, "request_id": str(uuid.uuid4()), "text": text, "remember": remember}
    result = api("/chat/messages", body, "POST")["result"]
    assert api("/chat/messages", body, "POST")["result"]["id"] == result["id"]
    for _ in range(60):
        messages = api("/chat/messages?user_id=" + uid)["items"]
        job = next(item for item in messages if item["id"] == result["id"])
        if job["status"] in {"completed", "failed"}:
            assert job["status"] == "completed", job
            return job
        time.sleep(1)
    raise RuntimeError("chat did not finish")


def main():
    uid = "chat-acceptance-" + uuid.uuid4().hex[:6]
    first = send(uid, "记住兴趣：agent, AI, LoRA")
    memories = api("/chat/memories?user_id=" + uid)["items"]
    assert len(memories) == 1 and memories[0]["value"] == "agent, AI, LoRA"
    send(uid, "记住目标：本条仅用于验收", False)
    assert len(api("/chat/memories?user_id=" + uid)["items"]) == 1
    context = send(uid, "你目前记得我哪些偏好？", False)
    assert "LoRA" in context["result"]["reply"]
    recommendations = send(uid, "根据我的兴趣推荐内容", False)
    assert recommendations["result"]["recommendations"], "expected ranked real-source recommendations"
    other = uid + "-other"
    assert api("/chat/memories?user_id=" + other)["items"] == []
    compose("rehearsal", "restart", "goframe-backend")
    for _ in range(30):
        try:
            if request("rehearsal", "/api/ready")[0] == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    assert api("/chat/memories?user_id=" + uid)["items"] == memories
    api("/chat/memories?user_id=" + uid, method="DELETE")
    after = send(uid, "你目前记得我哪些偏好？", False)
    assert "LoRA" not in after["result"]["reply"]
    assert api("/chat/memories?user_id=" + uid)["items"] == []
    report = {"user_id": uid, "duplicate_request_same_job": True, "memory_saved": True,
              "opt_out_respected": True, "conversation_reuses_memory": True, "cross_user_isolation": True,
              "recommendations": recommendations["result"]["recommendations"], "restart_persistence": True,
              "forget_not_resurrected": True, "mock_model": first["result"]["mock"], "real_wechat_delivery": False}
    write(folder("rehearsal") / "chat-acceptance.json", json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
