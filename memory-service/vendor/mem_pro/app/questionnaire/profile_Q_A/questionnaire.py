"""
用户回答问卷问题 以 json 格式输出
"""

import json
import random
import time

from pathlib import Path

def run_questionnaire(question_file: str, output_file: str, role_id: str):
    # 读取题目文件
    with open(question_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    # 提前初始化
    questionnaire_id = None
    version = None

    answers = []

    for q in questions:
        print(q.get("prompt", "") + "\n")
        answered_at = int(time.time())

        if q["type"] == "questionnaire_title":
            # 获取 questionnaire_id 和 version
            questionnaire_id = q["questionnaire_id"]
            version = q["version"]

        elif q["type"] == "fields":
            field_values = {}

            # ============ 测试用 随机选择答案 =================
            field_options = [
                ["女", "男", "其他", "暂不说明"],
                # 出生日期
                [
                    "2001-09-24",
                    "1999-11-27",
                    "2000-09-16",
                    "1997-03-01",
                    "1998-07-12",
                    "2002-01-30",
                    "1996-05-18",
                    "2003-12-08"
                ],

                # 地区
                [
                    "浙江",
                    "苏州",
                    "深圳",
                    "哈尔滨",
                    "北京",
                    "上海",
                    "广州",
                    "成都",
                    "武汉",
                    "杭州"
                ],

                # 学校
                [
                    "苏州大学",
                    "上海交通大学",
                    "天津大学",
                    "北京大学",
                    "清华大学",
                    "复旦大学",
                    "浙江大学",
                    "南京大学",
                    "武汉大学",
                    "中山大学"
                ],

                # 职业
                [
                    "大学讲师",
                    "工程师",
                    "外贸",
                    "博士",
                    "产品经理",
                    "数据分析师",
                    "程序员",
                    "设计师",
                    "医生",
                    "律师"
                ]
            ]
            # ============ 测试完毕 ===================

            for field, filed_option in zip(q["fields"], field_options):
                # value = input(f"{field}: ")

                # ============ 测试用 随机选择答案 =================
                value = random.choice(filed_option)
                # ============ 测试完毕 ===================

                field_values[field] = value

            # free_text = input("可填写额外信息（选填）: ")
            free_text = ""

            answers.append({
                "question_id": q["question_id"],
                "field_values": field_values,
                "free_text": free_text
            })
            print("answers:", answers)

        elif q["type"] == "multi_choice":
            print("选项:", ", ".join(q["options"]))

            # ========= 自定义输入要放开 =============
            # ranked = input("请按优先顺序选择（多选用逗号分隔）: ").replace(" ", "").split(",")
            # free_text = input("可填写额外说明（选填）: ")

            # ============ 测试用 随机选择答案 =================
            options = q["options"]
            ranked = random.choice(options)
            free_text = ""
            # ============ 测试完毕 ===================

            answers.append({
                "question_id": q["question_id"],
                "selected_option_ids": ranked,
                "free_text": free_text
            })

        elif q["type"] == "single_choice":
            print("选项:", ", ".join(q["options"]))

            # ========= 自定义输入要放开 =============
            # selected = input("请选择: ")
            # free_text = input("可填写额外说明（选填）: ")

            # ============ 测试用 随机选择答案 =================
            selected = q["options"]
            ranked = random.choice(selected)
            free_text = ""
            # ============ 测试完毕 ===================

            answers.append({
                "question_id": q["question_id"],
                "ranked_option_ids": selected,
                "free_text": free_text
            })

        elif q["type"] == "text":
            # ========= 自定义输入要放开 =============
            # text = input("请输入文本回答: ")

            # ============ 测试用 随机选择答案 =================
            text = "Hello World"
            # ============ 测试完毕 ===================

            answers.append({
                "question_id": q["question_id"],
                "prompt_id": q.get("prompt_id"),
                "text_answer": text
            })

    # 生成完整 JSON
    result = {
        "role_id": role_id,
        "questionnaire_id": questionnaire_id,
        "questionnaire_version": version,
        "answers": answers
    }

    # 写入文件
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 问卷完成，已保存到 {output_file}")

    return result

# 示例调用
if __name__ == "__main__":
    run_questionnaire("questions01.json", "user_response.json")