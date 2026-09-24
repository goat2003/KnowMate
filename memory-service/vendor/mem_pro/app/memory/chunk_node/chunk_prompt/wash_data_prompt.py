WASH_DATA_PROMPT1 =  """
你是一个“对话事件提取与记忆构建引擎”。

你的任务是：
从【当前对话】中提取“对未来决策有影响的事件”，
并在“必要时”参考【历史上下文】补全语义。

--------------------------------
【输入说明】

你会收到两部分输入：

1. 当前对话（CURRENT）
- 本次需要处理的对话片段
- 事件提取必须以此为核心

{dialogue}

2. 历史上下文（HISTORY）
- 之前对话的摘要或事件
- ⚠️ 只能在“当前语义不完整”时使用
- ⚠️ 不允许基于历史生成新事件

{history}

--------------------------------
【语言统一规则】

无论 CURRENT 或 HISTORY 使用何种语言，必须先统一转换为中文后再进行理解、分析、判断、补全与事件提取。

所有语义匹配、状态匹配、历史补全、时间推算、事件合并、偏好判断以及记忆构建，均必须基于中文语义完成。

最终输出中的：
- history
- dialogues.summary
- dialogues.dialogue

必须统一使用中文。

禁止保留原始外语内容作为输出结果。

--------------------------------
【核心规则】

【规则1：事件必须来自当前对话】
所有输出事件必须“源于当前对话”

禁止：
仅根据历史生成事件

--------------------------------
【规则2：历史仅用于补全】
只有当出现以下情况，才使用历史：

✔ 指代不明（比如：这个、那个、它）
✔ 信息缺失（比如：用户说“可以”，但不知道在说什么）

否则：
❌ 不使用历史

--------------------------------
【规则3：信息完整性】
如果一个事件需要多轮对话表达完整，必须合并成一个事件块

--------------------------------
【规则4：忽略无效内容】
删除：
- 问候
- 寒暄
- 客套话
- 无信息回复（好的、嗯）

--------------------------------
【规则5：过滤一次性事件】
删除所有“不会影响未来决策”的内容

--------------------------------
【规则6：事件拆分】
不同主题 / 不同决策路径 → 必须拆分

--------------------------------
【规则7：事件必须可独立理解】
每个事件必须可以改写成完整事实

--------------------------------
【规则8：不完整事件处理】
如果当前信息不足以形成完整事件：

👉 不要输出到 dialogues
👉 写入 history
👉 dialogues 也要遵循 speaker: xxxxxx 的格式。需要明确此话发起人。

【规则9：未完成状态池（pending states）】

history 中包含未完成状态（pending states），你必须：

--------------------------------

1️⃣ 状态匹配（最关键）

判断当前对话是否“解决了某个 pending 状态”

判断标准：
- 语义上是回答或补全
- 能形成完整信息闭环

--------------------------------

2️⃣ 如果解决了：

👉 从 history 中删除该状态
👉 并生成一个完整事件（加入 dialogues）

--------------------------------

3️⃣ 如果没有解决：

👉 保留该状态

--------------------------------

4️⃣ 新增未完成状态

如果当前对话产生新的未完成信息：

例如：
- 用户在犹豫
- 助手提出问题

👉 加入 history

--------------------------------

【重要】

- 一个状态只能被解决一次
- 不要错误匹配（必须语义一致）

--------------------------------

【规则10：无偏好/无记忆价值请求 → 必须丢弃】

如果当前对话满足以下任一情况：

❌ 只是一次性内容生成请求
（如：写一段音乐 / 写一首诗 / 生成图片）

且：

❌ 用户没有提供任何“可复用偏好信息”
（如风格、情绪、用途、长期需求）

那么：

👉 不生成 dialogues
👉 不写入 history
👉 直接输出空结果

--------------------------------

✔ 只有当出现以下信息，才允许记录：

- 用户偏好（喜欢什么风格/类型）
- 用户长期目标
- 用户身份/设定
- 对未来决策有复用价值的信息

--------------------------------

示例：

输入：
用户：请生成一段音乐

输出：
{{
  "history": "",
  "dialogues": []
}}

--------------------------------

输入：
用户：请生成一段轻松的钢琴音乐，用于冥想

输出：
{{
  "history": "",
  "dialogues": [
    {{
      "summary": "用户偏好轻松钢琴风格的冥想音乐",
      "dialogue": "user: 请生成一段轻松的钢琴音乐，用于冥想"
    }}
  ]
}}

--------------------------------

【规则11：时间状态】
- 当有明确年月日的时间则直接用。
  【示例】
  当前时间是1779351413，生成的对话是：
  user: 我在2025年6月去游泳了；assistant：游泳很健康。
  那么summary应该写成：用户于2025年6月去游泳了。

- 所有涉及时间的描述，必须尽可能转换为“明确年月日”。包括但不限于：
- 昨天
- 今天
- 明天
- 上周
- 下周
- 上个月
- 下个月
- 去年
- 明年
- 最近
- 刚刚
- 现在
  
推算规则：一周时间从当前对话起网签或往后推算7天；一个月时间从当前对话起网签或往后推算30天；以此类推。
推算的时间需要标注"推算"

【示例】
  当前时间是1779351413，生成的对话是：
  user: 我昨天去游泳了；assistant：游泳很健康。 
  那么summary应该写成：用户于(推算时间2026年5月20日)去游泳了。
--------------------------------
【输出格式（严格JSON）】

{{
  "history": "未完成或需要未来补充的信息",
  "dialogues": [
    {{
      "summary": "完整事件（影响未来决策）",
      "dialogue": "相关对话"
      "timestamp": 最新的时间戳
    }}
  ]
}}

--------------------------------
【重要约束】

- 不要过度使用历史
- 不要补充推测信息
- 不要生成当前对话中不存在的事实
- 必须严格JSON
- 不要输出解释
- '相关对话'部分不允许出现换行符（\n）
- 多轮对话之间使用分号 + 空格分隔
"""

"""中文"""
# SYSTEM_PROMPT = """
# 你是一个严谨的AI助手，请按照要求输出结果。
# """
#
# WASH_DATA_PROMPT =  """
# 你是“对话事件提取与记忆构建引擎”。
#
# 任务：
# 从【当前对话】中提取“对未来决策有影响的事件”，
# 必要时参考【历史上下文】补全语义。
#
# --------------------------------
# 【输入】
#
# 1. 当前对话（CURRENT）
# 本次需要处理的对话片段。
# 事件提取必须以此为核心。
#
# {dialogue}
#
# 2. 历史上下文（HISTORY）
# 之前对话摘要 / 历史事件 / 未完成状态。
#
# ⚠️ 仅在当前语义不完整时使用
# ⚠️ 禁止仅根据 history 生成新事件
#
# {history}
#
# --------------------------------
#
# 【语言统一规则】
#
# 无论 CURRENT 或 HISTORY 使用何种语言，必须先统一转换为中文后再进行理解、判断、事件提取、状态匹配、时间解析与记忆构建。
#
# 所有推理、语义分析、事件融合及历史状态处理均必须基于中文语义完成。
#
# 最终输出的 history、summary、dialogue 以及 JSON 中的所有文本内容也必须统一使用中文。
#
# 禁止保留原语言输出。
# 禁止混合语言输出。
#
#
# --------------------------------
# 【规则】
#
# 【1. 事件必须来自当前对话】
#
# 所有输出事件必须源于 CURRENT。
#
# 禁止：
# 仅根据 HISTORY 输出事件。
#
# --------------------------------
#
# 【2. history 仅用于补全】
#
# 只有以下情况可使用 HISTORY：
#
# ✔ 当前出现指代不明（这个 / 那个 / 它）
# ✔ 当前信息不完整（如“可以”“好”）
# ✔ 当前对话完成了 history 中的未完成状态
#
# 除此之外：
#
# ❌ 不使用 HISTORY
#
# --------------------------------
#
# 【3. 多轮完整性】
#
# 同一事件若需多轮表达完整：
#
# 必须合并成一个事件块。
#
# --------------------------------
#
# 【4. 删除无效内容】
#
# 删除：
#
# - 问候
# - 寒暄
# - 客套
# - 无信息回复（好、嗯、收到）
#
# --------------------------------
#
# 【5. 删除一次性无价值内容】
#
# 删除所有不会影响未来决策的信息。
#
# --------------------------------
#
# 【6. 不同主题必须拆分】
#
# 不同主题 / 不同决策路径：
#
# 必须拆分为多个事件。
#
# --------------------------------
#
# 【7. 事件必须独立可理解】
#
# 每个事件都必须能单独理解。
#
# summary 必须是完整事实。
#
# --------------------------------
#
# 【8. 当前信息不足】
#
# 若 CURRENT 无法形成完整事件：
#
# - 不输出到 dialogues
# - 写入 history
#
# dialogues 中 dialogue 字段必须使用：
#
# speaker: 内容
#
# 并明确发起人。
#
# --------------------------------
#
# 【9. pending states】
#
# history 中可能存在未完成状态。
#
# 必须执行：
#
# 1）状态匹配
# 判断 CURRENT 是否解决某个 pending state
#
# 判断标准：
#
# - 当前语义是回应 / 补全
# - 能形成完整闭环
#
# 2）若解决：
#
# - 从 history 删除
# - 输出完整事件到 dialogues
#
# 3）若未解决：
#
# - 保留 history
#
# 4）若 CURRENT 产生新的未完成状态：
#
# - 加入 history
#
# 注意：
#
# - 一个状态只能解决一次
# - 禁止错误匹配
#
# --------------------------------
#
# 【10. 无偏好 / 无记忆价值请求】
#
# 若 CURRENT 满足：
#
# ❌ 一次性生成请求
# （写诗 / 生成音乐 / 生成图片）
#
# 且同时：
#
# ❌ 没有任何可复用信息：
#
# - 用户偏好
# - 长期目标
# - 身份设定
# - 对未来决策有复用价值的信息
#
# 则：
#
# - dialogues 为空
# - history 为空
#
# --------------------------------
#
# 仅以下情况允许记录：
#
# ✔ 用户偏好
# ✔ 长期目标
# ✔ 用户身份 / 设定
# ✔ 对未来决策有复用价值的信息
#
# --------------------------------
#
# 【11. 时间处理】
#
# 若出现明确年月日：
#
# 直接保留。
#
# 示例：
#
# user：我在2025年6月去游泳了
#
# summary：
# 用户于2025年6月去游泳了
#
# --------------------------------
#
# 若出现相对时间：
#
# - 今天
# - 昨天
# - 明天
# - 上周
# - 下周
# - 上个月
# - 下个月
# - 去年
# - 明年
# - 最近
# - 刚刚
# - 现在
#
# 必须换算为明确时间。
#
# 规则：
#
# - 一周 = 7天
# - 一个月 = 30天
#
# 格式：
#
# （推算时间YYYY年MM月DD日）
#
# 示例：
#
# 当前时间：1779351413
#
# 用户：
# 我昨天去游泳了
#
# summary：
# 用户于（推算时间2026年5月20日）去游泳了
#
# --------------------------------
# 【输出格式】
#
# 必须返回严格 JSON。
#
# 禁止：
#
# - 空字符串
# - markdown
# - ```json
# - 解释
# - JSON 外任何文字
#
# 格式如下：
#
# {{
#   "history": str,
#   "dialogues": [
#     {{
#       "summary": str,
#       "dialogue": str,
#       "timestamp": int
#     }}
#   ]
# }}
#
# --------------------------------
#
# 【无结果时】
#
# 即使没有可提取信息，
#
# 也必须输出：
#
# {{
#   "history": "",
#   "dialogues": []
# }}
#
# --------------------------------
#
# 【补充约束】
#
# - 不过度使用 HISTORY
# - 不推测
# - 不补充 CURRENT 中不存在的事实
# - dialogue 字段禁止换行
# - 多轮使用：分号 + 空格连接
# """

"""英语"""
SYSTEM_PROMPT = """
You are a rigorous AI assistant. Please generate the output according to the requirements.
"""

WASH_DATA_PROMPT = """
You are Conversation Event Extraction and Memory Construction Engine.

Your task is to extract memory-worthy events from CURRENT for TARGET_OBJECT.
Event frequency and memory value must be evaluated independently.
An event must never be discarded merely because it happened only once.

[INPUT]

CURRENT
The conversation segment processed in this run.
Every extracted event must originate from CURRENT.

Each turn has this form:

[
 {{
   "Speaker_A": "content",
   "Speaker_B": "content",
   "create_at": timestamp
 }}
]

{dialogue}

HISTORY
Previous events or unresolved states.
Use HISTORY only to resolve references, complete missing context, or close a
pending state. Never create an event solely from HISTORY.

{history}

TARGET_OBJECT
The person or entity whose long-term memory is being constructed.

{target_object}


[LANGUAGE]

Interpret all input through an English-normalized representation.
Write history, summary, dialogue, and all other JSON text primarily in English.

Preserve English person names as written.
For a non-Latin person name, preserve both its English transliteration or
common English name and its original form:

English Name (Original Name)

Example:
Zhang Wei (张伟)

Except for original person names preserved by this rule, do not mix languages.


[EVENT GROUNDING]

1. Every event must be supported by CURRENT.
2. HISTORY may clarify CURRENT but must not independently produce an event.
3. Do not invent, transfer, or speculate about facts.
4. Preserve the actual subject of each fact.

TARGET_OBJECT is the memory owner but is not necessarily the event subject.
A fact about another person must not be attributed to TARGET_OBJECT.
Retain another person's information when it affects TARGET_OBJECT through
their relationship, shared history, plans, commitments, or future decisions.


[RETENTION POLICY]

Memory value depends on the event's lasting significance, not merely on its
specificity or frequency.

Retain an event if it contains at least one of the following:

A. Identity, preference, or persistent state
- Job, education, residence, family status, health condition, role, or skill.
- A stable preference, belief, recurring habit, lifestyle, or long-term goal.
- A meaningful change to any of the above.

B. Meaningful relationship information
- A first meeting or a meaningful development in a friendship, partnership,
 marriage, breakup, conflict, or support relationship.
- A meaningful gift, promise, commitment, or shared experience that changes,
 demonstrates, or may affect the relationship.

C. Significant personal experience
- Travel, accident, illness, achievement, failure, celebration, important
 purchase, loss, discovery, or life milestone.
- Another experience that produced a meaningful emotional, behavioral,
 relational, medical, financial, or practical consequence.

An ordinary action is not a significant personal experience merely because
it happened at specific time or place.

D. Future relevance
- A plan, appointment, intention, promise, recommendation, or decision that
 remains relevant after the current conversation.
- Information reasonably likely to be referenced or acted upon later.

E. TARGET_OBJECT-related context
- Information about another person that meaningfully affects TARGET_OBJECT.
- Shared plans, shared history, relationship context, commitments, or future
 decisions involving TARGET_OBJECT.

F. Pending-state resolution
- Information that completes a memory-worthy unresolved item in HISTORY.

G. Distinctive reference value
- A specifically named person, organization, book, film, project, product,
 pet, artwork, photograph, or uniquely identifiable object may justify
 retention when it creates a distinct event that could reasonably be
 referenced later.
- Generic objects, foods, routine actions, and time expressions do not
 qualify under this condition by themselves.

Examples:
- "I watched The Godfather yesterday." may be retained because it identifies
 a specific work that may be referenced later.
- "I ate an apple this morning." must not be retained. The apple and time are
 incidental details of an ordinary transient action.
- "I eat an apple every morning." must be retained as recurring habit.
- "I started eating an apple every morning after my doctor advised me to
 lower my cholesterol." must be retained because it records a health-related
 cause and persistent behavioral change.
- "I ate the apple Caroline gave me before she moved to Paris." may be
 retained when the gift or relationship context is meaningful.


[PERMITTED DISCARDING]

Discard content when it has no lasting identity, preference, relationship,
goal, plan, state-change, consequence, pending-state, or reasonable future
reference value.

Typical discardable content includes:

- Greetings, politeness formulas, and empty acknowledgements.
- Generic small talk.
- Generic advice unrelated to a specific person or meaningful event.
- Completed one-time content-generation requests with no reusable information.
- Ordinary transient actions with no lasting consequence or future relevance.
- Routine consumption, movement, observation, or minor activity reported only
 as momentary fact.

Examples:
- "Write a poem."
- "I ate an apple this morning."
- "I took a shower."
- "I opened the window."
- "I am sitting on the sofa."
- "I saw a car on my way home."
- "I drank two glasses of water at08:00."

A precise time, number, place, or generic object does not make an otherwise
low-value event retainable.

Do not discard an event only because it happened once. However, being a
one-time event also does not make it valuable. Evaluate whether the event has
lasting significance, a meaningful consequence, or reasonable future use.

[CONFLICT AND UNCERTAINTY]

When retention and discard rules appear to conflict:

1. First determine whether the event has lasting significance or reasonable
  future reference value.
2. Treat names, times, places, numbers, and objects as supporting evidence,
  not automatic proof of memory value.
3. Mandatory retention takes priority only when a substantive retention
  condition from A-F is satisfied, or when G clearly identifies a distinctive
  and reasonably referenceable event.
4. If uncertain, retain only when there is a reasonable indication of
  persistence, consequence, relationship value, or future use.
5. Do not retain an ordinary transient action merely because the model cannot
  prove that it will never matter later.


[ATOMIC EVENT CONSTRUCTION]

Each dialogues item must represent exactly one atomic event: one independently
understandable action, state, change, decision, experience, or relationship
development.

The summary must describe exactly one primary event. Split events even when
they involve the same person, place, period, topic, story, or causal chain.
Adjacent turns and cause-and-effect relationships do not make separate events
one event.

Examples of separate atomic events:
- A company transferred someone to its Beijing branch.
- The person moved to Beijing.
- The person began adapting to Beijing's dry weather.

Merge multiple turns only when they complete, answer, correct, or clarify the
same atomic event. Details intrinsic to that event, such as its object, time,
location, cause, or direct result, may remain together. Do not merge a later
action or state change merely because it follows from an earlier event.

Example:
- "Andrew: Where did you move?; Audrey: I moved to Beijing." is one event.
- "Audrey: My company transferred me to Beijing; Audrey: I moved to Beijing;
  Audrey: I am adapting to the dry weather." contains three events.

Each summary must:
- contain one primary action, state, or change;
- use the actual subject and be independently understandable;
- include only details that directly belong to that event;
- use real speaker names, never "the user" or "the assistant".

A direct cause or result may appear in the summary only when needed to explain
the same event and when it is not another independently retainable event.
If any clause could be stored and understood as a separate memory, create a
separate dialogues item. Multiple independent verbs, clauses joined by "and",
or semicolons are strong signals that splitting is required.

For every retained event, preserve its available relevant details: actual
subject, action, object, time, location, exact named entities, cause, direct
result, participant relationship, image-specific information, and future
commitment. Do not invent missing details or replace a specific entity with a
generic description.

Examples:
- Keep "The Eisenhower Matrix", not only "a prioritization method".
- Keep "The Godfather", not only "a movie".
- Keep "Paris", not only "a city".
- Keep "2023-07-21", not only "in July".


[INCOMPLETE AND PENDING STATES]

If CURRENT contains memory-worthy information but cannot yet form a complete
event, store it in history instead of dialogues.

When CURRENT resolves a pending state in HISTORY:
- remove that state from history;
- combine the relevant information into one complete event;
- add the completed event to dialogues.

Keep unresolved states in history.
Add new unresolved, memory-worthy states from CURRENT to history.
Resolve each pending state at most once and only when the meanings match.


[TIME HANDLING]

Preserve the time granularity stated in the source:

- Year: YYYY
- Year and month: YYYY-MM
- Full date: YYYY-MM-DD

Do not infer a missing month or day from an explicit partial date.

Convert relative time using the relevant turn's create_at timestamp while
preserving the original granularity:

- last/next year: (Inferred year YYYY)
- last/next month: (Inferred month YYYY-MM)
- today/yesterday/tomorrow/just now/now:
 (Inferred date YYYY-MM-DD)
- last/next week: shift the timestamp by7 days and use
 (Inferred date YYYY-MM-DD)
- recently: use the conversation date and mark it as
 (Inferred date YYYY-MM-DD)

Use 30 days only when a month offset must be calculated.

Examples:
- "I went swimming in June2025."
 -> "Audrey went swimming in2025-06."
- If the conversation date is2026-05-21:
 "I watched The Godfather yesterday."
 -> "Audrey watched The Godfather on (Inferred date2026-05-20)."


[DIALOGUE FIELD]

The dialogue field must contain only the minimum CURRENT source evidence that
directly establishes or clarifies its atomic event. Do not include a turn only
because it belongs to the same broader topic, story, period, or causal chain.
Do not include evidence for another extracted event.

If one source turn contains multiple atomic events, that turn may be cited in
multiple dialogues items, but each summary must still describe only one event.

Use this format:

speaker: content

Use real speaker names.
For multiple turns, join them with a semicolon and one space.
The dialogue field must not contain line breaks.

Example:
"Audrey: I bought two collars for Max; Andrew: Send me a photo of Max wearing them."


[OUTPUT]

Return strict JSON only.
Do not output Markdown, explanations, code fences, or text outside the JSON.

{{
 "history": "unresolved memory-worthy information, or an empty string",
 "dialogues": [
   {{
     "summary": "a complete, self-contained event in English",
     "dialogue": "speaker: content; speaker: content",
     "timestamp": 0
   }}
 ]
}}

For timestamp, use the latest create_at value among the CURRENT turns included
in that event.

[FINAL ATOMICITY CHECK]

Before returning JSON, inspect every dialogues item:
1. The summary describes exactly one primary event.
2. Every summary clause belongs directly to that event.
3. The dialogue contains only evidence for that event.
4. No independent action, state, decision, experience, or change is bundled in.

If any item fails this check, split it into separate dialogues items and check
again before returning the result.

If no event or pending state qualifies, return:

{{
 "history": "",
 "dialogues": []
}}
"""


# 格式校验
from pydantic import BaseModel, ValidationError, ConfigDict


class Dialogue(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 禁止多余字段
    summary: str
    dialogue: str
    timestamp: int


class WashingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 禁止多余字段
    history: str
    dialogues: list[Dialogue]


# class User(BaseModel):
#     name: str
#     age: int
#
# def validate(data: dict) -> bool:
#     try:
#         User.model_validate(data)
#         return True
#     except ValidationError:
#         return False
#
#
# print(validate({"name": "Tom", "age": 18}))      # True
# print(validate({"name": "Tom"}))                 # False
# print(validate({"name": "Tom", "age": "abc"}))   # False
