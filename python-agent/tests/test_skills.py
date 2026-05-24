# 文件作用：
# 本文件测试 Agent 技能提示词文件是否齐全且包含必需章节。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的测试层，覆盖 app/skill_loader.py 和 app/skills/*.md。
#
# 主要内容：
# 1. REQUIRED_SKILLS：必须存在的技能文件名。
# 2. REQUIRED_SECTIONS：每个技能文件必须包含的章节。
# 3. SkillLoaderTest：验证技能加载结果。
#
# 初学者阅读建议：
# 技能文件是 LLM prompt 规则，不是 Python 代码；这些测试保证每个 Agent 都有可读的提示词规范。
import unittest

from app.skill_loader import load_skills


# REQUIRED_SKILLS 是 ArticleWorkflow 初始化时会读取的关键技能文件。
REQUIRED_SKILLS = [
    "filter_skill",
    "summary_skill",
    "rewrite_post_skill",
    "fact_check_skill",
    "feedback_extract_skill",
    "memory_update_skill",
    "mcp_tool_usage_skill",
]

# REQUIRED_SECTIONS 是每个技能文件应该包含的说明章节，帮助提示词保持统一结构。
REQUIRED_SECTIONS = [
    "## 任务目标",
    "## 输入格式",
    "## 输出格式",
    "## 约束条件",
    "## 可调用 MCP Tool",
    "## 禁止调用 MCP Tool",
    "## 失败处理",
    "## 示例",
]


# 类作用：
# SkillLoaderTest 测试技能文件加载和内容完整性。
class SkillLoaderTest(unittest.TestCase):
    # 函数作用：
    # 验证必需技能文件都能加载，并且包含约定章节。
    def test_required_skill_files_are_loaded_and_non_empty(self) -> None:
        # load_skills 会读取 app/skills 下所有 Markdown 文件。
        skills = load_skills()

        # subTest 让每个 skill 独立报告失败，便于定位具体缺失文件或章节。
        for name in REQUIRED_SKILLS:
            with self.subTest(skill=name):
                self.assertIn(name, skills)
                self.assertTrue(skills[name].strip())
                for section in REQUIRED_SECTIONS:
                    self.assertIn(section, skills[name])


# 直接运行该测试文件时执行 unittest。
if __name__ == "__main__":
    unittest.main()
