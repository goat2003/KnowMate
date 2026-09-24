# app/memory/fact_node/fact_graph Function Documentation（表格版）

---

# File: `fact_store.py`

## Class: FactStore

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化 Neo4j manager、工具服务与 embedding 客户端 |
| 返回说明 | 构造函数无业务返回值 |

---

### ensure_schema

| 字段 | 内容 |
|------|------|
| 函数名 | ensure_schema |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 创建 Neo4j fact/entity 节点的约束与索引 |
| 返回说明 | 无返回值 |

---

### create_original_fact

| 字段 | 内容 |
|------|------|
| 函数名 | create_original_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid, role_id, summary, importance, confidence=1, used_count=0, history_feedback=0.0 |
| 返回类型 | str \| None |
| 作用 | 创建 OriginalFact 节点并与 Chunk 建立 HAS_FACT 关系 |
| 返回说明 | 成功返回 ori_fact_uuid，否则返回 None |

---

### update_original_fact_

| 字段 | 内容 |
|------|------|
| 函数名 | update_original_fact_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | chunk_uuid, ori_fact_uuid, **fields |
| 返回类型 | None |
| 作用 | 更新 OriginalFact 字段并确保关系存在 |
| 返回说明 | 无返回值 |

---

### update_original_fact

| 字段 | 内容 |
|------|------|
| 函数名 | update_original_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid, ori_fact_uuid, **fields |
| 返回类型 | None |
| 作用 | safe retry wrapper |
| 返回说明 | 通常返回 None |

---

### get_ori_fact_by_uuid

| 字段 | 内容 |
|------|------|
| 函数名 | get_ori_fact_by_uuid |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | ori_fact_uuid, field_names |
| 返回类型 | dict \| None |
| 作用 | 查询 OriginalFact 指定字段 |
| 返回说明 | 成功返回 dict，否则 None |

---

### create_derived_fact

| 字段 | 内容 |
|------|------|
| 函数名 | create_derived_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid, role_id, summary, confidence=1, status=0, weight=0.0 |
| 返回类型 | str \| None |
| 作用 | 创建 DerivedFact 并与 Chunk 建立 DERIVED_FROM 关系 |
| 返回说明 | 成功返回 dev_uuid，否则 None |

---

### update_derived_fact_

| 字段 | 内容 |
|------|------|
| 函数名 | update_derived_fact_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | chunk_uuid, dev_uuid, **fields |
| 返回类型 | None |
| 作用 | 更新 DerivedFact 字段并保证关系存在 |
| 返回说明 | 无返回值 |

---

### update_derived_fact

| 字段 | 内容 |
|------|------|
| 函数名 | update_derived_fact |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | chunk_uuid, dev_uuid, **fields |
| 返回类型 | None |
| 作用 | safe retry wrapper |
| 返回说明 | 通常返回 None |

---

### get_dev_fact_by_uuid

| 字段 | 内容 |
|------|------|
| 函数名 | get_dev_fact_by_uuid |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | dev_uuid, field_names |
| 返回类型 | dict \| None |
| 作用 | 查询 DerivedFact 指定字段 |
| 返回说明 | 成功返回 dict，否则 None |

---

### touch_derived_fact_used

| 字段 | 内容 |
|------|------|
| 函数名 | touch_derived_fact_used |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, dev_uuid, used_time |
| 返回类型 | None |
| 作用 | 更新 DerivedFact 使用时间 |
| 返回说明 | 无返回值 |

---

### delete_expired_derived_facts_by_status

| 字段 | 内容 |
|------|------|
| 函数名 | delete_expired_derived_facts_by_status |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | now_time, status=0, limit=200 |
| 返回类型 | list[str] \| None |
| 作用 | 删除过期 DerivedFact |
| 返回说明 | 返回删除的 dev_uuid 列表或 None |

---

### create_entity_

| 字段 | 内容 |
|------|------|
| 函数名 | create_entity_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | role_id, chunk_uuid, name, entity_type, semantic |
| 返回类型 | str |
| 作用 | 创建或复用 Entity 并关联 Chunk |
| 返回说明 | 返回 entity_uuid |

---

### get_entity_by_uuid

| 字段 | 内容 |
|------|------|
| 函数名 | get_entity_by_uuid |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | entity_uuid, field_names |
| 返回类型 | dict \| None |
| 作用 | 查询 Entity 指定字段 |
| 返回说明 | 成功返回 dict，否则 None |

---

### get_full_entity_by_uuid

| 字段 | 内容 |
|------|------|
| 函数名 | get_full_entity_by_uuid |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | entity_uuid |
| 返回类型 | unknown |
| 作用 | 查询完整 Entity |
| 返回说明 | 返回 entity 或 None |

---

### link_entity_to_chunk_

| 字段 | 内容 |
|------|------|
| 函数名 | link_entity_to_chunk_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | role_id, chunk_uuid, entity_uuid |
| 返回类型 | bool |
| 作用 | 建立 Entity 与 Chunk 关系 |
| 返回说明 | 成功 True，否则 False |

---

# Class: GraphORM

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | manager |
| 返回类型 | None |
| 作用 | 初始化图遍历工具 |
| 返回说明 | 无返回值 |

---

### _field

| 字段 | 内容 |
|------|------|
| 函数名 | _field |
| 访问级别 | private-like |
| 类型 | instance method |
| 参数 | node_type |
| 返回类型 | str |
| 作用 | 获取节点 UUID 字段 |
| 返回说明 | 返回字段名 |

---

### _rel

| 字段 | 内容 |
|------|------|
| 函数名 | _rel |
| 访问级别 | private-like |
| 类型 | instance method |
| 参数 | source, target |
| 返回类型 | str |
| 作用 | 获取默认关系类型 |
| 返回说明 | 返回关系名 |

---

### _safe

| 字段 | 内容 |
|------|------|
| 函数名 | _safe |
| 访问级别 | private-like |
| 类型 | instance method |
| 参数 | value |
| 返回类型 | str |
| 作用 | 校验 Cypher 注入安全性 |
| 返回说明 | 安全返回值或抛异常 |

---

### find

| 字段 | 内容 |
|------|------|
| 函数名 | find |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | node_type, node_uuid |
| 返回类型 | GraphORM |
| 作用 | 设置起始节点 |
| 返回说明 | 支持链式调用 |

---

### out

| 字段 | 内容 |
|------|------|
| 函数名 | out |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | target_type |
| 返回类型 | GraphORM |
| 作用 | 设置出边方向 |
| 返回说明 | 支持链式调用 |

---

### in_

| 字段 | 内容 |
|------|------|
| 函数名 | in_ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | target_type |
| 返回类型 | GraphORM |
| 作用 | 设置入边方向 |
| 返回说明 | 支持链式调用 |

---

### rel

| 字段 | 内容 |
|------|------|
| 函数名 | rel |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | rel_type |
| 返回类型 | GraphORM |
| 作用 | 设置关系类型 |
| 返回说明 | 支持链式调用 |

---

### run

| 字段 | 内容 |
|------|------|
| 函数名 | run |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | none |
| 返回类型 | list[str] |
| 作用 | 执行图遍历查询 |
| 返回说明 | 返回 UUID 列表 |

---

# File: fact_store_main.py

## Class: FactStoreMain

---

### __init__

| 字段 | 内容 |
|------|------|
| 函数名 | __init__ |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 初始化主入口类 |
| 返回说明 | 无业务返回 |

---

# File: __init__.py

| 内容 | 说明 |
|------|------|
| 无函数定义 | 初始化文件 |