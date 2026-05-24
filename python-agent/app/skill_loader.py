# 文件作用：
# 本文件负责读取 Python Agent 使用的技能提示词文件。
# 技能文件位于 app/skills/*.md，内容会作为 LLM system prompt 的补充规则。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的工具层，被 ArticleWorkflow 初始化时调用。
#
# 主要内容：
# 1. load_skills：批量读取技能目录下的 Markdown 文件。
# 2. load_skill：读取单个技能文本。
#
# 关键调用关系：
# - 被 app.workflow.graph.ArticleWorkflow.__init__ 调用。
# - 读取结果会传给 FilterAgent、SummaryAgent、RewriteAgent、FeedbackAgent、MemoryAgent。
#
# 初学者阅读建议：
# 先理解“技能文件”只是提示词文本，不是可执行代码；
# 再看 ArticleWorkflow 如何用 skills.get("xxx_skill") 取出对应 Agent 的规则。
from __future__ import annotations

from pathlib import Path


# 函数作用：
# 读取技能目录下所有 Markdown 文件，并按文件名 stem 组成字典。
#
# 参数说明：
# - skills_dir：可选技能目录；不传时使用 app/skills。
#
# 返回值：
# - 返回 dict[str, str]，key 是文件名去掉 .md 后的名称，value 是文件文本。
#
# 调用关系：
# - 被 ArticleWorkflow.__init__ 调用，用于一次性加载所有 Agent 技能提示词。
def load_skills(skills_dir: Path | None = None) -> dict[str, str]:
    # 如果调用方没有传目录，就从当前文件位置推导 app/skills 目录。
    base = skills_dir or Path(__file__).resolve().parent / "skills"
    # skills 用来累计每个技能文件的内容。
    skills: dict[str, str] = {}
    # sorted(...) 保证读取顺序稳定，方便测试和调试。
    for path in sorted(base.glob("*.md")):
        # path.stem 是不带扩展名的文件名，例如 filter_skill。
        # read_text(encoding="utf-8") 明确按 UTF-8 读取中文提示词。
        skills[path.stem] = path.read_text(encoding="utf-8")
    return skills


# 函数作用：
# 读取单个技能文本。
#
# 参数说明：
# - name：技能名称，对应 Markdown 文件名去掉 .md 后的部分。
# - skills_dir：可选技能目录。
#
# 返回值：
# - 找到时返回技能文本，找不到时返回空字符串。
def load_skill(name: str, skills_dir: Path | None = None) -> str:
    # 复用 load_skills，避免单独维护一套目录查找逻辑。
    return load_skills(skills_dir).get(name, "")
