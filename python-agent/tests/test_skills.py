import unittest

from app.skill_loader import load_skills


REQUIRED_SKILLS = [
    "filter_skill",
    "summary_skill",
    "rewrite_post_skill",
    "fact_check_skill",
    "feedback_extract_skill",
    "memory_update_skill",
    "mcp_tool_usage_skill",
]

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


class SkillLoaderTest(unittest.TestCase):
    def test_required_skill_files_are_loaded_and_non_empty(self) -> None:
        skills = load_skills()

        for name in REQUIRED_SKILLS:
            with self.subTest(skill=name):
                self.assertIn(name, skills)
                self.assertTrue(skills[name].strip())
                for section in REQUIRED_SECTIONS:
                    self.assertIn(section, skills[name])


if __name__ == "__main__":
    unittest.main()
