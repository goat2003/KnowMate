# Feedback Memory Profile Versioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Feedback Agent、Memory Agent 与 GoFrame 用户画像更新链路，使反馈处理幂等、画像可版本化、可追踪、可回滚，并支持失败补偿与推荐解释查询。

**Architecture:** Python Agent 负责结构化反馈抽取、画像权重合并、diff 生成与 MCP 调用；GoFrame 负责原始反馈、结构化反馈、画像版本、补偿任务、HTTP API 和 MySQL 审计。MySQL schema 使用 `init.sql` 加独立 migration 双轨更新，测试默认使用 mock、fake store 和本地 fixture，不依赖公网。

**Tech Stack:** GoFrame/Go、Python 3、grpcio/protobuf、MySQL 8、Milvus/Neo4j MCP mock transport、PowerShell test scripts。

---

## 工作区约束

当前仓库可能已有大量未提交改动。执行本计划时：

- 每个任务开始前运行 `git status --short`。
- 只读取或修改该任务列出的文件。
- 不使用 `git add .`。
- 每次提交只暂存当前任务文件。
- 不删除或回退用户已有改动。
- 默认文档和注释使用中文，代码标识使用英文。

## 文件结构

### Python Agent

- Modify: `python-agent/app/tools/llm_tool.py`
  - 扩展 `FeedbackLLMOutput`，增加 `structured_feedback`。
  - mock/fallback feedback 输出结构化三类信号。
- Modify: `python-agent/app/agents/feedback_agent.py`
  - 将 `structured_feedback` 写入 workflow state。
- Modify: `python-agent/app/agents/memory_agent.py`
  - 增加画像合并策略、权重 clamp、diff 生成和结构化反馈兼容解析。
- Modify: `python-agent/app/workflow/state.py`
  - 增加 `structured_feedback`、`profile_diff` typed fields。
- Modify: `python-agent/app/workflow/graph.py`
  - `process_feedback` 返回 `structured_feedback` 和 `profile_diff`。
- Modify: `python-agent/app/grpc_server.py`
  - 新 proto 字段和 Python dict 之间转换。
- Test: `python-agent/tests/test_workflow.py`
  - 覆盖结构化反馈、权重合并、diff、并发幂等缓存。

### Protobuf

- Modify: `proto/agent.proto`
- Modify: `shared/proto/agent.proto`
  - 只追加字段，不改变现有字段编号。
- Generated: `python-agent/agent_pb2.py`
- Generated: `python-agent/agent_pb2_grpc.py`
- Generated: `goframe-backend/internal/agentpb/agent.pb.go`
- Generated: `goframe-backend/internal/agentpb/agent_grpc.pb.go`
- Test: `goframe-backend/internal/agentpb/proto_contract_test.go`
- Test: `scripts/check_proto_contract.ps1`

### GoFrame Model/Store/Harness/API

- Modify: `goframe-backend/internal/model/model.go`
  - 增加 `UserProfileSnapshot`、`FeedbackRecord`、`MemoryCompensationTask`、`RecommendationExplanation` 等模型。
- Modify: `goframe-backend/internal/store/mysql.go`
  - 增加 feedback 幂等、画像 active/history/rollback、补偿任务、推荐解释 metadata 查询。
- Modify: `goframe-backend/internal/logic/harness/harness.go`
  - 调整 `ProcessFeedback` 为幂等版本化流程，增加补偿任务创建和 profile rebuild。
- Modify: `goframe-backend/internal/handler/handler.go`
  - 增加 `/profile`、`/profile/history`、`/profile/rollback`、`/recommendations/explain`、`/profile/rebuild`。
- Test: `goframe-backend/internal/store/mysql_test.go`
- Test: `goframe-backend/internal/logic/harness/crawler_test.go`
- Test: `goframe-backend/internal/logic/harness/feedback_test.go`
- Test: `goframe-backend/internal/handler/handler_test.go`

### SQL/Docs/Scripts

- Modify: `shared/sql/init.sql`
- Create: `shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql`
- Modify: `scripts/integration_test.ps1`
- Modify: `README.md`
- Modify: `shared/config/README.md`

---

## Task 1: Python 结构化反馈契约

**Files:**
- Modify: `python-agent/app/tools/llm_tool.py`
- Modify: `python-agent/app/agents/feedback_agent.py`
- Modify: `python-agent/app/workflow/state.py`
- Modify: `python-agent/app/workflow/graph.py`
- Test: `python-agent/tests/test_workflow.py`

- [ ] **Step 1: Write the failing test**

Add this test to `python-agent/tests/test_workflow.py` inside `ArticleWorkflowTest`:

```python
    def test_feedback_workflow_returns_structured_feedback(self) -> None:
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        result = workflow.process_feedback(
            {
                "run_id": "structured-feedback-run",
                "user_profile_snapshot": {"feedback_count": "0"},
                "mcp_policy": {
                    "mock_transport": True,
                    "enable_embedding": False,
                    "enable_milvus": False,
                    "enable_neo4j": False,
                },
                "feedback": [
                    {
                        "feedback_id": "f-structured",
                        "feedback_text": "这篇很有用，希望多保留工程实践细节，不要营销软文，风格更详细一点",
                        "feedback_type": "text",
                        "rating": 5,
                    }
                ],
            }
        )

        structured = result["structured_feedback"]
        self.assertIn("positive", structured)
        self.assertIn("negative", structured)
        self.assertIn("style_preferences", structured)
        self.assertTrue(structured["positive"])
        self.assertTrue(structured["style_preferences"])
        self.assertEqual(result["updated_profile_snapshot"]["last_structured_feedback"][:1], "{")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd python-agent
python -m unittest tests.test_workflow.ArticleWorkflowTest.test_feedback_workflow_returns_structured_feedback
```

Expected: FAIL with `KeyError: 'structured_feedback'` or missing `last_structured_feedback`.

- [ ] **Step 3: Extend `FeedbackLLMOutput`**

In `python-agent/app/tools/llm_tool.py`, change the feedback model to include:

```python
class FeedbackLLMOutput(BaseModel):
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    extracted_feedback: list[str] = Field(default_factory=list)
    structured_feedback: dict[str, Any] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
```

Update mock feedback JSON generation so it returns:

```python
structured = {
    "positive": [],
    "negative": [],
    "style_preferences": [],
    "raw_signals": [],
}
```

For each feedback item:

```python
if rating >= 4 or feedback_type in {"like", "favorite", "bookmark"}:
    structured["positive"].append({"topic": topic, "weight_delta": 0.08, "evidence": value})
elif rating <= 2 or feedback_type in {"dislike", "hide"}:
    structured["negative"].append({"topic": topic, "weight_delta": -0.1, "evidence": value})
if any(word in value.lower() for word in ["详细", "detail", "细节", "深入"]):
    structured["style_preferences"].append({"name": "detail_level", "value": "high", "confidence": 0.8})
```

The topic can be derived conservatively:

```python
topic = "工程实践" if "工程" in value or "practice" in value.lower() else "general"
```

Return JSON with `structured_feedback`.

- [ ] **Step 4: Wire `FeedbackAgent` state**

In `python-agent/app/agents/feedback_agent.py`, after `extracted_feedback`:

```python
        state["structured_feedback"] = output.structured_feedback
```

In `python-agent/app/workflow/state.py`, add:

```python
    structured_feedback: dict[str, Any]
    profile_diff: dict[str, Any]
```

In `python-agent/app/workflow/graph.py`, add to `process_feedback` return:

```python
            "structured_feedback": result.get("structured_feedback", {}),
            "profile_diff": result.get("profile_diff", {}),
```

- [ ] **Step 5: Preserve compatibility in MemoryAgent**

In `python-agent/app/agents/memory_agent.py`, before writing the final snapshot:

```python
        structured = dict(state.get("structured_feedback", {}))
        if structured:
            snapshot["last_structured_feedback"] = json.dumps(structured, ensure_ascii=False, sort_keys=True)
```

Add `import json`.

- [ ] **Step 6: Run test to verify it passes**

Run:

```powershell
cd python-agent
python -m unittest tests.test_workflow.ArticleWorkflowTest.test_feedback_workflow_returns_structured_feedback
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add -- python-agent/app/tools/llm_tool.py python-agent/app/agents/feedback_agent.py python-agent/app/agents/memory_agent.py python-agent/app/workflow/state.py python-agent/app/workflow/graph.py python-agent/tests/test_workflow.py
git commit -m "feat: add structured feedback signals"
```

---

## Task 2: MemoryAgent 权重合并、clamp 与 diff

**Files:**
- Modify: `python-agent/app/agents/memory_agent.py`
- Test: `python-agent/tests/test_workflow.py`

- [ ] **Step 1: Write failing tests**

Add these tests to `python-agent/tests/test_workflow.py` inside `ArticleWorkflowTest`:

```python
    def test_memory_agent_clamps_interest_weights_and_keeps_long_term_signal(self) -> None:
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        result = workflow.process_feedback(
            {
                "run_id": "weight-clamp-run",
                "user_profile_snapshot": {
                    "topics": "{\"AI\":0.95,\"工程实践\":0.60}",
                    "feedback_count": "0",
                },
                "mcp_policy": {"mock_transport": True},
                "feedback": [
                    {
                        "feedback_id": "f-weight",
                        "feedback_text": "非常有用，希望继续保留工程实践细节",
                        "rating": 5,
                    }
                ],
            }
        )

        topics = json.loads(result["updated_profile_snapshot"]["topics"])
        self.assertGreaterEqual(topics["AI"], 0.80)
        self.assertLessEqual(topics["工程实践"], 1.0)
        self.assertGreater(topics["工程实践"], 0.60)

    def test_memory_agent_applies_negative_and_style_feedback_differently(self) -> None:
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        result = workflow.process_feedback(
            {
                "run_id": "negative-style-run",
                "user_profile_snapshot": {
                    "topics": "{\"营销软文\":0.70}",
                    "feedback_count": "0",
                },
                "mcp_policy": {"mock_transport": True},
                "feedback": [
                    {
                        "feedback_id": "f-negative",
                        "feedback_text": "不想看营销软文，风格请更详细",
                        "rating": 1,
                    }
                ],
            }
        )

        snapshot = result["updated_profile_snapshot"]
        topics = json.loads(snapshot["topics"])
        negative_topics = json.loads(snapshot["negative_topics"])
        style = json.loads(snapshot["style_preferences"])
        self.assertLess(topics["营销软文"], 0.70)
        self.assertGreater(negative_topics["营销软文"], 0)
        self.assertEqual(style["detail_level"], "high")
        self.assertTrue(result["profile_diff"]["changes"])
```

Add `import json` at the top of the file.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd python-agent
python -m unittest `
  tests.test_workflow.ArticleWorkflowTest.test_memory_agent_clamps_interest_weights_and_keeps_long_term_signal `
  tests.test_workflow.ArticleWorkflowTest.test_memory_agent_applies_negative_and_style_feedback_differently
```

Expected: FAIL because `topics`, `negative_topics`, `style_preferences`, or `profile_diff` are missing.

- [ ] **Step 3: Add helper functions to MemoryAgent**

In `python-agent/app/agents/memory_agent.py`, add:

```python
def _json_object(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 4)
```

- [ ] **Step 4: Add structured merge methods**

Add methods to `MemoryAgent`:

```python
    def _merge_profile(self, snapshot: JsonDict, structured: JsonDict) -> tuple[JsonDict, JsonDict]:
        before = {
            "topics": _json_object(snapshot.get("topics")),
            "negative_topics": _json_object(snapshot.get("negative_topics")),
            "style_preferences": _json_object(snapshot.get("style_preferences")),
        }
        topics = {str(k): _clamp(_float(v)) for k, v in before["topics"].items()}
        negative_topics = {str(k): _clamp(_float(v)) for k, v in before["negative_topics"].items()}
        style_preferences = {str(k): str(v) for k, v in before["style_preferences"].items()}
        changes: list[JsonDict] = []

        for item in structured.get("positive", []) if isinstance(structured.get("positive", []), list) else []:
            topic = str(item.get("topic", "")).strip()
            if not topic:
                continue
            old = topics.get(topic, 0.0)
            signal = _clamp(abs(_float(item.get("weight_delta"), 0.08)))
            signal = min(signal, 0.12)
            new = _clamp(old * 0.92 + signal)
            topics[topic] = new
            changes.append({"path": f"topics.{topic}", "before": old, "after": new, "reason": "positive_feedback", "evidence": str(item.get("evidence", ""))})

        for item in structured.get("negative", []) if isinstance(structured.get("negative", []), list) else []:
            topic = str(item.get("topic", "")).strip()
            if not topic:
                continue
            old_negative = negative_topics.get(topic, 0.0)
            signal = min(_clamp(abs(_float(item.get("weight_delta"), 0.1))), 0.12)
            new_negative = _clamp(old_negative * 0.90 + signal)
            negative_topics[topic] = new_negative
            changes.append({"path": f"negative_topics.{topic}", "before": old_negative, "after": new_negative, "reason": "negative_feedback", "evidence": str(item.get("evidence", ""))})
            if topic in topics:
                old_topic = topics[topic]
                topics[topic] = _clamp(old_topic * 0.90)
                changes.append({"path": f"topics.{topic}", "before": old_topic, "after": topics[topic], "reason": "negative_feedback_decay", "evidence": str(item.get("evidence", ""))})

        for item in structured.get("style_preferences", []) if isinstance(structured.get("style_preferences", []), list) else []:
            name = str(item.get("name", "")).strip()
            value = str(item.get("value", "")).strip()
            if not name or not value:
                continue
            old = style_preferences.get(name)
            style_preferences[name] = value
            changes.append({"path": f"style_preferences.{name}", "before": old, "after": value, "reason": "style_preference", "evidence": str(item.get("evidence", ""))})

        snapshot["topics"] = json.dumps(topics, ensure_ascii=False, sort_keys=True)
        snapshot["negative_topics"] = json.dumps(negative_topics, ensure_ascii=False, sort_keys=True)
        snapshot["style_preferences"] = json.dumps(style_preferences, ensure_ascii=False, sort_keys=True)
        after = {"topics": topics, "negative_topics": negative_topics, "style_preferences": style_preferences}
        return snapshot, {"before": before, "after": after, "changes": changes}
```

- [ ] **Step 5: Call merge method from `run`**

In `MemoryAgent.run`, after `structured` is created:

```python
        if structured:
            snapshot, profile_diff = self._merge_profile(snapshot, structured)
        else:
            profile_diff = {"before": {}, "after": {}, "changes": []}
```

Before returning:

```python
        state["profile_diff"] = profile_diff
```

- [ ] **Step 6: Run tests to verify pass**

Run:

```powershell
cd python-agent
python -m unittest tests.test_workflow.ArticleWorkflowTest
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add -- python-agent/app/agents/memory_agent.py python-agent/tests/test_workflow.py
git commit -m "feat: merge feedback into bounded profile weights"
```

---

## Task 3: gRPC/protobuf 追加结构化反馈与 diff 字段

**Files:**
- Modify: `proto/agent.proto`
- Modify: `shared/proto/agent.proto`
- Modify: `python-agent/app/grpc_server.py`
- Generated: `python-agent/agent_pb2.py`
- Generated: `python-agent/agent_pb2_grpc.py`
- Generated: `goframe-backend/internal/agentpb/agent.pb.go`
- Generated: `goframe-backend/internal/agentpb/agent_grpc.pb.go`
- Test: `python-agent/tests/test_workflow.py`
- Test: `goframe-backend/internal/agentpb/proto_contract_test.go`
- Test: `scripts/check_proto_contract.ps1`

- [ ] **Step 1: Write failing Python gRPC test**

Add to `AgentServiceTest` in `python-agent/tests/test_workflow.py`:

```python
    def test_protobuf_service_process_feedback_returns_structured_fields(self) -> None:
        service = AgentService(Settings(mock_mcp=True))
        response = service.ProcessFeedback(
            agent_pb2.ProcessFeedbackRequest(
                run_id="grpc-structured-feedback",
                mcp_policy=agent_pb2.McpPolicy(mock_transport=True),
                feedback=[
                    agent_pb2.FeedbackItem(
                        feedback_id="f-grpc",
                        user_id="default-user",
                        feedback_text="有用，希望保留工程实践细节",
                        rating=5,
                    )
                ],
            ),
            None,
        )

        self.assertTrue(response.structured_feedback_json.startswith("{"))
        self.assertTrue(response.profile_diff_json.startswith("{"))
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
cd python-agent
python -m unittest tests.test_workflow.AgentServiceTest.test_protobuf_service_process_feedback_returns_structured_fields
```

Expected: ERROR because `structured_feedback_json` does not exist.

- [ ] **Step 3: Append proto fields**

In both `proto/agent.proto` and `shared/proto/agent.proto`, append fields to `ProcessFeedbackResponse`:

```proto
  // structured_feedback_json 保存 FeedbackAgent 抽取出的结构化反馈 JSON。
  string structured_feedback_json = 6;
  // profile_diff_json 保存 MemoryAgent 生成的画像变化差异 JSON。
  string profile_diff_json = 7;
```

Do not change fields 1-5.

- [ ] **Step 4: Regenerate protobuf files**

Run the repo’s existing proto generation command. If no script exists, use the same toolchain already used by the project:

```powershell
python -m grpc_tools.protoc `
  -I proto `
  --python_out=python-agent `
  --grpc_python_out=python-agent `
  proto/agent.proto

protoc `
  -I proto `
  --go_out=goframe-backend/internal/agentpb --go_opt=paths=source_relative `
  --go-grpc_out=goframe-backend/internal/agentpb --go-grpc_opt=paths=source_relative `
  proto/agent.proto
```

If local Go output path differs, inspect current generated package path before writing. Expected result: generated Python and Go files include getters for `StructuredFeedbackJson` and `ProfileDiffJson`.

- [ ] **Step 5: Wire Python gRPC conversion**

In `python-agent/app/grpc_server.py`, import `json` if needed and in `_process_feedback` response:

```python
            structured_feedback_json=json.dumps(result.get("structured_feedback", {}), ensure_ascii=False, sort_keys=True),
            profile_diff_json=json.dumps(result.get("profile_diff", {}), ensure_ascii=False, sort_keys=True),
```

- [ ] **Step 6: Update proto contract tests**

In `goframe-backend/internal/agentpb/proto_contract_test.go`, include the new field names in the expected descriptor assertions:

```go
"structured_feedback_json",
"profile_diff_json",
```

In `scripts/check_proto_contract.ps1`, include the same field names for `ProcessFeedbackResponse`.

- [ ] **Step 7: Run tests**

Run:

```powershell
cd python-agent
python -m unittest tests.test_workflow.AgentServiceTest.test_protobuf_service_process_feedback_returns_structured_fields

cd ..\goframe-backend
go test ./internal/agentpb -count=1
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add -- proto/agent.proto shared/proto/agent.proto python-agent/app/grpc_server.py python-agent/agent_pb2.py python-agent/agent_pb2_grpc.py goframe-backend/internal/agentpb/agent.pb.go goframe-backend/internal/agentpb/agent_grpc.pb.go goframe-backend/internal/agentpb/proto_contract_test.go scripts/check_proto_contract.ps1 python-agent/tests/test_workflow.py
git commit -m "feat: expose feedback profile diff in protobuf"
```

---

## Task 4: SQL schema 与 migration

**Files:**
- Modify: `shared/sql/init.sql`
- Create: `shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql`
- Modify: `goframe-backend/internal/store/mysql_test.go`

- [ ] **Step 1: Write schema contract test**

Add to `goframe-backend/internal/store/mysql_test.go`:

```go
func TestFeedbackMemoryProfileSchemaContracts(t *testing.T) {
	root := filepath.Join("..", "..", "..")
	for _, relativePath := range []string{
		filepath.Join("shared", "sql", "init.sql"),
		filepath.Join("shared", "sql", "migrations", "20260608_feedback_memory_profile_versioning.sql"),
	} {
		data, err := os.ReadFile(filepath.Join(root, relativePath))
		if err != nil {
			t.Fatalf("read %s: %v", relativePath, err)
		}
		sql := strings.ToLower(string(data))
		for _, required := range []string{
			"idempotency_key",
			"raw_feedback_json",
			"structured_feedback_json",
			"process_status",
			"profile_version",
			"diff_json",
			"is_active",
			"rolled_back_from_version",
			"memory_compensation_tasks",
			"posts",
			"metadata",
			"uk_feedback_idempotency",
			"uk_profile_user_version",
		} {
			if !strings.Contains(sql, required) {
				t.Fatalf("%s is missing %q", relativePath, required)
			}
		}
	}

	migration, err := os.ReadFile(filepath.Join(root, "shared", "sql", "migrations", "20260608_feedback_memory_profile_versioning.sql"))
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{"add_column_if_missing", "add_index_if_missing", "information_schema.columns", "information_schema.statistics"} {
		if !strings.Contains(strings.ToLower(string(migration)), required) {
			t.Fatalf("migration is missing idempotency contract %q", required)
		}
	}
}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
cd goframe-backend
go test ./internal/store -run TestFeedbackMemoryProfileSchemaContracts -count=1
```

Expected: FAIL because migration file and columns do not exist.

- [ ] **Step 3: Update `shared/sql/init.sql`**

Add columns to `posts`:

```sql
  metadata JSON NULL,
```

Add columns to `feedback_logs`:

```sql
  idempotency_key VARCHAR(128) NOT NULL DEFAULT '',
  raw_feedback_json JSON NULL,
  structured_feedback_json JSON NULL,
  process_status VARCHAR(32) NOT NULL DEFAULT 'received',
  profile_version INT NULL,
  error_message TEXT NULL,
  processed_at DATETIME NULL,
```

Add keys:

```sql
  UNIQUE KEY uk_feedback_idempotency (user_id, idempotency_key),
  KEY idx_feedback_status_created (process_status, created_at),
  KEY idx_feedback_user_profile_version (user_id, profile_version),
```

Add columns to `user_profile_snapshot`:

```sql
  version INT NOT NULL DEFAULT 1,
  base_version INT NULL,
  run_id VARCHAR(128) NOT NULL DEFAULT '',
  diff_json JSON NULL,
  change_reason VARCHAR(128) NOT NULL DEFAULT '',
  source_feedback_id BIGINT UNSIGNED NULL,
  is_active BOOLEAN NOT NULL DEFAULT FALSE,
  rolled_back_from_version INT NULL,
```

Add keys:

```sql
  UNIQUE KEY uk_profile_user_version (user_id, version),
  KEY idx_profile_user_active (user_id, is_active),
  KEY idx_profile_run_id (run_id),
```

Create new table:

```sql
CREATE TABLE IF NOT EXISTS memory_compensation_tasks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  task_id VARCHAR(128) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  user_id VARCHAR(128) NOT NULL,
  task_type VARCHAR(64) NOT NULL,
  target_system VARCHAR(32) NOT NULL,
  payload_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  attempt_count INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 5,
  next_retry_at DATETIME NULL,
  last_error TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_memory_compensation_task_id (task_id),
  KEY idx_memory_compensation_status_retry (status, next_retry_at),
  KEY idx_memory_compensation_run (run_id),
  KEY idx_memory_compensation_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 4: Create idempotent migration**

Create `shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql` with helper procedures:

```sql
DELIMITER //

CREATE PROCEDURE add_column_if_missing(
  IN table_name_value VARCHAR(128),
  IN column_name_value VARCHAR(128),
  IN ddl_value TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = table_name_value
      AND column_name = column_name_value
  ) THEN
    SET @ddl = ddl_value;
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//

CREATE PROCEDURE add_index_if_missing(
  IN table_name_value VARCHAR(128),
  IN index_name_value VARCHAR(128),
  IN ddl_value TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = table_name_value
      AND index_name = index_name_value
  ) THEN
    SET @ddl = ddl_value;
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//

DELIMITER ;
```

Then call `add_column_if_missing` and `add_index_if_missing` for every new column/index, create `memory_compensation_tasks`, backfill:

```sql
UPDATE feedback_logs SET idempotency_key = run_id WHERE idempotency_key = '';
UPDATE user_profile_snapshot s
JOIN (
  SELECT user_id, MAX(id) AS max_id
  FROM user_profile_snapshot
  GROUP BY user_id
) latest ON latest.user_id = s.user_id
SET s.version = 1,
    s.is_active = (s.id = latest.max_id)
WHERE s.version = 1;
```

Drop helper procedures at the end:

```sql
DROP PROCEDURE IF EXISTS add_column_if_missing;
DROP PROCEDURE IF EXISTS add_index_if_missing;
```

- [ ] **Step 5: Run schema contract test**

Run:

```powershell
cd goframe-backend
go test ./internal/store -run TestFeedbackMemoryProfileSchemaContracts -count=1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add -- shared/sql/init.sql shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql goframe-backend/internal/store/mysql_test.go
git commit -m "feat: add feedback profile versioning schema"
```

---

## Task 5: Store 模型、幂等反馈与画像版本读写

**Files:**
- Modify: `goframe-backend/internal/model/model.go`
- Modify: `goframe-backend/internal/store/mysql.go`
- Test: `goframe-backend/internal/store/mysql_test.go`

- [ ] **Step 1: Write pure helper tests**

Add to `goframe-backend/internal/store/mysql_test.go`:

```go
func TestFeedbackIdempotencyKeyIsStableAndContentSensitive(t *testing.T) {
	first := FeedbackIdempotencyKey("u1", "p1", "a1", "text", 5, "  有用  ")
	second := FeedbackIdempotencyKey("u1", "p1", "a1", "text", 5, "有用")
	different := FeedbackIdempotencyKey("u1", "p1", "a1", "text", 1, "有用")

	if first != second {
		t.Fatalf("expected normalized feedback text to produce same key")
	}
	if first == different {
		t.Fatalf("expected rating to affect key")
	}
	if len(first) != 64 {
		t.Fatalf("expected SHA-256 hex key, got %d", len(first))
	}
}

func TestProfileDiffDetectsChangedFields(t *testing.T) {
	diff := ProfileDiff(
		map[string]string{"topics": "{\"AI\":0.7}", "feedback_count": "1"},
		map[string]string{"topics": "{\"AI\":0.8}", "feedback_count": "2"},
		"feedback",
	)
	if len(diff.Changes) == 0 {
		t.Fatal("expected profile diff changes")
	}
}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd goframe-backend
go test ./internal/store -run "TestFeedbackIdempotencyKeyIsStableAndContentSensitive|TestProfileDiffDetectsChangedFields" -count=1
```

Expected: FAIL because helpers do not exist.

- [ ] **Step 3: Add model types**

In `goframe-backend/internal/model/model.go`, add:

```go
type FeedbackRecord struct {
	ID                     uint64         `json:"id"`
	RunID                  string         `json:"run_id"`
	PostUID                string         `json:"post_uid"`
	ArticleUID             string         `json:"article_uid"`
	UserID                 string         `json:"user_id"`
	FeedbackType           string         `json:"feedback_type"`
	Rating                 int            `json:"rating"`
	Comment                string         `json:"comment"`
	IdempotencyKey         string         `json:"idempotency_key"`
	RawFeedback            map[string]any `json:"raw_feedback"`
	StructuredFeedbackJSON string         `json:"structured_feedback_json"`
	ProcessStatus          string         `json:"process_status"`
	ProfileVersion         int            `json:"profile_version"`
	ErrorMessage           string         `json:"error_message"`
	CreatedAt              time.Time      `json:"created_at"`
}

type UserProfileSnapshot struct {
	ID                    uint64            `json:"id"`
	UserID                string            `json:"user_id"`
	Version               int               `json:"version"`
	BaseVersion           int               `json:"base_version"`
	RunID                 string            `json:"run_id"`
	Summary               string            `json:"summary"`
	Snapshot              map[string]string `json:"snapshot"`
	Diff                  map[string]any     `json:"diff"`
	ChangeReason          string            `json:"change_reason"`
	SourceFeedbackID      uint64            `json:"source_feedback_id"`
	IsActive              bool              `json:"is_active"`
	RolledBackFromVersion int               `json:"rolled_back_from_version"`
	CreatedAt             time.Time         `json:"created_at"`
}

type ProfileDiffChange struct {
	Path   string `json:"path"`
	Before any   `json:"before"`
	After  any   `json:"after"`
	Reason string `json:"reason"`
}

type ProfileDiffResult struct {
	Before  map[string]string  `json:"before"`
	After   map[string]string  `json:"after"`
	Changes []ProfileDiffChange `json:"changes"`
}

type MemoryCompensationTask struct {
	TaskID       string         `json:"task_id"`
	RunID        string         `json:"run_id"`
	UserID       string         `json:"user_id"`
	TaskType     string         `json:"task_type"`
	TargetSystem string         `json:"target_system"`
	Payload      map[string]any `json:"payload"`
	Status       string         `json:"status"`
	LastError    string         `json:"last_error"`
}
```

- [ ] **Step 4: Add helper functions**

In `goframe-backend/internal/store/mysql.go`, add exported helpers:

```go
func FeedbackIdempotencyKey(userID, postID, articleID, feedbackType string, rating int, text string) string {
	normalizedText := strings.Join(strings.Fields(strings.TrimSpace(text)), " ")
	value := strings.Join([]string{userID, postID, articleID, feedbackType, fmt.Sprintf("%d", rating), normalizedText}, "\x00")
	return fmt.Sprintf("%x", sha256.Sum256([]byte(value)))
}

func ProfileDiff(before map[string]string, after map[string]string, reason string) model.ProfileDiffResult {
	result := model.ProfileDiffResult{Before: before, After: after, Changes: []model.ProfileDiffChange{}}
	keys := map[string]struct{}{}
	for key := range before {
		keys[key] = struct{}{}
	}
	for key := range after {
		keys[key] = struct{}{}
	}
	for key := range keys {
		if before[key] != after[key] {
			result.Changes = append(result.Changes, model.ProfileDiffChange{Path: key, Before: before[key], After: after[key], Reason: reason})
		}
	}
	return result
}
```

- [ ] **Step 5: Add store method signatures**

In `Store`, implement:

```go
func (s *Store) UpsertFeedbackReceived(ctx context.Context, feedback model.FeedbackLog, idempotencyKey string, raw map[string]any) (model.FeedbackRecord, bool, error)
func (s *Store) MarkFeedbackProcessing(ctx context.Context, id uint64) error
func (s *Store) MarkFeedbackCompleted(ctx context.Context, id uint64, structuredJSON string, profileVersion int) error
func (s *Store) MarkFeedbackFailed(ctx context.Context, id uint64, message string) error
func (s *Store) ActiveUserProfileSnapshot(ctx context.Context, userID string) (model.UserProfileSnapshot, error)
func (s *Store) ListUserProfileSnapshots(ctx context.Context, userID string, limit int) ([]model.UserProfileSnapshot, error)
func (s *Store) InsertUserProfileSnapshotVersion(ctx context.Context, snapshot model.UserProfileSnapshot) (model.UserProfileSnapshot, error)
func (s *Store) RollbackUserProfileSnapshot(ctx context.Context, userID string, targetVersion int, reason string) (model.UserProfileSnapshot, error)
func (s *Store) InsertMemoryCompensationTask(ctx context.Context, task model.MemoryCompensationTask) error
```

Keep old `LatestUserProfileSnapshot` and `InsertUserProfileSnapshot` as compatibility wrappers around active/versioned methods.

- [ ] **Step 6: Run helper tests**

Run:

```powershell
cd goframe-backend
go test ./internal/store -run "TestFeedbackIdempotencyKeyIsStableAndContentSensitive|TestProfileDiffDetectsChangedFields" -count=1
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add -- goframe-backend/internal/model/model.go goframe-backend/internal/store/mysql.go goframe-backend/internal/store/mysql_test.go
git commit -m "feat: add profile version store primitives"
```

---

## Task 6: Harness 反馈幂等、版本化和补偿任务

**Files:**
- Modify: `goframe-backend/internal/logic/harness/harness.go`
- Create: `goframe-backend/internal/logic/harness/feedback_test.go`

- [ ] **Step 1: Write fake-store feedback tests**

Create `goframe-backend/internal/logic/harness/feedback_test.go` with:

```go
package harness

import (
	"context"
	"testing"

	"knowledge-post-agent/goframe-backend/internal/config"
	"knowledge-post-agent/goframe-backend/internal/model"
)

func TestProcessFeedbackReturnsCompletedResultForDuplicateFeedback(t *testing.T) {
	store := newFeedbackFakeStore()
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})
	req := FeedbackRequest{PostID: "p1", ArticleID: "a1", UserID: "u1", FeedbackText: "有用", FeedbackType: "text", Rating: 5}

	first := h.ProcessFeedback(context.Background(), req)
	second := h.ProcessFeedback(context.Background(), req)

	if first.Status != "completed" || second.Status != "completed" {
		t.Fatalf("expected completed duplicate results: %#v %#v", first, second)
	}
	if store.agentCalls != 1 {
		t.Fatalf("expected one agent call, got %d", store.agentCalls)
	}
	if len(store.profiles) != 1 {
		t.Fatalf("expected one profile version, got %d", len(store.profiles))
	}
}

func TestFailedMcpLogsCreateCompensationTasks(t *testing.T) {
	store := newFeedbackFakeStore()
	store.nextMcpLogs = []model.McpCallLog{{RunID: "r1", AgentName: "memory", ServerName: "milvus-mcp", ToolName: "insert_memory_vector", Status: "failed", Success: false, ErrorMessage: "milvus down"}}
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})

	result := h.ProcessFeedback(context.Background(), FeedbackRequest{PostID: "p1", UserID: "u1", FeedbackText: "有用", Rating: 5})

	if result.Status != "completed" {
		t.Fatalf("expected completed with compensation, got %#v", result)
	}
	if len(store.compensationTasks) != 1 || store.compensationTasks[0].TargetSystem != "milvus" {
		t.Fatalf("expected milvus compensation task, got %#v", store.compensationTasks)
	}
}
```

Implement `feedbackFakeStore` in the same test file with the `articleStore` methods plus fields to simulate duplicate feedback. Use `store.agentCalls` by introducing a test hook in Harness in Step 3.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd goframe-backend
go test ./internal/logic/harness -run "TestProcessFeedbackReturnsCompletedResultForDuplicateFeedback|TestFailedMcpLogsCreateCompensationTasks" -count=1
```

Expected: FAIL because harness lacks idempotent store methods/test hook.

- [ ] **Step 3: Add feedback agent test hook**

In `Harness`, add optional field:

```go
	processFeedbackFunc func(context.Context, string, string, FeedbackRequest, map[string]string, *stepRecorder) (*agentpb.ProcessFeedbackResponse, error)
```

In `callProcessFeedback` call sites, use:

```go
	if h.processFeedbackFunc != nil {
		return h.processFeedbackFunc(ctx, runID, userID, req, profile, steps)
	}
```

This keeps production behavior unchanged and lets unit tests avoid real gRPC.

- [ ] **Step 4: Extend articleStore interface**

Add the new store methods from Task 5 to `articleStore`.

Update existing fake stores in `crawler_test.go` to satisfy the interface with no-op/default implementations.

- [ ] **Step 5: Modify ProcessFeedback flow**

In `ProcessFeedback`:

1. Compute idempotency key from request.
2. Call `UpsertFeedbackReceived`.
3. If existing completed record is returned, build `FeedbackResult` from stored structured feedback/profile version metadata.
4. Mark processing.
5. Load active profile.
6. Call Agent.
7. Read `StructuredFeedbackJson` and `ProfileDiffJson` from response.
8. Insert profile version using `InsertUserProfileSnapshotVersion`.
9. Mark feedback completed.
10. Insert MCP logs.
11. For failed MCP logs, call `InsertMemoryCompensationTask`.

Use step names:

- `save_feedback`
- `feedback_idempotent_hit`
- `process_feedback`
- `save_profile_version`
- `save_mcp_logs`
- `create_compensation`

- [ ] **Step 6: Run harness tests**

Run:

```powershell
cd goframe-backend
go test ./internal/logic/harness -count=1
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add -- goframe-backend/internal/logic/harness/harness.go goframe-backend/internal/logic/harness/feedback_test.go goframe-backend/internal/logic/harness/crawler_test.go
git commit -m "feat: make feedback processing idempotent"
```

---

## Task 7: HTTP Profile、History、Rollback、Explanation、Rebuild APIs

**Files:**
- Modify: `goframe-backend/internal/handler/handler.go`
- Modify: `goframe-backend/internal/logic/harness/harness.go`
- Modify: `goframe-backend/internal/store/mysql.go`
- Create: `goframe-backend/internal/handler/handler_test.go`

- [ ] **Step 1: Write handler route tests**

Create `goframe-backend/internal/handler/handler_test.go` with focused tests for route registration and JSON request decoding. If direct GoFrame HTTP tests are too heavy, test handler methods with a fake store/harness and `httptest`.

Minimum test names:

```go
func TestProfileHandlersReturnJSON(t *testing.T)
func TestRollbackProfileRequiresTargetVersion(t *testing.T)
func TestRecommendationExplanationReturnsStoredMetadata(t *testing.T)
func TestProfileRebuildReturnsRunResult(t *testing.T)
```

Assertions:

- `GET /profile` returns `ok: true`.
- `GET /profile/history` returns `items`.
- `POST /profile/rollback` without target version returns `ok: false`.
- `GET /recommendations/explain` returns `explanation`.
- `POST /profile/rebuild` returns `result`.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd goframe-backend
go test ./internal/handler -count=1
```

Expected: FAIL because routes/handlers do not exist or dependencies are not injectable.

- [ ] **Step 3: Register routes**

In `Handler.Register`, add:

```go
		group.GET("/profile", h.GetProfile)
		group.GET("/profile/history", h.ListProfileHistory)
		group.POST("/profile/rollback", h.RollbackProfile)
		group.GET("/recommendations/explain", h.GetRecommendationExplanation)
		group.POST("/profile/rebuild", h.RebuildProfile)
```

- [ ] **Step 4: Add request/response structs**

In `handler.go` or harness if business logic belongs there:

```go
type RollbackProfileRequest struct {
	UserID        string `json:"user_id"`
	TargetVersion int   `json:"target_version"`
	Reason        string `json:"reason"`
}

type RebuildProfileRequest struct {
	UserID      string `json:"user_id"`
	FromVersion int   `json:"from_version"`
	DryRun      bool   `json:"dry_run"`
}
```

- [ ] **Step 5: Implement handlers**

Handlers should call store/harness:

- `GetProfile`: `store.ActiveUserProfileSnapshot`
- `ListProfileHistory`: `store.ListUserProfileSnapshots`
- `RollbackProfile`: `store.RollbackUserProfileSnapshot`
- `GetRecommendationExplanation`: new `store.RecommendationExplanationByPostID`
- `RebuildProfile`: `harness.RebuildProfile`

Use `queryLimit(r)` for history limit.

- [ ] **Step 6: Implement `RebuildProfile` minimal flow**

In harness, add:

```go
type RebuildProfileResult struct {
	RunID string `json:"run_id"`
	Status string `json:"status"`
	UserID string `json:"user_id"`
ProfileVersion int `json:"profile_version"`
	Error string `json:"error,omitempty"`
	Steps []StepLog `json:"steps"`
}
```

First implementation can create a `profile_rebuild` compensation task and return `completed` when task creation succeeds. The full replay can be Task 9.

- [ ] **Step 7: Run handler tests**

Run:

```powershell
cd goframe-backend
go test ./internal/handler -count=1
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add -- goframe-backend/internal/handler/handler.go goframe-backend/internal/handler/handler_test.go goframe-backend/internal/logic/harness/harness.go goframe-backend/internal/store/mysql.go
git commit -m "feat: add profile and recommendation APIs"
```

---

## Task 8: Recommendation explanation persistence

**Files:**
- Modify: `goframe-backend/internal/model/model.go`
- Modify: `goframe-backend/internal/store/mysql.go`
- Modify: `goframe-backend/internal/logic/harness/harness.go`
- Test: `goframe-backend/internal/logic/harness/feedback_test.go`
- Test: `goframe-backend/internal/store/mysql_test.go`

- [ ] **Step 1: Write failing metadata test**

Add a test that calls `persistAgentResults` with an `ArticleProcessResult` containing score breakdown/reasons and asserts `InsertPost` receives `Post.Metadata` containing:

- `score`
- `rank_position`
- `score_breakdown`
- `recommendation_reasons`
- `rejection_reasons`
- `profile_version`

Expected failure: `model.Post` has no `Metadata` or harness does not set it.

- [ ] **Step 2: Add `Metadata` to model.Post**

In `model.Post`:

```go
	Metadata map[string]any `json:"metadata"`
```

- [ ] **Step 3: Update InsertPost/ListPosts**

In `InsertPost`, marshal `post.Metadata` and include `metadata` column.

In `ListPosts`, select `COALESCE(CAST(metadata AS CHAR), '{}')` and unmarshal into `post.Metadata`.

- [ ] **Step 4: Populate metadata in `persistAgentResults`**

When creating `post`, set:

```go
Metadata: map[string]any{
	"score": item.Score,
	"rank_position": item.RankPosition,
	"score_breakdown": item.ScoreBreakdown,
	"recommendation_reasons": item.RecommendationReasons,
	"rejection_reasons": item.RejectionReasons,
	"profile_version": profileVersion,
},
```

If `profileVersion` is not available in RunArticles yet, pass latest active profile version through `loadProfile` by adding a helper that returns both snapshot and version.

- [ ] **Step 5: Implement explanation query**

In store:

```go
func (s *Store) RecommendationExplanationByPostID(ctx context.Context, postID string) (model.RecommendationExplanation, error)
```

Query `posts.metadata` and related `mcp_call_logs` by run id prefix or stored metadata. Keep first version simple: return metadata plus `post_uid` and `article_uid`.

- [ ] **Step 6: Run tests**

Run:

```powershell
cd goframe-backend
go test ./internal/logic/harness ./internal/store -count=1
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add -- goframe-backend/internal/model/model.go goframe-backend/internal/store/mysql.go goframe-backend/internal/logic/harness/harness.go goframe-backend/internal/logic/harness/feedback_test.go goframe-backend/internal/store/mysql_test.go
git commit -m "feat: persist recommendation explanations"
```

---

## Task 9: Profile rebuild replay

**Files:**
- Modify: `goframe-backend/internal/store/mysql.go`
- Modify: `goframe-backend/internal/logic/harness/harness.go`
- Test: `goframe-backend/internal/logic/harness/feedback_test.go`

- [ ] **Step 1: Write failing rebuild replay test**

Add:

```go
func TestProfileRebuildReplaysStructuredFeedback(t *testing.T) {
	store := newFeedbackFakeStore()
	store.completedFeedback = []model.FeedbackRecord{
		{UserID: "u1", StructuredFeedbackJSON: `{"positive":[{"topic":"工程实践","weight_delta":0.08,"evidence":"有用"}],"negative":[],"style_preferences":[]}`},
	}
	h := newWithDependencies(config.Config{Profile: config.ProfileConfig{UserID: "u1"}}, store, &fakeSourceCrawler{})

	result := h.RebuildProfile(context.Background(), RebuildProfileRequest{UserID: "u1"})

	if result.Status != "completed" {
		t.Fatalf("expected completed rebuild, got %#v", result)
	}
	if len(store.profiles) != 1 {
		t.Fatalf("expected rebuilt profile version, got %#v", store.profiles)
	}
	if store.profiles[0].ChangeReason != "rebuild" {
		t.Fatalf("expected rebuild reason, got %#v", store.profiles[0])
	}
}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
cd goframe-backend
go test ./internal/logic/harness -run TestProfileRebuildReplaysStructuredFeedback -count=1
```

Expected: FAIL because replay method does not exist or only creates task.

- [ ] **Step 3: Add store query**

Add:

```go
func (s *Store) ListCompletedStructuredFeedback(ctx context.Context, userID string) ([]model.FeedbackRecord, error)
```

Query completed feedback where `structured_feedback_json` is not null/empty.

- [ ] **Step 4: Implement minimal Go replay**

In harness, implement deterministic replay for structured JSON:

- Start from configured default profile or `from_version` snapshot.
- Parse positive/negative/style arrays.
- Reuse conservative clamp rules from Python for Go rebuild.
- Insert active profile version with `change_reason = "rebuild"`.

This intentionally mirrors Python strategy without calling LLM.

- [ ] **Step 5: Run tests**

Run:

```powershell
cd goframe-backend
go test ./internal/logic/harness -count=1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add -- goframe-backend/internal/store/mysql.go goframe-backend/internal/logic/harness/harness.go goframe-backend/internal/logic/harness/feedback_test.go
git commit -m "feat: rebuild profiles from structured feedback"
```

---

## Task 10: Integration script and documentation

**Files:**
- Modify: `scripts/integration_test.ps1`
- Modify: `README.md`
- Modify: `shared/config/README.md`

- [ ] **Step 1: Update integration script migration check**

In `scripts/integration_test.ps1`, add the new migration to the temporary MySQL section:

```powershell
$profileMigration = Get-Content -Raw "$RootDir\shared\sql\migrations\20260608_feedback_memory_profile_versioning.sql"
$profileMigration | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
$profileMigration | docker exec -i -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent
$profileColumns = docker exec -e MYSQL_PWD=rootpass $migrationContainer mysql -uroot knowledge_post_agent -N -e "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='user_profile_snapshot' AND column_name IN ('version','diff_json','is_active');"
if ([int]$profileColumns.Trim() -lt 3) { throw "profile versioning migration did not create expected columns" }
```

- [ ] **Step 2: Update README API docs**

Add a section with:

```markdown
### Profile Memory APIs

- `GET /profile?user_id=default-user`
- `GET /profile/history?user_id=default-user&limit=20`
- `POST /profile/rollback`
- `GET /recommendations/explain?post_id=...`
- `POST /profile/rebuild`
```

Include one curl example for rollback and one for explanation.

- [ ] **Step 3: Update shared config README**

Document new MySQL tables/columns and compensation task purpose.

- [ ] **Step 4: Run docs/script sanity checks**

Run:

```powershell
Select-String -Path README.md -Pattern "/profile/history","/recommendations/explain","/profile/rebuild"
Select-String -Path shared/config/README.md -Pattern "memory_compensation_tasks","user_profile_snapshot"
```

Expected: all patterns found.

- [ ] **Step 5: Commit**

```powershell
git add -- scripts/integration_test.ps1 README.md shared/config/README.md
git commit -m "docs: document profile memory APIs"
```

---

## Task 11: Verification

**Files:**
- No production edits expected.

- [ ] **Step 1: Run Python unit tests**

```powershell
cd python-agent
python -m unittest
```

Expected: PASS.

- [ ] **Step 2: Run Go unit tests**

```powershell
cd goframe-backend
go test ./... -count=1
```

Expected: PASS.

- [ ] **Step 3: Run Go vet**

```powershell
cd goframe-backend
go vet ./...
```

Expected: PASS.

- [ ] **Step 4: Run focused race tests**

```powershell
cd goframe-backend
go test -race ./internal/logic/harness ./internal/store -count=1
```

Expected: PASS.

- [ ] **Step 5: Run migration integration check**

```powershell
.\scripts\integration_test.ps1
```

Expected: PASS. If Docker image pull fails with mirror `EOF` or local port `3306` conflict, classify as environment issue and record exact error.

- [ ] **Step 6: Review final diff**

```powershell
git status --short
git diff --stat HEAD
```

Expected: only current task files are modified/untracked after final task; no unrelated user changes staged.

---

## 自检

- Spec requirement coverage:
  - 幂等反馈：Task 5、Task 6。
  - 原始反馈和结构化反馈保存：Task 1、Task 3、Task 5、Task 6。
  - 每次画像更新新版本：Task 4、Task 5、Task 6。
  - 版本历史查询：Task 5、Task 7。
  - 回滚画像：Task 5、Task 7。
  - 兴趣权重范围：Task 2、Task 9。
  - 短期不覆盖长期：Task 2。
  - 正/负/风格策略：Task 1、Task 2、Task 9。
  - Milvus/Neo4j/MySQL 重试补偿：Task 4、Task 6、Task 10。
  - 画像 diff：Task 2、Task 5、Task 6。
  - 查看画像 API：Task 7。
  - 历史 API：Task 7。
  - 回滚 API：Task 7。
  - 推荐解释 API：Task 7、Task 8。
  - 重建画像任务：Task 7、Task 9。
  - 并发/重复/部分失败测试：Task 3、Task 6、Task 11。
- Placeholder scan: plan content contains no unfinished placeholder markers.
- Type consistency:
  - Python fields: `structured_feedback`, `profile_diff`, `structured_feedback_json`, `profile_diff_json` are consistent across workflow and gRPC.
  - Go models: `FeedbackRecord`, `UserProfileSnapshot`, `MemoryCompensationTask` are referenced consistently.
  - Store methods are listed before harness/API tasks use them.
