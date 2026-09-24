"""
用作 问卷回答的测试
1. 判定用户是否已完成该问卷
2. 用户回答存入 mongodb
3. 从 mongodb 获取回答 生成用户基础画像写入 neo4j

mongodb数据库字段
role_id
questionnaire_id
user_response
status
create_time
"""

from app.questionnaire.profile_Q_A.questionnaire import *
from app.questionnaire.questionnaire_server.profile_init_server import ProfileInitServer
from app.DBserver.mongoDB_repository.mongoDB_repository import BaseRepository
from datetime import datetime
from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore
from app.memory.tools_service import ToolService
import json

class QuestionnaireMain():
    def __init__(self):
        self.profile_init_server = ProfileInitServer()
        self.questionnaire_repo = BaseRepository(
            "questionnaire"
        )
        self.profile_repo = BaseRepository(
            "profile"
        )
        self.user_info_store = UserInfoStore()
        self.tool_service = ToolService()
        # 连接数据库 设置 唯一性index
        # questionnaire 唯一索引
        index_questionnaire = [
            ("role_id", 1),
            ("questionnaire_id", 1),
        ]

        self.questionnaire_repo.create_unique_indexes("questionnaire", index_questionnaire)

        # profile 唯一索引
        index_profile = "role_id"

        self.profile_repo.create_unique_index("profile", index_profile)


    # 用户画像问卷回答存入mongodb
    # collection_name = "questionnaire"
    def save_in_mongo(self, role_id:str, questionnaire_id:str, collection_name = "questionnaire"):
        # =========== 1. 判定用户是否已完成该问卷 ========
        # status = 0 或者 数据库压根不存在该用户的此问卷的回答
        query = {"role_id": role_id, "questionnaire_id": questionnaire_id}
        projection = {"info":1}
        query_result = self.questionnaire_repo.query_one(
            query,
            collection_name,
            projection
        )

        print("query_result:", query_result)
        print(type(query_result))

        # 若 query_result 为空   不存在，建立
        if not query_result:
            # 没有信息，用户完成问卷并存进 mongodb
            response = run_questionnaire(
                "app/questionnaire/profile_Q_A/questions01.json",
                "app/questionnaire/profile_Q_A/user_response.json",
                role_id
            )

            # 若response啥都没得，则不执行存入操作
            if not response:
                return

            s = json.dumps(response, ensure_ascii=False)
            print(type(s))

            # =========== 2. 用户回答存入 mongodb ========
            data = {
                "role_id": role_id,
                "questionnaire_id": questionnaire_id,
                "info": response,
                "create_time": datetime.now()
            }
            self.questionnaire_repo.insert_one(collection_name, data)

        # 若 不为空， print("请勿重复作答")
        else:
            # 该用户已完成此问卷 并且 mongodb 已有相关信息
            print("已存在, 勿重复作答")
            return


    # =========== 3. 从 mongodb 获取回答 生成用户基础画像写入 neo4j ========
    async def write_in_neo4j(self, questionnaire_id:str, start_time:datetime, end_time:datetime, collection_name = "questionnaire"):
        # 根据 questionnaire_id 和 time_range 获取所有满足条件的数据

        # query 根据时间查询
        # start_time = datetime(2026, 5, 14, 0, 0, 0)
        # end_time = datetime(2026, 5, 15, 0, 0, 0)

        query = {
            "create_time": {
                "$gte": start_time,
                "$lt": end_time
            },
            "questionnaire_id": questionnaire_id
        }
        result = self.questionnaire_repo.query_many(
            query,
            collection_name,
            # projection: 只获取 info 的信息
            projection={
                "info": 1
            }
        )
        print("questionnaire result: ", result)

        if result:
            # llm 解析
            for user_response in result:
                print("user_response:", user_response)
                print(type(user_response))
                response = user_response["info"]
                role_id = response["role_id"]
                print("role_id:", role_id)
                llm_result = await self.profile_init_server.merge_profile(response)
                # 写进节点
                print("写进节点")
                await self.user_info_store.upsert_user_info(role_id, llm_result)


    # 测试用
    async def main(
            self,
            role_id: str,
            questionnaire_id: str,
    ):
        # ============= Step 1 问卷 + mongodb =============
        print("Step 1: 问卷 + mongodb")
        self.save_in_mongo(
            role_id,
            questionnaire_id
        )

        # ========== Step 2: mongodb 读取信息 + user_info_node ============
        print("Step 2: mongodb 读取信息 + user_info_node")
        # 获取时间区间
        # _pre 测试用，获取当天时间范围
        time_range = self.tool_service.get_year_month_day_pre()
        start_time = time_range["start_time"]
        end_time = time_range["end_time"]
        await self.write_in_neo4j(
            questionnaire_id,
            start_time,
            end_time
        )


if __name__ == "__main__":
    scripts = QuestionnaireMain()

    role_ids = ["1", "2", "3", "4"]
    # role_id = "1"
    questionnaire_id = "NSDF"
    # for role_id in role_ids:
    #     scripts.save_in_mongo(role_id, questionnaire_id)

    import asyncio

    role_id = "conv-91"
    # query 根据时间查询
    time_range = scripts.tool_service.get_year_month_day_pre()
    asyncio.run(scripts.main(role_id, questionnaire_id))