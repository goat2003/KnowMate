from app.extra_user_profile.importance_prompt import IMPORTANCE_PROMPT, SYSTEM_PROMPT
from app.common.client.llm_client import get_llm_client
import json
from app.memory.fact_node.fact_graph.fact_store import FactStore

class UserProfile:
    def __init__(self):
        self.fact_graph_repository = FactStore()

    """
    对fact节点插入importance值 -> create fact
    从里面获取 importance(llm判断的重要度) / confidence(源头个数)
    什么时候进行重要度判断:
    DerivedFact 
    派生节点变成稳定节点的时候
     
    OriginalFact
    原生事实节点创建的时候
    """
    async def get_fact_content(self, fact_uuid:str, fact_label:str):
        # 获取 fact 节点 所有信息
        fact_info = await self.fact_graph_repository.get_fact_by_uuid(fact_label, fact_uuid)
        content = fact_info[0]["content"] # 获取 summary
        return content

    # llm 对事件进行评分
    async def get_importance_score(self, summary:str) -> float:
        client = await get_llm_client()

        # 当前对话
        input_text = json.dumps(summary, ensure_ascii=False)

        user_prompt = IMPORTANCE_PROMPT.format(
            event_description=input_text
        )

        response = await client.chat(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=False,
            temperature=0.3
        )

        result_dict = json.loads(response.content)

        # print("result_llm: ", response.content)

        # 返回 importance_score 最终计算的数值
        return result_dict["importance_score"]


    # 更新 fact 节点 importance 字段
    # 要区分 原始fact 派生fact
    async def update_fact_importance(
            self,
            label: str,
            fact_uuid: str
    ):
        # 获取 fact 节点 content
        content = await self.get_fact_content(fact_uuid, label)

        # 对 content 进行重要度评分
        importance_score = await self.get_importance_score(content)

        # 写进节点中 importance_score 属性
        await self.fact_graph_repository.update_fact(
            label,
            fact_uuid,
            "importance",
            importance_score)


if __name__ == "__main__":
    up = UserProfile()
    import asyncio

    # summary = "用户2025年考进了当地法院当了法官。"
    summary = "我今早吃了一个苹果。"
    result = asyncio.run(up.get_importance_score(summary))
    print(result)
    print(type(result))


    # 示例输出
    """
    result_llm:  {
     "importance_score": 0.923,
     "semantic_score": 0.950,
     "milestone_score": 0.900,
     "emotion_score": 0.850,
     "reason":"成为法官是重大职业身份与长期人生轨迹的转折，属于重要职业里程碑并伴随显著成就感。"
    }
    0.923
    <class 'float'>
    """

