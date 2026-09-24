"""
问卷 markdown
      +
用户答案 JSON
      ↓
构造 Prompt
      ↓
LLM 生成画像 JSON
      ↓
校验 JSON
      ↓
保存 generated_user_info_profile.json
      ↓
调用 user_info_store01.py
      ↓
写入 Neo4j
"""


from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

# 两个目录同时存在的位置。
# app/
# doc/
def find_project_root(start: Path) -> Path:
    """
    从当前脚本位置向上查找项目根目录。

    这个脚本可能放在 scripts/，也可能作为 app 内模块执行；不能依赖固定的
    parents[n] 层级，否则移动文件后会拼出错误的 doc 路径。
    """
    for path in (start, *start.parents):
        if (path / "app").is_dir() and (path / "doc").is_dir():
            return path
    raise RuntimeError(f"Cannot find project root from: {start}")


PROJECT_ROOT = find_project_root(Path(__file__).resolve().parent)
# 允许从任意目录直接执行时，也能正常 import app 下的项目模块。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 默认围绕 v1.0 问卷目录工作：读取问卷定义和答案，产出三字段画像 JSON。
QUESTIONNAIRE_DIR = PROJECT_ROOT / "doc" / "USER_PROFILE_QUESTIONNAIRE_v1.0"
DEFAULT_QUESTIONNAIRE_PATH = QUESTIONNAIRE_DIR / "USER_PROFILE_QUESTIONNAIRE.md"                            # 问卷定义，给模型看用的
DEFAULT_ANSWERS_PATH = QUESTIONNAIRE_DIR / "mock_questionnaire_answer.json"                                 # 问卷答案，给模型看用的；实际使用时会传真实用户的答案 JSON 路径
DEFAULT_OUTPUT_PATH = QUESTIONNAIRE_DIR / "generated_user_info_profile.json"                                # 生成的用户画像 JSON 路径；实际使用时可以指定到其他地方，但建议放在 doc/ 目录下，方便审阅和后续导入 user_info_store01.py
USER_INFO_STORE_PATH = PROJECT_ROOT / "app" / "user_info_node" / "user_info_graph" / "user_info_store01.py"   # 负责把生成的画像 JSON 写入 UserInfoNode 的脚本路径

# UserInfoNode 只写入后三个画像字段；role_id 用于把这份画像路由到正确用户。
PROFILE_FIELDS = ("basic_info", "preference", "skill")
REQUIRED_OUTPUT_FIELDS = ("role_id", *PROFILE_FIELDS)

# 三种写库模式，直接传给 user_info_store01.py 处理，避免本脚本重复实现写库策略。
# create-only: 只在 UserInfoNode 不存在时创建；如果 role_id 已存在则跳过。
# overwrite: 如果三字段画像内容变化，则覆盖；如果内容相同则返回 unchanged。
# merge: 如果三字段画像内容变化，则保留旧画像并追加新画像；如果内容相同则返回 unchanged。
WRITE_MODES = ("create-only", "overwrite", "merge")


# 系统提示词负责约束“只基于问卷答案生成、不要推断、输出严格 JSON”。
SYSTEM_PROMPT = """
你是一个社交软件的用户画像生成助手。你的任务是根据用户填写的问卷答案，生成可以写入 UserInfoNode 的用户画像。

当前 UserInfoNode 只支持三个字段：
1. basic_info：用户基础事实资料，例如城市、职业、学校、年龄段、当前状态、近况。
2. preference：用户兴趣、社交目的、想认识的人、可聊话题、活动偏好、社交节奏、匹配偏好。
3. skill：用户已有技能、正在学习的技能、愿意教别人的技能、希望找人一起练习的技能。

输出 JSON 需要额外包含 role_id 字段，用于标识这份画像属于哪个用户；role_id 必须来自问卷答案或调用方显式指定的 role_id，不要改写、翻译或编造。

请严格遵守：
1. 只根据输入的问卷答案生成画像，不要编造用户没有提供的信息。
2. 基础事实只能来自用户明确填写的内容，不要根据兴趣推断性别、年龄、职业、城市。
3. 兴趣标签是重要信号；如果有 top_interests 或强兴趣排序，需要优先体现。
4. free_text 是高价值信号，如果自由文本比选项更具体，优先保留自由文本中的具体表达。
5. trait_scores 只用于生成温和的社交倾向描述，不要输出人格诊断。
6. 如果某个字段没有足够信息，请写“用户暂未提供明确……信息”，不要硬编。
7. 输出语言要自然、简洁、适合长期保存为用户画像。
8. 输出必须是严格 JSON，不要 Markdown，不要解释。
9. JSON 必须且只能包含 role_id、basic_info、preference、skill 四个字段。
10. 每个字段的值必须是字符串，不要输出数组或对象。
""".strip()


# 解析命令行参数
def parse_args() -> argparse.Namespace:
    # write-mode 会原样传给 user_info_store01.py，避免本脚本重复实现写库策略。
    parser = argparse.ArgumentParser(
        description="Generate UserInfoNode profile JSON from questionnaire answers, then write it through user_info_store01.py."
    )
    parser.add_argument(
        "--questionnaire",
        type=Path,
        default=DEFAULT_QUESTIONNAIRE_PATH,
        help=f"Questionnaire markdown path. Defaults to {DEFAULT_QUESTIONNAIRE_PATH}",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=DEFAULT_ANSWERS_PATH,
        help=f"Questionnaire answers JSON path. Defaults to {DEFAULT_ANSWERS_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Generated profile JSON path. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--role-id",
        help="Override role_id used in generated JSON and passed to user_info_store01.py. If omitted, it is read from --answers.",
    )
    parser.add_argument(
        "--write-mode",
        choices=WRITE_MODES,
        default="create-only",
        help="Mode passed to user_info_store01.py. Defaults to create-only.",
    )
    parser.add_argument(
        "--no-write-db",
        action="store_true",
        help="Only generate the profile JSON; do not execute user_info_store01.py.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help="Max tokens for LLM profile generation.",
    )
    return parser.parse_args()


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_role_id(answers: dict, role_id_override: str | None) -> str:
    if role_id_override:
        return role_id_override

    role_id = answers.get("role_id")
    if not isinstance(role_id, str) or not role_id.strip():
        raise ValueError("role_id is missing from answers JSON. Pass --role-id to set it explicitly.")

    return role_id.strip()


def validate_profile(profile: dict, expected_role_id: str) -> dict[str, str]:
    # 对 LLM 输出做硬校验：字段少了、多了、类型不对都直接失败，避免脏数据写库。
    missing_fields = [field for field in REQUIRED_OUTPUT_FIELDS if field not in profile]
    extra_fields = [field for field in profile if field not in REQUIRED_OUTPUT_FIELDS]
    invalid_fields = [
        field
        for field in REQUIRED_OUTPUT_FIELDS
        if field in profile and not isinstance(profile[field], str)
    ]

    if missing_fields:
        raise ValueError(f"LLM profile missing fields: {', '.join(missing_fields)}")
    if extra_fields:
        raise ValueError(f"LLM profile has extra fields: {', '.join(extra_fields)}")
    if invalid_fields:
        raise ValueError(f"LLM profile fields must be strings: {', '.join(invalid_fields)}")

    clean_profile = {field: profile[field].strip() for field in REQUIRED_OUTPUT_FIELDS}
    if clean_profile["role_id"] != expected_role_id:
        raise ValueError(
            f"LLM profile role_id mismatch: expected {expected_role_id}, got {clean_profile['role_id']}"
        )

    return clean_profile


def build_prompt(questionnaire_text: str, answers: dict, role_id: str) -> str:
    # 把完整问卷定义和用户答案一起给模型，便于模型理解 option_id 的真实含义。
    answers_json = json.dumps(answers, ensure_ascii=False, indent=2)
    return f"""
【问卷版本】
{questionnaire_text}

【问卷答案】
{answers_json}

【本次输出 role_id】
{role_id}

请输出如下严格 JSON：
{{
  "role_id": "{role_id}",
  "basic_info": "……",
  "preference": "……",
  "skill": "……"
}}
""".strip()


async def generate_profile(
        questionnaire_path: Path,
        answers_path: Path,
        max_tokens: int,
        role_id_override: str | None = None
) -> dict[str, str]:
    # 这里复用项目统一的 LLMClient，因此模型、base_url、api_key 都走 .env / llm_conf.py。
    from app.common.client.llm_client import get_llm_client

    questionnaire_text = load_text(questionnaire_path)
    answers = load_json(answers_path)
    role_id = resolve_role_id(answers, role_id_override)
    prompt = build_prompt(questionnaire_text, answers, role_id)

    client = await get_llm_client()
    try:
        # json_mode=True 会请求 OpenAI 兼容接口返回 JSON object；temperature=0 降低输出漂移。
        response = await client.chat(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=True,
            temperature=0,
            max_tokens=max_tokens,
        )
    finally:
        # 脚本型任务执行完就释放底层 HTTP 连接。
        await client.close()

    if not isinstance(response.content, dict) or not response.content:
        raise RuntimeError(f"LLM did not return valid JSON content: {response.content}")

    return validate_profile(response.content, role_id)


def save_profile(profile: dict[str, str], output_path: Path) -> None:
    # 生成结果落到固定 JSON 文件，后续可以单独审阅或用 user_info_store01.py 重复导入。
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(profile, file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_profile_to_db(profile_path: Path, answers_path: Path, role_id: str | None, write_mode: str) -> None:
    # 写库仍然交给 UserInfoStore 的 CLI。
    command = [
        sys.executable,
        str(USER_INFO_STORE_PATH),
        "--profile",
        str(profile_path),
        "--answers",
        str(answers_path),
        "--mode",
        write_mode,
    ]
    if role_id:
        command.extend(["--role-id", role_id])

    # 捕获输出再转发，方便调用方看到 user_info_store01.py 返回的 write_status。
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)


async def main() -> None:
    args = parse_args()

    # 主流程：问卷答案 -> LLM role_id + 三字段画像 -> 保存 JSON -> 可选写入 UserInfoNode。
    print(f"Generating profile for role_id: {args.role_id or '(from answers)'}...")
    profile = await generate_profile(
        args.questionnaire,
        args.answers,
        args.max_tokens,
        role_id_override=args.role_id,
    )
    save_profile(profile, args.output)
    print(f"Generated profile JSON: {args.output}")

    if args.no_write_db:
        return

    write_profile_to_db(args.output, args.answers, args.role_id, args.write_mode)


if __name__ == "__main__":
    asyncio.run(main())
