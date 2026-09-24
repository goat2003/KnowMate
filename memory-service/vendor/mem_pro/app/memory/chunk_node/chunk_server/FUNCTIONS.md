# app/memory/chunk_node/chunk_server Function Documentation（表格版）

---

# File: `chunk_service.py`

## Class: ChunkService

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化 Chunk storage、Milvus CRUD、utility service、embedding client，并确保 chunk_schema 存在 |
| 返回说明 | 构造函数无业务返回值 |

---

### washing_server_llm

| 字段 | 内容 |
|------|------|
| 函数名 | washing_server_llm |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | text: str, history: str |
| 返回类型 | str |
| 作用 | 构建 prompt 并调用 LLM，提取有效对话信息并更新 history |
| 返回说明 | 返回 LLM 输出（通常为 JSON 字符串） |

---

### save_llm_server

| 字段 | 内容 |
|------|------|
| 函数名 | save_llm_server |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | dialogues: List[dict], history: str |
| 返回类型 | Optional[tuple[str, List[str]]] |
| 作用 | 调用 LLM 清洗逻辑，最多重试三次并解析结果 |
| 返回说明 | 成功返回 (history, dialogues)，失败返回 None |

---

### single_round_chunk

| 字段 | 内容 |
|------|------|
| 函数名 | single_round_chunk |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, dialogues, history |
| 返回类型 | Optional[tuple[str, List[str]]] |
| 作用 | 单轮 Chunk 处理（hash 去重 + LLM + embedding + Neo4j + Milvus 写入） |
| 返回说明 | 返回 (history, chunk_uuids)，重复或跳过返回 None |

---

### chunk_save_in_milvus

| 字段 | 内容 |
|------|------|
| 函数名 | chunk_save_in_milvus |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, chunk_uuid, dia_embedding, summary_embedding |
| 返回类型 | None |
| 作用 | 将 Chunk 向量与元数据写入 Milvus |
| 返回说明 | 无返回值，失败由底层抛出异常 |

---

### create_all_chunks

| 字段 | 内容 |
|------|------|
| 函数名 | create_all_chunks |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, dialogues, split |
| 返回类型 | List[str] |
| 作用 | 按窗口切分对话并批量创建 Chunk |
| 返回说明 | 返回所有 chunk_uuid |

---

# File: `embedding_server.py`

---

### main

| 字段 | 内容 |
|------|------|
| 函数名 | main |
| 访问级别 | public |
| 类型 | module-level async function |
| 参数 | none |
| 返回类型 | None |
| 作用 | 用于测试 embedding client |
| 返回说明 | 无返回值 |

---

# File: `llm_test.py`

## Class: ChunkMain

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化测试类 |
| 返回说明 | 无业务返回值 |

---

### save_llm

| 字段 | 内容 |
|------|------|
| 函数名 | save_llm |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | dialogues: List[dict], history: str |
| 返回类型 | 未标注 |
| 作用 | 测试 LLM 清洗与保存逻辑 |
| 返回说明 | 依赖测试实现 |

---

### llm

| 字段 | 内容 |
|------|------|
| 函数名 | llm |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | dialogues: List[dict], history: str |
| 返回类型 | 未标注 |
| 作用 | 测试 LLM 调用流程 |
| 返回说明 | 依赖测试实现 |

---

### create_chunk

| 字段 | 内容 |
|------|------|
| 函数名 | create_chunk |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, dialogues, split |
| 返回类型 | List[str] |
| 作用 | 测试 Chunk 创建流程 |
| 返回说明 | 返回 chunk_uuid 列表（测试逻辑决定） |

---

### single_round_chunk_

| 字段 | 内容 |
|------|------|
| 函数名 | single_round_chunk_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | role_id, dialogues, history |
| 返回类型 | 未标注 |
| 作用 | 单轮 Chunk 创建测试版本 |
| 返回说明 | 依赖测试实现 |

---

## File: `__init__.py`

| 内容 | 说明 |
|------|------|
| 无函数定义 | 初始化文件 |