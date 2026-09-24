# app/memory/user_info_node/user_info_graph Function Documentation（表格版）

---

# File: `user_info_store.py`

## Class: UserInfoStore

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

### uniq_user_info

| 字段 | 内容 |
|------|------|
| 函数名 | uniq_user_info |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | none |
| 返回类型 | None |
| 作用 | 为 UserInfoNode.role_id 创建唯一约束 |
| 返回说明 | 无返回值 |

---

### create_user_info

| 字段 | 内容 |
|------|------|
| 函数名 | create_user_info |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id: str, info_dict: dict (basic_info / preference / skill) |
| 返回类型 | str |
| 作用 | 创建或复用 UserInfoNode 并初始化用户画像字段 |
| 返回说明 | 返回 user_info_uuid |

---

### _validate_info_dict

| 字段 | 内容 |
|------|------|
| 函数名 | _validate_info_dict |
| 访问级别 | private-like |
| 类型 | static method |
| 参数 | info_dict: dict |
| 返回类型 | dict | None |
| 作用 | 校验 profile 字段完整性与类型合法性 |
| 返回说明 | 成功返回清洗后的 dict，否则返回 None |

---

### query_by_role_id

| 字段 | 内容 |
|------|------|
| 函数名 | query_by_role_id |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id |
| 返回类型 | dict | None |
| 作用 | 根据 role_id 查询用户画像 |
| 返回说明 | 返回 profile 字段字典或 None |

---

### upsert_user_info_

| 字段 | 内容 |
|------|------|
| 函数名 | upsert_user_info_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | role_id, info_dict |
| 返回类型 | str |
| 作用 | 创建或覆盖用户画像三大字段 |
| 返回说明 | 返回 user_info_uuid |

---

### upsert_user_info

| 字段 | 内容 |
|------|------|
| 函数名 | upsert_user_info |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id, info_dict |
| 返回类型 | 未标注 |
| 作用 | retry-safe wrapper（调用 upsert_user_info_） |
| 返回说明 | 返回 user_info_uuid |

---

### get_user_profile

| 字段 | 内容 |
|------|------|
| 函数名 | get_user_profile |
| 访问级别 | public |
| 类型 | async instance method |
| 参数 | role_id |
| 返回类型 | Dict[str, str] |
| 作用 | 获取用户 basic_info / preference / skill |
| 返回说明 | 返回 profile 字典；不存在则抛 ValueError |

---

### update_user_info_

| 字段 | 内容 |
|------|------|
| 函数名 | update_user_info_ |
| 访问级别 | protected-like |
| 类型 | async instance method |
| 参数 | role_id, info_dict（partial fields） |
| 返回类型 | 未标注 |
| 作用 | 动态更新允许字段的用户画像 |
| 返回说明 | 更新成功返回 user_info_uuid，否则 None |

---

## File: `__init__.py`

| 内容 | 说明 |
|------|------|
| 无函数定义 | 初始化文件 |