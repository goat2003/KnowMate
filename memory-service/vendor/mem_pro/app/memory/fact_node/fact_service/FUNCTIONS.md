# app/memory/fact_node/fact_service Function Documentation（表格版）

---

# File: `fact_pipeline_copy.py`

## Class: BuildOriFact

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化 ChunkStore、MilvusCRUD、FactLLMExtractor、FactStore、importance scoring service |
| 返回说明 | 构造函数无业务返回值 |

---

### get_chunk_summary_embedding

| 字段 | 内容 |
|------|------|
| 函数名 | get_chunk_summary_embedding |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid |
| 返回类型 | Optional[tuple[str, List]] |
| 作用 | 从 Neo4j 获取 Chunk summary，并从 Milvus 获取 summary embedding |
| 返回说明 | 返回 (chunk_summary, summary_embedding) |

---

### chunk_match_ori_fact

| 字段 | 内容 |
|------|------|
| 函数名 | chunk_match_ori_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, chunk_embedding |
| 返回类型 | str | None |
| 作用 | 在 Milvus 中匹配是否存在相似 OriginalFact |
| 返回说明 | 返回匹配 OriFact UUID 或 None |

---

### merge_chunk_to_ori_fact

| 字段 | 内容 |
|------|------|
| 函数名 | merge_chunk_to_ori_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | ori_fact_uuid, chunk_uuid, topic |
| 返回类型 | None |
| 作用 | 更新 OriginalFact 并绑定 Chunk，同时更新 Milvus 向量 |
| 返回说明 | 无返回值 |

---

### create_ori_fact_

| 字段 | 内容 |
|------|------|
| 函数名 | create_ori_fact_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | chunk_uuid, role_id, topic |
| 返回类型 | None |
| 作用 | 创建 OriginalFact 并写入 Milvus |
| 返回说明 | 无返回值 |

---

## Class: BuildDevFact

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化 DerivedFact 构建所需组件 |
| 返回说明 | 无业务返回值 |

---

### get_dev_topic_from_chunk

| 字段 | 内容 |
|------|------|
| 函数名 | get_dev_topic_from_chunk |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_summary |
| 返回类型 | str | None |
| 作用 | 使用 LLM 判断是否生成 DerivedFact topic |
| 返回说明 | 返回 topic 或 None |

---

### dev_summary_match_dev_fact

| 字段 | 内容 |
|------|------|
| 函数名 | dev_summary_match_dev_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, dev_topic |
| 返回类型 | str | None |
| 作用 | 在 Milvus 中匹配已有 DerivedFact |
| 返回说明 | 返回匹配 UUID 或 None |

---

### merge_chunk_to_dev_fact

| 字段 | 内容 |
|------|------|
| 函数名 | merge_chunk_to_dev_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | dev_uuid, chunk_uuid, topic, confidence |
| 返回类型 | str | None |
| 作用 | 更新 DerivedFact（状态/权重/向量等） |
| 返回说明 | 返回稳定 topic 或 None |

---

### create_dev_fact_milvus

| 字段 | 内容 |
|------|------|
| 函数名 | create_dev_fact_milvus |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid, role_id, topic |
| 返回类型 | None |
| 作用 | 创建 DerivedFact 并写入 Milvus |
| 返回说明 | 无返回值 |

---

### delete_expired_node

| 字段 | 内容 |
|------|------|
| 函数名 | delete_expired_node |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 删除 Neo4j + Milvus 中过期 DerivedFact |
| 返回说明 | 无返回值 |

---

## Class: BuildEntity

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化 Entity 构建依赖（LLM/embedding/store） |
| 返回说明 | 无业务返回值 |

---

### semantic_match_entity

| 字段 | 内容 |
|------|------|
| 函数名 | semantic_match_entity |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, entity_name, entity_type, semantic_embedding |
| 返回类型 | Optional[Tuple[str, str]] |
| 作用 | 在 Milvus 中语义匹配 Entity |
| 返回说明 | 返回匹配实体信息或 None |

---

### entity_embed_save

| 字段 | 内容 |
|------|------|
| 函数名 | entity_embed_save |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, chunk_uuid, llm_result |
| 返回类型 | None |
| 作用 | Entity embedding + 创建/复用 + 与 Chunk 关联 + 写入 Milvus |
| 返回说明 | 无返回值 |

---

# File: `fact_pipeline_main.py`

## Class: FPMain

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化 Fact pipeline 组件（Ori/Dev/Entity/LLM/Store/UserInfo） |
| 返回说明 | 无业务返回值 |

---

### build_ori_fact_main

| 字段 | 内容 |
|------|------|
| 函数名 | build_ori_fact_main |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, chunk_uuid, chunk_summary, chunk_embedding |
| 返回类型 | str | None |
| 作用 | 构建/合并 OriginalFact，并判断是否触发 profile 更新 |
| 返回说明 | 返回 chunk_summary 或 None |

---

### build_dev_fact_main

| 字段 | 内容 |
|------|------|
| 函数名 | build_dev_fact_main |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, chunk_uuid, chunk_summary |
| 返回类型 | str | None |
| 作用 | 构建 DerivedFact（检测/匹配/合并/创建） |
| 返回说明 | 返回 stable summary 或 None |

---

### build_entity_main

| 字段 | 内容 |
|------|------|
| 函数名 | build_entity_main |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, chunk_uuid, chunk_summary |
| 返回类型 | None |
| 作用 | 从 Chunk 提取 Entity 并写入图与向量库 |
| 返回说明 | 无返回值 |

---

### profile_update_main

| 字段 | 内容 |
|------|------|
| 函数名 | profile_update_main |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, ori_summary, dev_summary |
| 返回类型 | None |
| 作用 | LLM 判断并更新用户 profile |
| 返回说明 | 无返回值 |

---

## File: `llm_extractor.py`

---

### detect_dev

| 字段 | 内容 |
|------|------|
| 函数名 | detect_dev |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_summary, max_retries=5 |
| 返回类型 | str |
| 作用 | 判断是否生成 DerivedFact |
| 返回说明 | 返回 topic 或空字符串 |

---

### merge_dev_summary

| 字段 | 内容 |
|------|------|
| 函数名 | merge_dev_summary |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | old_dev_summary, new_dev_summary, max_retries=3 |
| 返回类型 | str |
| 作用 | 合并 DerivedFact summary |
| 返回说明 | 返回合并后的文本 |

---

### extract_profile_update

| 字段 | 内容 |
|------|------|
| 函数名 | extract_profile_update |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | old_profile, summary, max_retries=3 |
| 返回类型 | ProfileUpdateDecision |
| 作用 | 判断是否更新用户 profile |
| 返回说明 | 返回结构化更新决策 |

---

### extract_entities_from_summaries

| 字段 | 内容 |
|------|------|
| 函数名 | extract_entities_from_summaries |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_summaries, max_retries=3 |
| 返回类型 | List[EntityItem] |
| 作用 | 从 summaries 批量提取实体 |
| 返回说明 | 返回 EntityItem 列表 |

---

### extract_entity_from_summary

| 字段 | 内容 |
|------|------|
| 函数名 | extract_entity_from_summary |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_summary, max_retries=3 |
| 返回类型 | List[dict] | None |
| 作用 | 单条 summary 提取实体 |
| 返回说明 | 返回实体列表或 None |

---

### extract_ori_fact_summary

| 字段 | 内容 |
|------|------|
| 函数名 | extract_ori_fact_summary |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | existing_ori_summary, new_summary, max_retries=3 |
| 返回类型 | dict |
| 作用 | 生成 OriginalFact summary + profile update 判断 |
| 返回说明 | 返回 JSON dict |

---

### _parse_profile_update_payload

| 字段 | 内容 |
|------|------|
| 函数名 | _parse_profile_update_payload |
| 访问级别 | private-like |
| 类型 | static method |
| 参数 | payload |
| 返回类型 | ProfileUpdateDecision |
| 作用 | 解析 LLM 输出为结构化 profile 更新对象 |
| 返回说明 | 返回 ProfileUpdateDecision |