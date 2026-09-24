"""
解析 用户问卷 json
"""

import json
from pathlib import Path
# 这里复用项目统一的 LLMClient，因此模型、base_url、api_key 都走 .env / llm_conf.py。
from app.common.client.llm_client import get_llm_client
from app.questionnaire.questionnaire_server.profile_init_prompt import SYSTEM_PROMPT, MERGE_PROFILE_BY_QUESTIONNAIRE
from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore

class ProfileInitServer:
    def __init__(self):
        self.user_info_store = UserInfoStore()

    @ staticmethod
    # ================== 基础工具函数 ===================
    def load_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    @staticmethod
    def load_json(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)


    # ================== 调用 llm ===================
    # ====== 解析 用户问卷 json 并生成新的 json 文件 =======
    # ============ 新问卷合并到旧画像 ==============
    async def merge_profile(
            self,
            answer:dict    # 新问卷回答 json 路径
    ) -> dict:
        client = await get_llm_client()

        # ============= 获取 问卷回答 json ================
        # answer = self.load_text(path)
        role_id = answer["role_id"]
        q_response = json.dumps(answer, ensure_ascii=False)

        # ============= 获取旧画像 判断 user_info 节点是否存在 =============
        # 初始化
        await self.user_info_store.uniq_user_info()
        exist = await self.user_info_store.query_by_role_id(role_id)
        # user_info 存在
        if exist:
            old_profile = {
                "basic_info": exist["basic_info"],
                "preference": exist["preference"],
                "skill": exist["skill"]
            }
        else:
            old_profile = {
                "basic_info": "",
                "preference": "",
                "skill": ""
            }

        # 扔 llm 中解析 并生成聚合的画像内容
        user_prompt = MERGE_PROFILE_BY_QUESTIONNAIRE.format(
            old_profile=old_profile,
            answers_json=q_response
        )

        response = await client.chat(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=False,
            temperature=0.3
        )

        result_dict = json.loads(response.content)

        # print("result_llm: ", response.content)
        # print(type(result_dict))

        return result_dict



    # ========== 存入 user_info_node =========
    async def save_in_user_info(
            self,
            answer_dict: dict
    ):
        return
