"""
构建系统 最终执行文件

流程：
问卷回答 + 写进 mongodb
      ↓
从 mongodb 获取回答 + 写入 user_info 节点 (此过程包括节点创建)
      ↓
执行 chunk 节点创建
      ↓
执行 fact 节点创建
"""


import os
import sys
import json
import time

# 允许直接通过 `python main/main_questionnaire.py` 从项目根目录运行。
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory.chunk_node.chunk_server.chunk_service import ChunkService
from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore
from app.memory.chunk_node.chunk_graph.chunk_store import ChunkStore
from app.questionnaire.questionnaire_server.profile_init_server import ProfileInitServer
from app.memory.tools_service import ToolService
# from app.memory.fact_node.fact_service.fact_graph_service import FactGraphService
from main.main_questionnaire import QuestionnaireMain
from app.extra_user_profile.profile_search import ProfileSearch
from main.fact_main import FactMain
import app.common.indexing.db_initializer as db_init


class BuildMain:
    def __init__(self):
        self.questionnaire_main = QuestionnaireMain()
        self.fact_main = FactMain()
        self.chunk_service = ChunkService()
        self.user_info_store = UserInfoStore()
        self.chunk_store = ChunkStore()
        self.pro_init = ProfileInitServer()
        # self.fact_graph_service = FactGraphService()
        self.tool_service = ToolService()

    async def init_(self):
        await self.user_info_store.uniq_user_info()
        # await self.chunk_store.uniq_chunk()
        await db_init.init_all_schema()

    # 纯对话构建记忆系统
    async def main(
            self,
            role_id: str,
            # questionnaire_id: str,
            dialogues: list,
            split: int,
            target_object: str   # 主要分析对象，正式上线后 target_object = role_id
    ):
        await self.init_()
        target_object = target_object or role_id

        # ============= Step 1 获取role_id 创建 user_info 节点 =============
        # ============= user_info 已存在则跳过 ===============
        print("Step 1: 创建 user_info 节点 或 跳过")
        get_user_node = await self.user_info_store.query_by_role_id(role_id)
        if get_user_node is None:
            info_dict = {
                "basic_info": "",
                "preference": "",
                "skill": ""
            }
            await self.user_info_store.create_user_info(
                role_id=role_id,
                info_dict = info_dict
            )


        # ============ Step 2: 创建 chunk 节点 =============
        print("Step 2: 创建 chunk 节点")
        chunk_uuids = await self.chunk_service.create_all_chunks(role_id, dialogues, split, target_object)
        print(chunk_uuids)
        if not chunk_uuids:
            print("未创建任何 chunk，请检查对话内容")
            return
        print("how many chunk uuid: ", len(chunk_uuids))
        print(chunk_uuids)


        # ============== Step3: 创建 fact 节点 ============
        print("Step 3: 创建 fact 节点")
        for chunk_uuid in chunk_uuids:
            print("chunk_uuid: ", chunk_uuid)
            await self.fact_main.main(role_id, chunk_uuid, target_object)


class ProfileMain:
    def __init__(self):
        self.profile_search = ProfileSearch()
        self.questionnaire_main = QuestionnaireMain()

    # 生成用户画像段落  基础信息、偏好、技能和重要事件
    # 存入 mongodb 或更新 mongodb
    async def insert_or_update_profile(self, role_id: str, collection_name = "profile"):
        response = json.loads(await self.profile_search.generate_profile_phase(role_id))
        print(response)
        print(type(response))

        # 判断 mongodb 中是否存在该 role_id 的画像
        query = {"role_id": role_id}
        projection = None
        exist = self.questionnaire_main.questionnaire_repo.query_one(
            query, collection_name, projection)
        if exist:   # 存在即更新
            print("1")
            self.questionnaire_main.questionnaire_repo.update_one(
                collection_name,
                query,
                response
            )

        else:    # 不存在结果存入 mongodb
            print("2")
            data = {"role_id": role_id} | response
            print("data: ", data)
            self.questionnaire_main.questionnaire_repo.insert_one(collection_name, data)


    # 给信息检索提供 user_info 用户画像
    async def profile_for_retrieval(self, role_id:str, collection_name = "profile"):
        query = {"role_id": role_id}
        projection = {
                    "user_info": 1
                }
        info = self.questionnaire_main.questionnaire_repo.query_one(
            query, collection_name, projection)

        return info["user_info"]


    # 给接口提供用户画像
    async def profile_for_interface(self, role_id:str, collection_name = "profile"):
        query = {"role_id": role_id}
        projection = {
                    "user_info": 1,
                    "important_events": 1
                }
        info = self.questionnaire_main.questionnaire_repo.query_one(
            query, collection_name, projection)

        return info["user_info"]+info["important_events"]

    async def main(self, role_id:str, collection_name = "profile"):
        await self.insert_or_update_profile(role_id)
        print(await self.profile_for_retrieval(role_id, collection_name))
        print(await self.profile_for_interface(role_id, collection_name))

if __name__ == "__main__":
    bm = BuildMain()
    pm = ProfileMain()

    # role_id = "mock_user_001"
    questionnaire_id = "NSDF"
    split = 3


    import asyncio
    # =========== step 1 测试问卷写入 user_info ============
    scripts = bm.questionnaire_main
    # asyncio.run(scripts.main(role_id, questionnaire_id))

    # =========== step 2 对话构建记忆框架 ============
    from data.transform import *

    # file_path1 = "data/mock_dialogue1.json"
    # dialogues1 = load_conversations(file_path1)
    # file_path2 = "data/mock_dialogue2.json"
    # dialogues2 = load_conversations(file_path2)
    #
    # dialogues = dialogues1 + dialogues2
    # print("dialogues2: ", dialogues)
    # print(type(dialogues))


    # role_id = "conv-91"
    # target_object = role_id

    file_path = "data/output/user1_couple.json"
    dialogues = load_conversations(file_path)
    print(len(dialogues))

    role_id = "conv-01"
    target_object = "user"

    start = time.time()
    result = asyncio.run(bm.main(role_id, dialogues, split, target_object))

    end = time.time()
    print(end - start)
    # =========== step 3 获取用户画像描述 ===========
    # asyncio.run(pm.insert_or_update_profile(role_id))
