"""
用户画像相关检索

重要事件检索
1. 通过 role_id 对 fact 层进行检索
2. 限制条件：importance_score 大于一个临界值
   该值是由 llm 判断的事件重要度的打分
3. 计算该事件最终重要度分值
   final = mu1 * importance_score + mu2 * confidence
   importance_score 和 confidence(源头个数) 加权计算
4. 排序

用户基本信息检索/更新
是否需要更新 user_info 节点中字段，由 fact 节点 summary 判断

原始 fact：可直接进行更新嚯覆盖
派生 fact：需设置 confidence 临界值。
          当当前节点 confidence 大于临界值时，即可更新 user_info
"""

"""
每天一次检索用户画像信息
存储于文本文件
"""

import json
from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore
from app.memory.fact_node.fact_graph.fact_store import FactStore
from app.common.client.llm_client import get_llm_client
from app.extra_user_profile.importance_prompt import USER_INFO_PROMPT , SYSTEM_PROMPT

class ProfileSearch:
    def __init__(self):
        self.user_info_store = UserInfoStore()
        self.fact_graph_repository = FactStore()


    """
    获取 info 信息   
    基础信息、偏好、技能和重要事件
    """
    async def get_user_info(self, role_id: str):
        all_info = await self.user_info_store.query_by_role_id(role_id)

        # 获取 top-3 重要事件
        important_events = await self.fact_graph_repository.get_top_k_facts_by_role(
            role_id,
            3,  # 选取前k个重要事件
            0.75,
            0.25,
            0.1  # 筛选条件临界值
        )

        # 构造 prompt 所需输入
        result_important_events = []
        for event in important_events:
            result_important_events.append(event["content"])

        infos = {
            "basic_info": all_info["basic_info"],
            "preference": all_info["preference"],
            "skill": all_info["skill"],
            "important_events": result_important_events
        }

        return json.dumps(infos)


    # 调用 llm 生成用户画像段落
    async def generate_profile_phase(self, role_id: str):
        client = await get_llm_client()

        # 待输入信息
        infos = await self.get_user_info(role_id)

        user_prompt = USER_INFO_PROMPT.format(
            discrete_user_info=infos
        )

        response = await client.chat(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=False,
            temperature=0.3
        )

        return response.content


if __name__ == '__main__':
    ps = ProfileSearch()
    role_id = "1"

    import asyncio
    result = asyncio.run(ps.generate_profile_phase(role_id))
    print(result)
    print(type(result))
