# ToolService 函数文档（表格版）

---

### get_hash_val

| 字段 | 内容 |
|------|------|
| 函数名 | get_hash_val |
| 访问级别 | public |
| 类型 | static method |
| 参数 | data: List[dict] |
| 返回类型 | str |
| 作用 | 对输入列表进行稳定 JSON 序列化，并生成 SHA-256 哈希用于去重 |
| 返回说明 | 返回十六进制 SHA-256 字符串 |

---

### get_hash

| 字段 | 内容 |
|------|------|
| 函数名 | get_hash |
| 访问级别 | public |
| 类型 | static method |
| 参数 | data: dict |
| 返回类型 | str |
| 作用 | 对字典进行稳定 JSON 序列化，并生成 MD5 哈希 |
| 返回说明 | 返回十六进制 MD5 字符串 |

---

### build_hash

| 字段 | 内容 |
|------|------|
| 函数名 | build_hash |
| 访问级别 | public |
| 类型 | static method |
| 参数 | role_id: str, session_id: str, contents: dict, created_at: int |
| 返回类型 | str |
| 作用 | 构建标准化对话对象并生成 MD5 哈希 |
| 返回说明 | 返回十六进制 MD5 字符串 |

---

### transfer_timeform

| 字段 | 内容 |
|------|------|
| 函数名 | transfer_timeform |
| 访问级别 | public |
| 类型 | static method（含 self） |
| 参数 | self, timestamp |
| 返回类型 | datetime |
| 作用 | Unix 时间戳转 datetime |
| 返回说明 | datetime.fromtimestamp(timestamp) |

---

### get_current_system_time

| 字段 | 内容 |
|------|------|
| 函数名 | get_current_system_time |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | 无 |
| 返回类型 | datetime |
| 作用 | 获取当前系统时间 |
| 返回说明 | 返回当前 datetime |

---

### get_x_days_before

| 字段 | 内容 |
|------|------|
| 函数名 | get_x_days_before |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | x: int |
| 返回类型 | datetime |
| 作用 | 获取当前时间往前推 x 天的时间点 |
| 返回说明 | 返回 datetime |

---

### get_indep_data

| 字段 | 内容 |
|------|------|
| 函数名 | get_indep_data |
| 访问级别 | public |
| 类型 | instance method |
| 参数 | data: dict |
| 返回类型 | dict |
| 作用 | 标准化对话数据并生成 hash |
| 返回说明 | 返回包含 role_id/session_id/speakers/contents/content/valid_at/hash_val |

---

### read_and_group_by_conversation

| 字段 | 内容 |
|------|------|
| 函数名 | read_and_group_by_conversation |
| 访问级别 | public |
| 类型 | static method（含 self） |
| 参数 | self, file_path: str |
| 返回类型 | dict |
| 作用 | 读取 JSON 并按 (session_id, role_id) 分组 |
| 返回说明 | 返回分组后的 dict |

---

### get_year_month_day

| 字段 | 内容 |
|------|------|
| 函数名 | get_year_month_day |
| 访问级别 | public |
| 类型 | static method |
| 参数 | 无 |
| 返回类型 | dict |
| 作用 | 获取 MongoDB 时间范围（昨天 00:00 ~ 今天 00:00） |
| 返回说明 | start_time / end_time |

---

### get_year_month_day_pre

| 字段 | 内容 |
|------|------|
| 函数名 | get_year_month_day_pre |
| 访问级别 | public |
| 类型 | static method |
| 参数 | 无 |
| 返回类型 | dict |
| 作用 | 获取 MongoDB 时间范围（今天 00:00 ~ 明天 00:00） |
| 返回说明 | start_time / end_time |

---

### safe_retry

| 字段 | 内容 |
|------|------|
| 函数名 | safe_retry |
| 访问级别 | public |
| 类型 | instance async method |
| 参数 | func, *args, max_retry=5, **kwargs |
| 返回类型 | Any |
| 作用 | 异步重试机制（指数退避 + jitter），用于 Neo4j 等操作 |
| 返回说明 | 成功返回 func 结果，否则抛出 Exception("retry failed") |

---

### detect_language

| 字段 | 内容 |
|------|------|
| 函数名 | detect_language |
| 访问级别 | public |
| 类型 | static method |
| 参数 | text: str |
| 返回类型 | str |
| 作用 | 使用 langdetect 检测语言 |
| 返回说明 | 返回语言代码（en / zh-cn 等） |

---

### merge_dialogue

| 字段 | 内容 |
|------|------|
| 函数名 | merge_dialogue |
| 访问级别 | public |
| 类型 | static method |
| 参数 | dialogues: List[dict] |
| 返回类型 | str |
| 作用 | 合并 user / assistant 多轮对话文本 |
| 返回说明 | 返回拼接后的字符串 |

---
```