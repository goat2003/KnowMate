"""
集合直接可调用的底层功能函数，他们可以相互组合

* 大模型对对话进行清洗
* 创建 chunk 节点
* 对话内容转成向量
* 存入milvus
"""
from json import JSONDecodeError
# 本文件实现memory层的llm调用
from typing import List, Optional
from pydantic import ValidationError

from app.common.client.llm_client import get_llm_client
# from app.memory_node.prompt.memory_prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.memory.chunk_node.chunk_prompt.wash_data_prompt import (
    SYSTEM_PROMPT,
    WASH_DATA_PROMPT,
    WashingResult,
    Dialogue,
)
from app.memory.chunk_node.chunk_graph.chunk_store import ChunkStore
from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.memory.tools_service import ToolService
# from app.prototype_node.proto_service.label_service import EmbeddingServer
from app.common.client.embedding_client import get_embedding_client
import json
# import ast

class ChunkService:
    def __init__(self):
        self.chunk_store = ChunkStore()
        self.milvus_CRUD = MilvusCRUD()
        self.tool_service = ToolService()
        self.embedding_client = get_embedding_client()
        # self.milvus_CRUD.ensure_collection("chunk_schema")


    # 大模型过滤出有效对话信息
    # @staticmethod
    async def washing_server_llm(self, text: list[dict], history: str, target_object: str) -> dict | None:
        client = await get_llm_client()

        # 当前对话
        input_text = json.dumps(text, ensure_ascii=False)

        user_prompt = WASH_DATA_PROMPT.format(
            dialogue=input_text,
            history=history,
            target_object=target_object
        )

        response = await client.chat(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=True,
            temperature=0.2,
            max_retries=3,
        )
        if response.content == {}:
            return None
        return response.content

    async def save_llm_server(
            self,
            dialogues: list[dict],
            history: str,
            target: str
    ) -> Optional[tuple[str, list[dict]]]:

        for retry in range(3):

            # =====================
            # 1. 调用LLM
            # =====================
            llm_response = await self.washing_server_llm(
                dialogues,
                history,
                target
            )

            print("washing_server_llm response: ", llm_response)

            # =====================
            # 2. 判断是否有输出
            # =====================
            if not llm_response:
                print(
                    f"LLM无输出，第 {retry + 1} 次重试"
                )
                continue

            # =====================
            # 3. Pydantic格式校验
            # =====================
            try:
                WashingResult.model_validate(
                    llm_response
                )

            except ValidationError as e:
                print(
                    f"LLM输出格式错误，第 {retry + 1} 次重试"
                )
                print(e)
                continue

            # =====================
            # 4. 校验成功
            # =====================
            return llm_response["history"], llm_response["dialogues"]

        print(
            "LLM连续3次输出失败，跳过本次处理"
        )

        return None

    # 创建一轮对话的 chunk 节点
    # text: [{user: str, assistant: str, timestamp: int},{}]
    async def single_round_chunk(
            self,
            role_id: str,
            dialogues: List[dict],
            history: str,
            target_object: str
    ) -> Optional[tuple[str, List[str]]]:
        """
        1. 判断该节选对话是否被分析过。 计算 hash
            是：return
            否：扔给大模型并创建新的 chunk 节点
        2. 扔给大模型分析
        3. 创建 chunk 节点
        4. 存 milvus
        """

        chunk_uuids = []

        # ======== 1. 计算hash并判断是否执行过该对话 ===========
        hash_val = self.tool_service.get_hash_val(dialogues)
        exist_chunk_uuids = await self.chunk_store.query_exist_by_hash(hash_val, role_id)
        if exist_chunk_uuids:
            print("该用户已完成这部分对话，勿重复分析")
            return history, exist_chunk_uuids

        # ======== 2. 扔给大模型分析 ===========
        # print("=============== Step 2 扔给大模型分析 ===========")
        llm_result = await self.save_llm_server(dialogues, history, target_object)
        # 若大模型发脾气不给输出，那么将不执行该轮对话的分析和存入 或者 llm_result 有输出但是 dialogues 未空
        if not llm_result:
            return None
        history, dialogues = llm_result

        # 若 dialogues 为空，neo4j 将会被存入空气   要不得要不得
        if not dialogues:
            return None

        # print("history, dialogues")
        # print(history)
        # print(dialogues)

        # ======== 3. 准备 chunk 节点内容 ===============
        # print("======== Step 3. 准备 chunk 节点内容 ===============")
        dialogue_lit = []
        summary_lit = []
        timestamp_lit = []
        for dialogue_info in dialogues:
            dialogue_lit.append(dialogue_info["dialogue"])
            summary_lit.append(dialogue_info["summary"])
            timestamp_lit.append(dialogue_info["timestamp"])

        # ============= 4. 生成向量 ===============
        # print("============= Step 4. 生成向量 ===============")
        # 先生成 embedding，再写 Neo4j，避免 embedding 服务失败时留下半成品 ChunkNode。
        dia_embedding_lit = await self.embedding_client.embed_batch(dialogue_lit)
        summary_embedding_lit = await self.embedding_client.embed_batch(summary_lit)
        # print(len(dia_embedding_lit), len(summary_embedding_lit))
        # print(len(dia_embedding_lit[0]), len(summary_embedding_lit[0]))
        # print(len(dialogue_lit), len(summary_lit), len(timestamp_lit))

        # ======== 5. 创建独立 chunk 节点 ===============
        # print("======== Step 5. 创建独立 chunk 节点 ===============")
        for dialogue, summary, timestamp, dia_embedding, summary_embedding in zip(
                dialogue_lit, summary_lit, timestamp_lit, dia_embedding_lit, summary_embedding_lit):
            # print(len(dia_embedding), len(summary_embedding))
            # print(type(dia_embedding), len(dia_embedding))

            # print("创建一个chunk节点的参数")
            # print(role_id,
            #     dialogue,
            #     summary,
            #     timestamp,
            #     hash_val)

            chunk_uuid = await self.chunk_store.create_chunk(
                role_id,
                dialogue,
                summary,
                timestamp,
                hash_val
            )
            chunk_uuids.append(chunk_uuid)
            # print("chunk_uuid: ", chunk_uuid)

            # print("========== chunk 存milvus =========")
            # 对 content 和 summary 向量化并存入 milvus
            if chunk_uuid:  # 防止 chunk_uuid is None, 执行 milvus 插入报错中断执行
                await self.chunk_save_in_milvus(role_id, chunk_uuid, dia_embedding, summary_embedding)

        return history, chunk_uuids


    async def chunk_save_in_milvus(
            self,
            role_id: str,
            chunk_uuid: str,
            dia_embedding: list[float],
            summary_embedding: list[float]
    ):
        # ============= 6. 存milvus ===============
        # print("============= Step 6. 存milvus ===============")
        data = {
            "role_id": role_id,
            "chunk_uuid": chunk_uuid,
            "fact_uuid": "",
            "dia_embedding": dia_embedding,
            "summary_embedding": summary_embedding
        }

        # print("data: ", data)
        # print("======== chunk_save_in_milvus ==============")
        # print(len(data["dia_embedding"]), len(data["summary_embedding"]))
        # print("============================================")

        await self.milvus_CRUD.insert("chunk_schema", data)

    # 完整上下文的chunk节点构建
    async def create_all_chunks(
       self,
       role_id: str,
       dialogues: List[dict],
       split: int,
       target_object:str
    ) -> List[str]:
        chunk_uuids = []
        history = ""

        for count in range(0, len(dialogues), split):
            dialogue = dialogues[count:count + 3]
            print(f"第{count / 3}次对话分析")
            result = await self.single_round_chunk(
               role_id,
               dialogue,
               history,
               target_object
            )
            print("result: ", result)
            if result is not None:
                history, chunk_uuid = result
                if chunk_uuid:
                    chunk_uuids += chunk_uuid
            else:
                dialogue_round = []
                continue
            dialogue_round = []

        return chunk_uuids




if __name__ == "__main__":
#     ms = ChunkService()
#
#     dialogues = [
#         {
#             "user": "你猜怎么着，最近工作突然面临调动，公司下个月让我去北京分公司常驻了。",
#             "assistant": "这变化好快！去新的城市发展是个不小的挑战，希望你能顺利适应新环境。",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "我现在已经搬到北京生活了，正式开始了北漂的日子。",
#             "assistant": "看来你已经顺利入职北京分公司了，要注意保暖和防风防燥啊。",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "北京的天气真的是挺干燥的，跟以前在上海完全不一样，我还在想办法多补水。",
#             "assistant": "确实，南北气候差异很大，建议在房间里备个加湿器，平时一定要多喝水。",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "我有一个假期，请推荐一些事情我可以在假期中做的",
#             "assistant": "你可以去看电影，旅游，攀岩",
#             "create_at": 1775270805.0674586
#         },
#         {
#             "user": "攀岩可以",
#             "assistant": "你可以去xx，那里有不同高度不同难度的石壁，但是需要你准备好所有攀岩的装备",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "装备我还没有，但是我有想了想，不去攀岩。我决定去看电影。",
#             "assistant": "好的，那我给你推荐几部电影。你喜欢什么类型的电影？",
#             "create_at": 1774493013.6845293
#         },
#         {
#             "user": "你好, 我今天早上吃了一个苹果。",
#             "assistant": "苹果很健康。",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "我要跟你讲，昨天我去练习滑板了，摔了一跤",
#             "assistant": "滑板是很好的运动，但是你有受伤吗？",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "请给我生成一段音乐",
#             "assistant": "[Verse]  新年钟声敲响时，万家灯火映笑颜，  财源滚滚如潮涌，幸福生活乐无边。  \n[Chorus]  恭喜发财万事兴，金银满仓喜盈盈，  心中梦想如星辰，愿望成真皆可行。  \n[Verse]  红包飞舞传祝福，亲朋好友共欢聚，  笑语盈盈声声暖，团圆时刻最珍贵。  \n[Chorus]  恭喜发财好运来，事业腾飞展宏图，  每一个明天都灿烂，幸福生活永不止。  \n[Bridge]  生活如歌节奏快，心中有梦不怕难，  迎接未来每一步，勇敢追逐心中愿。  \n[Outro]  \n[End] https://aimcdn.hapmetasocialltd.com/music/1183083357395746816/b51f75e1.mp3",
#             "create_at": 1774493135.30345
#         }
#     ]
#
#     dialogues1 = [
#         {
#             "user": "我最近喜欢上了一个乐器，是吉他。",
#             "assistant": "吉他是个很容易“越弹越上头”的乐器。它有一种很特别的反馈感：哪怕只学会两个和弦，就已经能弹出一首歌的雏形了。",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "我比较偏向于民谣，喜欢安安静静自弹自唱",
#             "assistant": "那民谣吉他真的很适合你。'一个人安静地弹唱'其实是很多人长期坚持下来的原因——它不像纯技巧型乐器那样总在追求速度，而更像是在整理情绪。刚开始手指会疼。几乎每个吉他手都经历过'按到指尖发麻'的阶段，但通常一两周后会明显好很多。",
#             "create_at": 1774493135.30345
#         },
#         {
#             "user": "是的，手指会痛",
#             "assistant": "这基本算是“新手吉他手认证”了。",
#             "create_at": 1774493135.30345
#         }
#     ]
#
#     history = ""
#     text = json.dumps(dialogues[5:8])
#
#     import asyncio
#     result = asyncio.run(ms.washing_server_llm(
#         text,
#         history
#     ))
#     print(result)
    dic = [{"name": "asf", "age": 23}]
    l = json.dumps(dic)
    print(l, type(l))
