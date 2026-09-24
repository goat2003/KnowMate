# app/memory/chunk_node/chunk_graph Function Documentation（表格版）

---

# File: `chunk_store.py`

## Class: ChunkStore

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化 Neo4j manager 与 utility service |
| 返回说明 | 构造函数无业务返回值 |

---

### create_chunk

| 字段 | 内容 |
|------|------|
| 函数名 | create_chunk |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, dialogue, summary, timestamp, hash_val |
| 返回类型 | str |
| 作用 | 创建 ChunkNode 并与 UserInfoNode 建立 HAS_CHUNK 关系 |
| 返回说明 | 返回 chunk_uuid；无结果时返回 None |

---

### get_chunk_by_uuid

| 字段 | 内容 |
|------|------|
| 函数名 | get_chunk_by_uuid |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid |
| 返回类型 | List[Dict] |
| 作用 | 根据 UUID 查询单个 Chunk |
| 返回说明 | 返回结果列表；无结果返回空列表 |

---

### get_chunk_by_role_id

| 字段 | 内容 |
|------|------|
| 函数名 | get_chunk_by_role_id |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id |
| 返回类型 | List[Dict] |
| 作用 | 查询某个用户的所有 Chunk |
| 返回说明 | 返回结果列表；无结果返回空列表 |

---

### get_chunk_summary_by_role_id

| 字段 | 内容 |
|------|------|
| 函数名 | get_chunk_summary_by_role_id |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id |
| 返回类型 | List[str] |
| 作用 | 获取用户所有 Chunk 的 summary 并扁平化 |
| 返回说明 | 返回 summary 列表；无结果返回空列表 |

---

### get_chunk_summary_by_uuid

| 字段 | 内容 |
|------|------|
| 函数名 | get_chunk_summary_by_uuid |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid |
| 返回类型 | Optional[str] |
| 作用 | 根据 UUID 获取 Chunk summary |
| 返回说明 | 存在则返回 summary，否则返回 None |

---

### query_exist_by_hash

| 字段 | 内容 |
|------|------|
| 函数名 | query_exist_by_hash |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | hash_val |
| 返回类型 | bool |
| 作用 | 判断 Chunk 是否已存在（基于 hash） |
| 返回说明 | 存在返回 True，否则 False |

---

## File: `__init__.py`

| 内容 | 说明 |
|------|------|
| 无函数定义 | 初始化文件 |