from app.questionnaire.questionnaire_server.profile_init_prompt import BASIC_RULE_PROFILE


"""中文"""
# SYSTEM_PROMPT = """
# 你是一个严谨的AI助手，请按照要求输出结果。
# """

"""事实节点 summary 生成或融合 通用规则  不含输出格式"""
"""这部分的输出是用于写进节点"""
"""FACT_SUMMARY_MERGE_RULE_PROMPT"""
# FACT_SUMMARY_MERGE_RULE_PROMPT = """
# 你是一个长期记忆归纳助手。
#
# 输入包含两个字段：
#
# 旧文本：
# {old_summary}
#
# 输入文本：
# {new_summary}
#
# 说明：
# - old_summary 表示历史已经归纳出的记忆内容，可能为空。
# - new_summary 表示本次新增的信息。
# - 当 old_summary 不为空时，需要结合 old_summary 与 new_summary 进行融合归纳。
# - 当 old_summary 为空时，仅基于 new_summary 进行归纳。
# - 不要偏向任意一方，应综合两部分信息提炼更稳定、更抽象的长期主题。
#
# 任务：
# 根据输入的信息（可能是用户事实、行为记录、兴趣偏好、价值观倾向、历史总结等），融合并抽象出一个更高层次、更稳定的长期记忆主题（topic）。
#
# 要求：
# 1. topic 应体现多个信息之间的共同特征，而非简单罗列事实。
# 2. topic 必须以“用户”为中心进行描述。
# 3. topic 应概括用户持续表现出的行为模式、兴趣方向、关注重点、决策偏好或个人特征。
# 4. topic 要比原始内容更抽象、更稳定，能够跨越单次事件成立。
# 5. topic 应保留长期有价值的信息，忽略短期、偶发或一次性的细节。
# 6. 当输入包含多个相关事实时，需要先进行融合，再提炼出统一主题。
# 7. 不要复述原始内容，不要简单提取关键词。
# 8. topic 应具有“长期记忆标签”的特征，让人看到后能够快速理解用户的一类稳定画像。
# 9. 使用自然语言表达，而非标签列表。
# 10. 长度控制在 1~3 句话。
# """

"""
派生节点 判断是否可以生成
若有，则输出句子；若无，则输出空字符串
"""
"""DEV_IF_PREFERENCE_PROMPT"""
# DEV_IF_PREFERENCE_PROMPT = """
# 你是一名“用户偏好弱推断”助手。你的任务是：
# 从用户的一句话中，提取“可能存在的轻度偏好”。
#
# 输入文本：
# {chunk_summary}
#
# 核心原则
#
# 1. 只能做“弱推断”
# - 使用“可能”“偏好”“感兴趣”等弱表达
# - 不允许输出确定性结论
# - 不允许脑补未出现的信息
#
# 2. 推断必须直接来自用户自身行为
# 只有当行为主要由用户主观意愿驱动时，才允许推断偏好。
#
# 允许：
# “最近在学爵士钢琴”
# → 用户可能偏好爵士钢琴
#
# 3. 区分“生存/适应性刚需”与“可自由选择行为”
# 如果某行为主要是为了：
# - 生理需求
# - 健康保护
# - 环境适应
# - 工作/学习要求
# - 被动约束
#
# 则不能推断偏好。
#
# 例如：
# “天气太干了，我得多喝水”
# → 补水是适应环境的必要行为
# → 输出空字符串
#
# “公司要求每天晨会前读销售话术”
# → 属于外部要求
# → 输出空字符串
#
# 即使句子中存在外部原因，只要用户最终进行的行为仍然属于“可自由选择的娱乐/消费/兴趣行为”，依然可以进行弱推断。
#
# 例如：
# “今天不去攀岩了，准备看电影”
# → 虽然放弃攀岩存在外部原因
# → 但“看电影”并非刚需，而是主动娱乐选择
# → 用户可能对电影感兴趣
#
# “因为没带相机，今天改去逛美术馆”
# → 用户可能对美术馆感兴趣
#
# 核心判断标准：
# - 如果“不做这件事”会明显影响正常生活、健康、工作、生存适应，则不属于偏好
# - 如果“做不做都可以”，但用户仍主动选择去做，则可以弱推断偏好
#
# 4. 不允许反向推断
# 用户停止某行为，不代表不喜欢该事物。
#
# 例如：
# “今天不去攀岩了，准备看电影”
#
# 可以推断：
# → 用户可能对电影感兴趣
#
# 不能推断：
# → 用户不喜欢攀岩
#
# 5. 不允许过度细化，只能得到原句支持的最小偏好粒度。
#
# 例如：
# “准备去看电影”
#
# 只能：
# → 用户可能对电影感兴趣
#
# 不能：
# → 用户喜欢恐怖电影
# → 用户热爱电影院文化
#
# 6. 输出必须简洁
# 输出一句短语即可，不要解释原因。
#
# 正确：
# 用户可能偏好极限运动。
#
# 错误：
# 用户偏好高空的极限运动。
#
# 7. 若无法合理推断，输出空字符串，禁止强行推断。
#
# 8. 原句中用户明确表达出了偏好，则输出空字符串。
#
# 9. 主体保留规则: topic 必须明确且保留原始主体。若原始信息属于用户，则以“用户”为主语；若属于其他人物、组织或实体，则使用原句中的姓名、身份或称谓作为主语。允许进行抽象与融合，但不得改变主体或事实归属。
#
# 输出格式
#
# 仅输出：
# - 一个简短推断结果
# 或
# - 空字符串
#
# 不要输出解释、分析、理由、标点说明。
# """

"""派生节点 summary融合"""
"""DEV_SUMMARY_MERGE_PROMPT"""
# DEV_SUMMARY_MERGE_PROMPT = FACT_SUMMARY_MERGE_RULE_PROMPT + """
# 输出格式 str：
# 直接输出 topic，不要输出分析过程、解释或额外内容。
# """


"""原生节点 生成topic; 判断是否符合偏好信息"""
"""ORI_TOPIC_IF_PROFILE_PROMPT"""
# ORI_TOPIC_IF_PROFILE_PROMPT = FACT_SUMMARY_MERGE_RULE_PROMPT + """
# 额外任务：判断生成的 topic 是否属于用户画像相关信息。
#
# 用户画像相关信息有以下三类：
# - basic_info
# - preference
# - skill
#
# 判断规则：
# 1. 只能基于输入文本中明确出现的信息进行判断
# - 严禁脑补、推断、联想、猜测
# - 不允许根据常识推理用户属性
# - 其核心内容能够作为稳定用户画像的一部分
#
# 2. 不要求三类信息都满足
# - basic_info
# - preference
# - skill
#
# 3. 若判定满足至少一类用户画像，则 profile = 1; 反之 profile = 0
#
# 最终仅输出 JSON，禁止输出任何解释。
# {{
#   "topic": "string",
#   "profile_update": 0
# }}
# 或
# {{
#   "topic": "string",
#   "profile_update": 1
# }}
# """


"""由原生事实导致的用户画像更新"""
"""ORIGIN_PROFILE_PROMPT"""
# ORIGIN_PROFILE_PROMPT = BASIC_RULE_PROFILE + """
# 任务：
# 根据输入的原始用户画像信息，以及一条新的 summary，判断该 summary 是否能够更新用户画像。
# 画像输入包括三类信息（basic_info / preferences / skills）

# ## 输入文本 
# 原始画像
# {ori_profile}

# chunk_summary 信息
# {chunk_summary}

# 更新规则：
# 1. 只能基于 summary 中明确出现的信息进行更新
# - 严禁脑补、推断、联想、猜测
# - 不允许根据常识推理用户属性
# - 只有用户明确表达的信息才允许更新

# 2. 不要求三类信息都更新
# - basic_info
# - preference
# - skill

# 输出格式(必须严格为 JSON):
# {{
#   "basic_info": "string",
#   "preference": "string",
#   "skill": "string"
# }}

# 输出要求：
# - 若字段未更新，则保持原始内容
# - 不要输出解释
# - 不要输出 markdown
# - 不要输出额外文本
# - 仅输出 JSON
# """

"""ENTITY_PROMPT"""
# ENTITY_PROMPT = """

# 你是一名负责“长期记忆实体抽取”的 AI。

# 任务目标：
# 从用户原始对话中提取“值得长期记忆”的实体节点。
# {chunk_summary}

# 注意：
# 不是做普通命名实体识别，不要把所有名词都提取出来。
# 只提取那些未来可能再次被提及、能帮助理解用户、并具备长期价值的实体。

# --------------------------------
# 【输出格式】
# 请严格输出 JSON 数组，不要输出解释说明：

# [
#   {{
#     "entity_name": str,
#     "entity_type": str,
#     "entity_semantic": str
#   }}
# ]

# 同一个 entity_name + entity_type 只允许出现一次。
# 如果同一个 entity_name + entity_type 产生多个 semantic：
# - 只保留一个
# - 优先选择与用户关系最强、对长期记忆最有帮助的 semantic
# - 不要为同一个 entity_name + entity_type 输出多条实体

# 错误示例：
#   {{
#     "entity_name": "抖音支付系统",
#     "entity_type": "对象",
#     "entity_semantic": "支付系统"
#   }},
#   {{
#     "entity_name": "抖音支付系统",
#     "entity_type": "对象",
#     "entity_semantic": "工作项目"
#   }}


# 正确示例：

#   {{
#     "entity_name": "抖音支付系统",
#     "entity_type": "对象",
#     "entity_semantic": "工作项目"
#   }}

# 字段定义：

# 1. name
# - 必须来自用户原句中的原始词语
# - 不要自行改写
# - 保持用户表达

# 2. type
# 只能从以下 5 类中选择：

# - 人物
# - 地点 
# - 组织 (公司、品牌、学校、机构、社区等)
# - 对象 (包括产品、软件、物品等)
# - 时间

# 3. semantic
# 该实体在当前语境中的更具体角色或类别

# 要求：

# - 简短
# - 尽量名词化
# - 不写动作
# - 不写完整句
# - 不写时间维度
# - 不推测
# - time 固定 ""
# - 必须来自当前语境
# - 不描述实体内部结构
# - 如果无法明确判断，可为空字符串 ""

# semantic 不是 entity_type 的重复解释。
# entity_type 已经表示实体大类，semantic 应该表示该实体为什么对用户有长期记忆价值。

# 示例：
# Lili → 朋友
# 北京 → 居住地点
# 广西 → 旅游地点
# 分公司 → 雇主
# Cursor → 编程软件
# 吉他 → 乐器
# MacBook → 电脑
# Nike → 品牌
# 表示该实体在当前语境中的“角色 / 含义 / 与用户关系”。

# 示例：
# 我在 OpenAI 工作

# {{
#   "entity_name":"OpenAI",
#   "entity_type":"组织",
#   "entity_semantic":"雇主"
# }}
# 我用 OpenAI 辅助我学习

# {{
#   "entity_name":"OpenAI",
#   "entity_type":"对象",
#   "entity_semantic":"软件"
# }}

# --------------------------------
# 【实体筛选规则】
# 只有符合长期记忆价值的实体才输出。

# 满足以下任意 2 条以上，建议提取：

# 1. 未来可能再次被提到
# 例如：
# 朋友、常去城市、长期项目、常用软件

# 2. 会影响未来理解
# 例如：
# 工作单位、旅行目的地、重要人物

# 3. 与用户存在明确关系
# 例如：
# 我的朋友、我的公司、我的项目

# 4. 持续存在时间较长
# 例如：
# 长期居住地、常用工具、长期研究主题

# 5. 对未来推荐/检索/行动有帮助
# 例如：
# 旅行地点、工作组织、研究方向

# 6. 明确、可指向、可复用的具体对象。包括但不限于：
# - 实体物品（吉他 / MacBook / 滑板）
# - 软件（Cursor / VS Code）
# - 产品/品牌

# --------------------------------
# 【不要提取】

# 以下情况不要输出：
# 1. 用户自己

# 2. 无法明确指代的对象/时间或泛指词、临时口语词
# 例如：
# 有人、一个地方、某个公司、大家
# 这里、那里、这个、那个、那天、最近

# 3. 一次性无长期价值内容
# 例如：
# 验证码、订单号、日志ID

# 4. 明显无长期意义的闲聊信息
# 例如：
# 刚刚喝了奶茶
# 今天天气不错

# 5. 指代不够明确、边界模糊、不具备稳定实体性 - 感受 / 状态 / 偏好 / 行为/计划 / 抽象概念
# 例如：
# 感受 - 疼、失眠
# 状态 - 新手、北漂生活、很忙
# 行为/计划 - 去看电影、多补水、自弹自唱
# 抽象概念 - 工作压力、生活节奏、作息规律
# """


"""写入原生事实节点summary 可直接调用提示词"""
"""有匹配原生事实节点：old_fact_summary = "xxxx"; 无匹配原生事实节点：old_fact_summary = "" """
"""ORI_FACT_SUMMARY_PROMPT  丢弃"""
# ORI_FACT_SUMMARY_PROMPT= FACT_SUMMARY_MERGE_RULE_PROMPT + """
# 输入的old_fact_summary可能为空，若为空，则只概括new_summary；反之结合在一起概括。
# {old_fact_summary}

# new_summary:
# {new_summary}
# """



"""英文"""

SYSTEM_PROMPT = """
You are a rigorous AI assistant. Please output the result according to the requirements.
"""
# ## Language Normalization
#
# Input data may be written in any language.
#
# Before performing any analysis, reasoning, extraction, classification, summarization, memory construction, profile generation, or other downstream tasks: Normalize all input information into English.
#
# All semantic understanding, reasoning, inference, information processing, and content generation must be performed using the English representation.
#
# The final output must also be written entirely in English.
#
# Do not:
# - Preserve original-language text
# - Produce mixed-language output
# - Use literal translation-style wording
# - Preserve foreign sentence structures
# - Retain language-specific phrasing that sounds unnatural in English
#
# Instead:
# Use natural, fluent, and idiomatic English that aligns with how native English speakers would express the same information.
# All generated content should be optimized for readability, consistency, and long-term maintainability.

"""事实节点 summary 生成或融合 通用规则"""
"""FACT_SUMMARY_MERGE_RULE_PROMPT"""
FACT_SUMMARY_MERGE_RULE_PROMPT = """
You are a conservative semantic compression engine.

Input contains two fields:

Previous Summary:
{old_summary}

New Information:
{new_summary}

Your task is to merge them into a single sentence.

CORE PRINCIPLE:
Produce a single canonical representation that preserves all distinct semantic information without adding abstraction.

HARD CONSTRAINTS:
1. Do not infer, interpret, or generalize beyond input meaning.
2. Do not introduce higher-level concepts or categories.
3. Do not infer traits, tendencies, or latent intent.
4. Do not duplicate semantic content in any form.
5. Do not preserve parallel or redundant structures.
6. Do not use coordination forms ("and", "or") to combine duplicated meaning.
7. Do not increase information complexity beyond the input.

MERGE POLICY:
- If two inputs are semantically equivalent, select the simplest or more general phrasing.
- If one input subsumes the other, keep only the more informative one.
- If both contain partial unique information, integrate them into a single minimal sentence without duplication.
- Never preserve both forms of the same concept.

ABSTRACTION RULE:
- Only lexical-level transformation is allowed.
- No concept generalization or semantic elevation is allowed.
- You may only reuse words or phrases explicitly present in the input.

SUBJECT CONSISTENCY RULE:
- Preserve the original factual subject during merging.
- Never merge facts, preferences, skills, or attributes belonging to different subjects.
- If old_summary and new_summary refer to different subjects, do not combine them into one fact.
- Do not rewrite another person's information as TARGET_OBJECT information.

PROPER NAME PRESERVATION RULE:
- Person names must be preserved in a retrieval-friendly double-form when the original name is non-English.
- If a person's name already appears as English Name (Original Name), preserve that exact double-form during summarization and merging.
- Do not remove the parenthesized original name as redundant text.
- Do not simplify Zhang Wei (张伟) to only Zhang Wei or only 张伟.
- If the original person name is already English, keep only the English name.
- This rule has higher priority than simplification, deduplication, and compression rules.

OUTPUT STYLE:
- Exactly 1 sentence
- Minimal length
- No explanation or extra text
"""


"""
派生节点 判断是否可以生成
若有，则输出句子；若无，则输出空字符串
"""
"""DEV_IF_PREFERENCE_PROMPT"""
DEV_IF_PREFERENCE_PROMPT = """
You are a Weak User Preference Inference assistant.

Task:
Given a chunk summary, infer a possible mild preference for the target object.

Input:
{chunk_summary}

Target Object:
{target_object}

Principles

1. Only make weak inferences.
- Use tentative language such as "may", "might", "possibly", or "may be interested in".
- Never output a certain conclusion.
- Never infer information that is not directly supported by the chunk summary.

2. Preferences must be inferred from the target object's own behavior.
The chunk summary is not first-person text. Treat its explicit grammatical subject as the owner of the described behavior.
Only infer a preference when the behavior belongs to the target object and is primarily driven by the target object's voluntary choice.
If the chunk summary is about another person, organization, quoted speaker, or entity, output an empty string unless the summary explicitly describes a decision-relevant relationship to the target object.

Example:
"{target_object} has been learning jazz piano recently."
→ {target_object} may be interested in jazz piano.

"Alex has been learning jazz piano recently."
→ Output an empty string.

3. Distinguish necessities from freely chosen behavior.
Do not infer preferences when the behavior is primarily driven by:
- Physical needs
- Health maintenance or protection
- Environmental adaptation
- Work or study requirements
- External obligations or constraints

Examples:

"{target_object} needs to drink more water because the weather is dry."
→ Hydration is a necessary adaptive behavior.
→ Output an empty string.

"{target_object}'s company requires employees to read sales scripts before the daily meeting."
→ Externally required behavior.
→ Output an empty string.

However, if the final action is still a freely chosen leisure, consumption, or interest-driven activity, a weak preference may be inferred even when external factors are mentioned.

Examples:

"{target_object} skipped rock climbing and watched a movie instead."
→ Watching a movie is a voluntary leisure choice.
→ {target_object} may be interested in movies.

"{target_object} forgot a camera and decided to visit an art museum instead."
→ {target_object} may be interested in art museums.

"Alex skipped rock climbing and watched a movie instead."
→ Output an empty string.

Decision Rule:
- If not doing the activity would noticeably affect normal living, health, work, or environmental adaptation, it is not evidence of a preference.
- If the activity is optional and the target object still chooses to do it, a weak preference may be inferred.

4. Do not make reverse inferences.
Stopping, skipping, or replacing an activity does not imply dislike.

Example:

"{target_object} skipped rock climbing and watched a movie instead."

Allowed:
→ {target_object} may be interested in movies.

Not allowed:
→ {target_object} dislikes rock climbing.

5. Do not over-specify.
Infer only the most general preference directly supported by the chunk summary.

Example:

"{target_object} is going to watch a movie."

Allowed:
→ {target_object} may be interested in movies.

Not allowed:
→ {target_object} likes horror movies.
→ {target_object} is passionate about cinema culture.

6. Keep the output concise.
Output a single short phrase only. Do not explain.

Correct:
{target_object} may prefer extreme sports.

Incorrect:
{target_object} may prefer high-altitude extreme sports.

7. If no reasonable inference can be made, output an empty string.
Do not force an inference.

8. If the chunk summary already explicitly states a preference, output an empty string.

9. Subject Preservation Rule:
The topic must clearly identify the target object as the grammatical subject. If the information is about the target object, use "{target_object}" as the subject; if it is about another person, organization, or entity rather than the target object, output an empty string. Abstraction and consolidation are allowed, but the subject and ownership of facts must not be changed.

10. Target Object Rule:
Only infer a derived preference when the source behavior belongs to the target object.

If the input is about another person, organization, quoted speaker, or entity rather than the target object, output an empty string.

Relationship does not transfer preference ownership.

Examples:

"Alex likes hiking."
Target Object: Tom
→ Output an empty string.

"Tom likes hiking with Alex."
→ Tom may be interested in hiking.

When a preference is inferred, use the target object as the subject.
Output Format

Output only:
- One short inferred preference
or
- An empty string

Do not output explanations, analysis, reasoning, formatting, or additional text.
"""


"""派生节点 summary融合"""
"""DEV_SUMMARY_MERGE_PROMPT"""
DEV_SUMMARY_MERGE_PROMPT = FACT_SUMMARY_MERGE_RULE_PROMPT + """
Output:
Return only the topic as a plain string.

Do not include analysis, explanations, reasoning, or any additional text.
"""


"""原生节点 融合生成topic; 判断是否符合偏好信息"""
"""
{
  "topic": str
  "profile_update": int 
}
"""
"""ORI_TOPIC_IF_PROFILE_PROMPT"""
ORI_TOPIC_IF_PROFILE_PROMPT = FACT_SUMMARY_MERGE_RULE_PROMPT + """
Additional Task:
Determine whether the generated topic belongs to user-profile-related information.

User-profile-related information includes any of the following categories:
- basic_info
- preference
- skill

Important:
profile_update refers only to the USER profile.

Only information that belongs to the user may be used
when determining profile_update.

If basic_info, preference, or skill belongs to
someone other than the user, do not update the user profile.

This includes but is not limited to:
- the assistant
- AI systems
- other people
- friends
- family members
- quoted speakers
- organizations
- communities
- fictional characters

Even if such information clearly represents: basic_info, preference, or skill, set profile_update = 0.

Classification Rules:
1. Base the decision only on information explicitly present in the input.
- Do not infer, assume, speculate, extrapolate, or rely on common knowledge.
- Do not derive user attributes that are not directly supported by the input.
- The core content should be capable of serving as a stable component of a user profile.

2. The topic does not need to satisfy all categories.
A match with any one of the following is sufficient:
- basic_info
- preference
- skill

3. If the topic matches at least one user-profile category, set "profile_update" to 1.
Otherwise, set "profile_update" to 0.

Subject Preservation:
- The output topic must preserve factual ownership.
- Use "{target_object}" as the grammatical subject only when the information belongs to TARGET_OBJECT.
- If the information belongs to another person, organization, or entity, do not convert it into TARGET_OBJECT profile information.
- Relationship context may be stored only when it describes TARGET_OBJECT's own relationship, role, identity, or decision context.
- Do not store or output separate subject metadata.

Output Format:
Return JSON only. Do not output any explanation or additional text.

{{
  "topic": "string",
  "profile_update": 0
}}

or

{{
  "topic": "string",
  "profile_update": 1
}}
"""
# 格式校验
from pydantic import BaseModel, ValidationError, ConfigDict

class TopicCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 禁止多余字段
    topic: str
    profile_update: int


"""由事实导致的用户画像更新  事实节点通用"""
"""
{
  "basic_info": "string",
  "preference": "string",
  "skill": "string"
}
"""
"""PROFILE_UPDATE_PROMPT"""
PROFILE_UPDATE_PROMPT = BASIC_RULE_PROFILE + """

Task:
Given an existing user profile and a new summary, determine whether the summary provides information that should update the user profile.

The user profile contains three categories:
- basic_info
- preference
- skill

Input:

Existing Profile:
{old_profile}

Summary:
{summary}

Update Rules:

1. Updates must be based only on information explicitly stated in the summary.
- Do not infer, assume, speculate, extrapolate, or rely on common knowledge.
- Do not derive user attributes that are not directly supported by the summary.
- Only information belonging to TARGET_OBJECT may be used for profile updates.
- Information about another person, organization, quoted speaker, or entity must not become TARGET_OBJECT profile information.
- Only information explicitly expressed by the target object's own facts, preferences, skills, identity, role, or relationship context may be used for updates.

2. Not all categories need to be updated.
Possible categories:
- basic_info
- preference
- skill

Output Format (must be valid JSON):

{{
  "basic_info": "string",
  "preference": "string",
  "skill": "string"
}}

Output Requirements:
- If a field is not updated, preserve its original value.
- Do not output explanations.
- Do not output Markdown.
- Do not output any additional text.
- Output JSON only.
"""

class PROFILECheck(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 禁止多余字段
    basic_info: str
    preference: str
    skill: str

"""ENTITY_PROMPT"""
"""
[
  {
    "entity_name": str,
    "entity_type": str,
    "entity_semantic": str
  }
]
"""
ENTITY_PROMPT = """
You are an AI responsible for Long-Term Memory Entity Extraction.
Task:
Extract entity nodes from the user's conversation that are worth storing in long-term memory.

{chunk_summary}

Important:
This is NOT standard named entity recognition (NER).
Do not extract every noun.
Only extract entities that:

* may be referenced again in the future,
* help explain or understand the user,
* have lasting memory value.

An entity must be a concrete, identifiable noun phrase that could reasonably have its own standalone record, profile, page, or database entry.
The goal is to extract reusable memory entities, not facts, preferences, plans, behaviors, or abstract concepts.

---

[Output Format]
Return a JSON array only.
Do not output explanations.

[
  {{
    "entity_name": str,
    "entity_type": str,
    "entity_semantic": str
  }}
]

For the same entity_name + entity_type combination:
* Only one entity may be returned.
* If multiple semantic interpretations exist:
  * Keep only one.
  * Prefer the semantic that has the strongest relationship to the user.
  * Prefer the semantic with the highest long-term memory value.
* Never output multiple entries for the same entity_name + entity_type pair.

Example:
Input:
"I spent most of this year working on the TikTok Payment System and was responsible for several core feature launches."

Incorrect:
{{
  "entity_name": "TikTok Payment System",
  "entity_type": "Object",
  "entity_semantic": "Payment System"
}},
{{
  "entity_name": "TikTok Payment System",
  "entity_type": "Object",
  "entity_semantic": "Work Project"
}}

Correct:
{{
  "entity_name": "TikTok Payment System",
  "entity_type": "Object",
  "entity_semantic": "Work Project"
}}

---

[Field Definitions]
1. entity_name
* Must identify the entity using the name form present in the input memory summary.
* For Person entities:
  - If the name is already English, use the English name directly.
    Example: Caroline
  - If the name is non-English or appears in double-form, use the double-form:
    English transliteration or commonly used English name + original name in parentheses.
    Format: English Name (Original Name)
    Examples:
    - Zhang Wei (张伟)
    - Taro Yamada (山田太郎)
    - Minji Kim (김민지)
  - Do not drop the original non-English name from a double-form person name.
  - Do not output only the romanized name when the original non-English name is available.
* For non-Person entities, preserve the clearest stable name from the input summary.

2. entity_type
Must be exactly one of:
* Person
* Location
* Organization
* Object
* Time
These categories are mutually exclusive.
Always classify entities based primarily on what they fundamentally are; only when their core nature cannot be clearly determined should their classification be gently influenced by how they are described in the sentence.

Definitions:
Person
* A real human individual.

Location
* A specific place, city, country, venue, residence, destination, etc.

Organization
* Company, school, institution, support group, community, team, government body, etc.

Object
* Product, software, project, device, vehicle, physical item, artwork, document, brand, tool, etc.

Time
* A specific identifiable point or period in time.

3. entity_semantic
A more specific role or category of the entity within the current context.
Requirements:
* Short
* Prefer noun phrases
* No actions
* No complete sentences
* No speculation
* Must be supported by the current context
* Do not describe the entity's internal structure

For Time entities:
* Always use ""
Use "" if the role cannot be determined confidently.
entity_semantic is NOT a restatement of entity_type.
entity_type describes what the entity is.
entity_semantic describes why the entity matters in the user's context.

Examples:
Lili → Friend
Beijing → Residence
Berlin → Travel Destination
Branch Office → Employer
Cursor → Programming Software
MacBook → Computer
Nike → Brand
OpenAI (when user works there) → Employer
OpenAI (when user uses the service) → Software

---

[Time Entity Rules]
Time entities are special.
A specific date, year, month, period, or timestamp may be extracted even if it does not independently satisfy the long-term memory value criteria.
Extract only concrete and identifiable time expressions.

Examples:
✅ 2023-05-07
✅ May 2023
✅ 2024
✅ last summer
✅ freshman year
✅ high school

Do NOT extract vague or relative time expressions.
Examples:
❌ recently
❌ lately
❌ nowadays
❌ these days
❌ right now
❌ soon
❌ someday
❌ at the moment

---

[Entity Selection Rules]
Only extract entities with long-term memory value.
An entity is generally worth extracting if it satisfies at least two of the following:

1. Likely to be mentioned again in the future
Examples:
* Friends
* Frequently visited cities
* Long-term projects
* Frequently used software

2. Important for future understanding
Examples:
* Employer
* Important organizations
* Important people
* Long-term tools

3. Has a clear relationship to the user
Examples:
* My friend
* My company
* My project
* My school

4. Exists over a relatively long period of time
Examples:
* Residence
* Ongoing project
* Frequently used software
* Educational institution

5. Useful for future recommendation, retrieval, or action
Examples:
* Work organizations
* Travel destinations
* Software tools
* Long-term projects

6. A concrete, identifiable, reusable entity
Examples:
* MacBook
* Cursor
* VS Code
* OpenAI
* Harvard University

---

[Do Not Extract]
Never extract:
1. The user
2. The assistant, AI system, or information introduced by the assistant
Examples:
❌ ChatGPT
❌ Assistant
❌ Melanie

unless the user explicitly discusses them as a meaningful long-term entity.

3. Ambiguous references or temporary conversational references
Examples:
❌ someone
❌ everyone
❌ somewhere
❌ here
❌ there
❌ this
❌ that

4. Generic populations or anonymous groups
Examples:
❌ people with similar issues
❌ software engineers
❌ college students
❌ local residents
❌ LGBTQ people

Only extract if the group itself is a specific identifiable entity.
Examples:
✅ LGBTQ support group
✅ Stanford AI Lab

5. One-time identifiers
Examples:
❌ verification code
❌ order number
❌ log ID

6. Casual information without lasting significance
Examples:
❌ milk tea
❌ today's weather

7. Abstract concepts
Examples:
❌ work pressure
❌ lifestyle pace
❌ happiness
❌ anxiety
❌ self-acceptance

8. States
Examples:
❌ beginner
❌ busy
❌ unemployed

9. Behaviors, actions, goals, plans, aspirations, or intentions
Examples:
❌ learning programming
❌ studying psychology
❌ becoming a counselor
❌ working in mental health
❌ going to a movie
❌ drinking more water

10. Preferences
Examples:
❌ liking music
❌ enjoying travel
❌ interest in AI

These belong to memory facts or preferences, not entity nodes.

---

Final Reminder:
Extract entities, not facts.
If a phrase primarily describes:
* an action
* a behavior
* a plan
* a goal
* an intention
* a preference
* a feeling
* a state
* an abstract concept
* a generic group

then it is NOT an entity and must not be extracted.
Return JSON array only.
"""

class EntityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 禁止多余字段
    entity_name: str
    entity_type: str
    entity_semantic: str




