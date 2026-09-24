from app.memory.user_info_node.profile_prompt.profile_prompt import BASIC_RULE_PROFILE

"""中文"""
# SYSTEM_PROMPT = """
# 你是一个严谨的AI助手，请按照要求输出结果。
# """
#
# # user_info_node 合并画像
# MERGE_PROFILE_BY_QUESTIONNAIRE = BASIC_RULE_PROFILE + """
# 任务：
# 根据用户填写的问卷答案，生成可写入 UserInfoNode 的用户画像。
#
# 请严格遵守：
#
# 【基础原则】
#
# 1. 仅依据问卷答案和已有画像生成结果，不得编造用户未明确提供的信息。
#
# 2. 输出必须为严格 JSON。
# 禁止 Markdown、代码块、解释说明或任何额外文本。
#
# JSON 必须且只能包含以下字段：
#
# - role_id
# - basic_info
# - preference
# - skill
#
# 3. 兴趣标签属于高价值信号。
#
# 若存在 top_interests、兴趣排序或明确的兴趣强度信息，应优先体现在画像中。
#
# 4. free_text 属于高价值信息源。
#
# 当自由文本提供的信息比选项更加具体、准确或丰富时，应优先保留自由文本中的表达，并与其他信息进行融合。
#
# 5. trait_scores 仅用于生成温和、非诊断性的社交倾向描述。
#
# 禁止输出：
#
# - 人格类型
# - 心理测评结果
# - MBTI推断
# - 性格诊断
# - 精神状态判断
#
# 6. 输出内容应自然、简洁、稳定，适合作为长期维护的用户画像。
#
# 每个字段均应使用完整描述句，不得输出关键词列表或标签集合。
#
# 7. 无论输入内容使用何种语言（包括但不限于中文、英文、日文、韩文、法文、西班牙文等），必须先统一转换为中文后再进行理解、判断、画像融合与推理。
#
# 所有语义分析、偏好归纳、技能识别、画像更新和信息融合均必须基于中文语义完成。
#
# 最终输出的所有字段必须使用自然、地道、符合中文表达习惯的中文书写。
#
# 禁止：
#
# - 保留原语言内容；
# - 混合语言输出；
# - 使用翻译腔表达；
# - 直接沿用外语语序；
# - 保留明显的外语表达结构。
#
# 应优先采用符合中文用户画像场景的表达方式，使画像能够被中文用户自然理解，并适合长期存储。
#
# 已有画像
# {old_profile}
#
# 问卷答案
# {answers_json}
#
# 请综合已有画像与问卷答案，按照 BASIC_RULE_PROFILE 的规则进行融合更新，并输出最新版本画像。
#
# 输出格式：
#
# {
#   "role_id": str,
#   "basic_info": str,
#   "preference": str,
#   "skill": str
# }
# """

"""英文"""
SYSTEM_PROMPT = """
You are a rigorous AI assistant. Please generate the output according to the requirements.
"""

# user_info_node 合并画像
MERGE_PROFILE_BY_QUESTIONNAIRE = BASIC_RULE_PROFILE + """
Task:

Generate an updated user profile that can be stored in a UserInfoNode based on the user's questionnaire responses.

Follow the rules below strictly.

[Core Principles]

1. Generate the profile only from:
   - the questionnaire responses
   - the existing profile

Do not invent, assume, infer, or fabricate information that is not explicitly supported by the provided data.

2. The output must be valid JSON only.

Do not output:

- Markdown
- Code fences
- Explanations
- Comments
- Any text outside the JSON object

The JSON must contain exactly these four fields:

- role_id
- basic_info
- preference
- skill

No additional fields are allowed.

3. Interest signals are highly important.

If top_interests, ranked interests, favorite categories, or explicit preference rankings are provided, they should be reflected prominently in the profile.

4. Free-text responses are high-value signals.

When free-text responses provide more specific, nuanced, or detailed information than multiple-choice selections, prioritize the information contained in the free-text responses and integrate it with the rest of the profile.

5. trait_scores may only be used to generate mild descriptions of social or interaction preferences.

Do not generate:

- Personality diagnoses
- Personality types
- MBTI classifications
- Psychological assessments
- Mental health conclusions

6. The profile should be concise, natural, and suitable for long-term storage.

Each field should contain complete descriptive sentences rather than keyword lists, labels, or fragmented phrases.

7. Input data may be written in any language.

Before performing any analysis, profile merging, preference extraction, skill identification, or reasoning:

Normalize all information into English.

All reasoning and profile construction must be performed using the English representation.

The final output must also be written entirely in English.

Do not:

- Preserve original-language text
- Produce mixed-language output
- Use literal translation-style wording
- Preserve foreign sentence structures
- Retain language-specific phrasing that sounds unnatural in English

Instead:

Use natural, fluent, and idiomatic English that matches how user profiles are typically written in English-speaking products.

The profile should read naturally to native English speakers and be suitable for long-term storage and future profile updates.

Existing Profile

{old_profile}

Questionnaire Responses

{answers_json}

Using both the existing profile and the questionnaire responses, generate the latest consolidated profile according to all rules defined in BASIC_RULE_PROFILE.

Output format:

{{
  "role_id": str,
  "basic_info": str,
  "preference": str,
  "skill": str
}}
"""