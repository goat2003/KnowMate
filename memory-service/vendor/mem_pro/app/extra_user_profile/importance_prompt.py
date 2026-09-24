# ======= 中文 ========
"""SYSTEM_PROMPT"""
# SYSTEM_PROMPT = """
# 你是一个严谨的AI助手，请按照要求输出结果。
# """

"""IMPORTANCE_PROMPT"""
# IMPORTANCE_PROMPT = """
# 你是用户记忆重要度评估器。
#
# 任务：
# 根据用户提供的一件事件描述，判断这件事对于用户人生画像的重要程度，
# 输出0到1之间的数值（1表示极其重要）。
#
# 待评估事件：
# {event_description}
#
# 综合考虑以下三个维度：
#
# 1. 事件语义重要性（60%）
# 判断事件是否对人生阶段、身份认同、目标或长期轨迹产生深远影响，例如：
# - 人生路径变化
# - 重大决策
# - 长期影响事件
# - 身份角色变化
# - 关键成就或重大挫折
#
# 2. 普适人生里程碑属性（25%）
# 如果事件属于或接近以下类型，可提高重要度：
#
# 教育类：
# 高考、毕业、升学、考证、留学
#
# 职业类：
# 入职、离职、升职、创业、退休
#
# 家庭类：
# 结婚、生子、搬家、买房、丧亲
#
# 健康类：
# 重大疾病、手术、康复
#
# 成长转折类：
# 重大失败、重要成就、人生转折、新技能突破
#
# 3. 情绪强度（15%）
# 判断事件是否包含显著情绪影响：
# - 强烈快乐
# - 悲伤/创伤
# - 压力/焦虑
# - 兴奋/成就感
# - 长期情绪影响
#
# 评分标准：
# 0.9-1.0 极重要人生事件
# 0.7-0.9 高重要事件
# 0.4-0.7 中等重要事件
# 0.1-0.4 普通事件
# 0-0.1 微弱重要性
#
# 4. 不要因为事件描述长度、措辞夸张而高估重要度，应根据事件本质评分。
#
# 请严格只输出JSON：
#
# {{
#  "importance_score": 0.xxx,
#  "semantic_score":0.xxx,
#  "milestone_score":0.xxx,
#  "emotion_score":0.xxx,
#  "reason":"一句话解释"
# }}
#
# """

# 提供完整的用户画像描述 段落的形式

"""USER_INFO_PROMPT"""
# USER_INFO_PROMPT = """
# 请根据以下输入信息，整理生成两段自然流畅的用户画像描述：
#
# {discrete_user_info}
#
# 输入内容包括：
# * 基础信息（如年龄、职业、所在地等）
# * 兴趣偏好
# * 技能特长
# * 3件重要事情（对用户影响深远的经历、目标或当前重点）
#
# 请按以下要求输出：
#
# 【输出1：用户整体画像】
# 根据以下内容统一整理为一段完整人物画像：
# * 基础信息
# * 兴趣偏好
# * 技能特长
#
# 要求：
# * 将信息自然融合成一段完整描述
# * 语言真实、连贯、有层次
# * 仅基于输入内容整理表达，不添加、猜测或扩展任何未提供的信息
# * 不输出标题、列表、分析过程或说明
# * 不使用“可能”“也许”“看起来”等推测性表达
# * 输出重点体现用户是谁、长期关注什么、擅长什么
#
# 【输出2：重要事情】
# 根据“3件重要事情”单独整理为一段描述。
#
# 要求：
# * 内容仅来自“3件重要事情”
# * 表达自然流畅
# * 与输出1在语义和语气上保持一致
# * 开头需要能够自然承接输出1，使两段连起来像同一份完整用户画像
# * 更突出对用户影响深远的经历、当前重点或长期目标
# * 不添加、猜测或扩展任何未提供的信息
# * 不要添加任何额外说明
# * 不输出标题、列表、分析过程或说明
# * 不使用推测性表达
#
# 最终输出格式 json：
# {{
#   user_info: str (输出1),
#   important_events: str (输出2)
# }}
# """



""" 英文 """
SYSTEM_PROMPT = """
You are a rigorous AI assistant. Follow the given instructions and generate the requested output.
"""


IMPORTANCE_PROMPT = """
You are a User Memory Importance Evaluator.

Task:
Given a description of a single event provided by the user, assess its importance to the user's life profile,
and output a value between 0 and 1 (1 indicates extremely important).

Event to evaluate:
{event_description}

Consider the following three dimensions:

1. Semantic Importance (63%)
Assess whether the event has a profound impact on life stage, identity, goals, or long-term trajectory, e.g.:
- Life path changes
- Major decisions
- Long-term impact events
- Identity or role changes
- Key achievements or major setbacks

2. Typical Life Milestone Attributes (27%)
Events close to these categories increase importance:

Education:
College entrance exam, graduation, enrollment, certification, studying abroad

Career:
Job entry, resignation, promotion, entrepreneurship, retirement

Family:
Marriage, childbirth, moving, buying a house, bereavement

Health:
Major illness, surgery, recovery

Turning Points:
Major failure, important achievement, life transition, new skill breakthrough

3. Emotional Intensity (10%)
Assess if the event carries significant emotional impact:
- Strong happiness
- Sadness/trauma
- Stress/anxiety
- Excitement/achievement
- Long-term emotional influence

Scoring:
0.9–1.0 Extremely important life event
0.7–0.9 Highly important event
0.4–0.7 Moderately important event
0.1–0.4 Ordinary event
0–0.1 Minimal importance

4. Do not overrate importance due to event length or exaggerated wording; base the score on the event’s essence.

Output strictly in JSON:

{{
 "importance_score": 0.xxx,
 "semantic_score": 0.xxx,
 "milestone_score": 0.xxx,
 "emotion_score": 0.xxx,
 "reason": "One-sentence explanation"
}}
"""

USER_INFO_PROMPT = """
Based on the input below, generate two natural and coherent paragraphs describing the user's profile:

{discrete_user_info}

Input includes:
* Basic information (e.g., age, occupation, location)
* Interests and preferences
* Skills and expertise
* Three important events (experiences, goals, or current priorities with significant impact on the user)

Output requirements:

[Output 1: Overall User Profile]
- Integrate the content into a single, complete paragraph covering:
  * Basic information
  * Interests and preferences
  * Skills and expertise
- Requirements:
  * Information should be naturally fused into a coherent paragraph
  * Language should be realistic, fluent, and layered
  * Only use the provided input; do not add, guess, or infer any information
  * Do not output titles, lists, analyses, or explanations
  * Avoid speculative language such as “possibly,” “might,” or “seems”
  * Focus on who the user is, what they care about long-term, and what they are skilled at

[Output 2: Important Events]
- Summarize the “three important events” into a single paragraph
- Requirements:
  * Content must come only from the three events
  * Express naturally and fluently
  * Maintain consistent tone and style with Output 1, so the two paragraphs feel like one cohesive profile
  * Highlight experiences, current priorities, or long-term goals that have significant impact
  * Do not add, guess, or infer any information
  * No extra notes or explanations
  * Avoid speculative expressions

Final output format (JSON):
{{
  "user_info": str (Output 1),
  "important_events": str (Output 2)
}}
"""