from typing import Optional, List, Any

# from bson import ObjectId
from pymongo.collection import Collection
from pymongo.errors import (
    PyMongoError,
    DuplicateKeyError,
    BulkWriteError,
)

from app.common.manager.mongodb_manager import MongoManager


class BaseRepository:

    def __init__(self, collection_name: str):

        self.db = MongoManager.get_db()

        # self.collection: Collection = self.db[
        #     collection_name
        # ]

        # =========================
        # collection helper
        # =========================

    def _get_collection(
            self,
            collection_name: str
    ) -> Collection:
        return self.db[
            collection_name
        ]

    # =========================
    # unique
    # =========================
    # 单个字段唯一
    def create_unique_index(
            self,
            collection_name: str,
            index: str
    ):

        collection = self._get_collection(
            collection_name
        )
        # 联合唯一
        # 示例：
        # collection.create_index(
        #     [("user_id", 1), ("post_id", 1)],
        #     unique=True
        # )
        collection.create_index(
            index,
            unique=True,
            sparse=True  # 只有存在指定字段的数据才参与唯一性校验
        )

    # 联合唯一
    def create_unique_indexes(
            self,
            collection_name: str,
            index: List[tuple[str, int]]
    ):

        collection = self._get_collection(
            collection_name
        )
        # 示例：
        # collection.create_index(
        #     [("user_id", 1), ("post_id", 1)],
        #     unique=True
        # )
        collection.create_index(
            index,
            unique=True,
            sparse=True  # 只有存在指定字段的数据才参与唯一性校验
        )


    # =========================
    # insert
    # =========================
    # 插入一条数据：dict
    def insert_one(self, collection_name: str, data: dict) -> str:


        collection = self._get_collection(
            collection_name
        )
        try:
            result = collection.insert_one(data)
            return str(result.inserted_id)

        except DuplicateKeyError:
            return "message: 数据已存在"

        except PyMongoError as e:
            return f"message: mongo error: {e}"



    # 插入多条数据：List[dict]
    def insert_many(self, collection_name: str, data: List[dict]):


        collection = self._get_collection(
            collection_name
        )
        if not data:
            return {
                "success": False,
                "message": "empty data"
            }

        try:

            result = collection.insert_many(
                data,
                ordered=False
            )

            return {
                "success": True,
                "inserted_ids": [
                    str(_id)
                    for _id in result.inserted_ids
                ]
            }

        except BulkWriteError as e:

            # 提取真正成功插入的数据数量
            inserted_count = e.details.get("nInserted", 0)

            return {
                "success": False,
                "message": "部分数据重复，重复数据已跳过",
                "inserted_count": inserted_count
            }

        except PyMongoError as e:

            return {
                "success": False,
                "message": f"mongo error: {e}"
            }

    # =========================
    # Read - query
    # =========================
    # 查询一条
    def query_one(
            self,
            query: dict,
            collection_name: str,
            projection: Optional[dict] = None  # 控制查询结果里返回哪些字段。
    ):

        collection = self._get_collection(
            collection_name
        )

        result = collection.find_one(
            query,
            projection
        )

        return self._serialize(result)

    # projection = {
    #         "name": 1,
    #         "email": 1
    #     }
    # 输出：
    # {
    #     "_id": ObjectId("xxx"),
    #     "name": "Tom",
    #     "email": "tom@test.com"
    # }

    # 查询多条
    def query_many(
            self,
            query: dict,
            collection_name: str,
            projection: Optional[dict] = None,
            skip: int = 0,   # 当查询量很大的时候，分批查询。skip 就是当前位置已查询过的数据数目
            limit: int = 0,  # 每个批次的查询量
            sort: Optional[list[tuple[str, int]]] = None,
    ):

        collection = self._get_collection(
            collection_name
        )
        cursor = collection.find(
            query,
            projection
        )

        # 排序
        if sort:
            cursor = cursor.sort(sort)

        # 分页
        if skip:
            cursor = cursor.skip(skip)

        if limit:
            cursor = cursor.limit(limit)

        return [
            self._serialize(item)
            for item in cursor
        ]

    # =========================
    # Update
    # =========================

    def update_one(
            self,
            collection_name: str,
            query: dict,
            data: dict
    ) -> int:

        collection = self._get_collection(
            collection_name
        )

        result = collection.update_one(
            query,
            {
                "$set": data
            }
        )

        return result.modified_count

    # =========================
    # Delete
    # =========================

    def delete_one(self, collection_name: str, query: dict) -> int:

        collection = self._get_collection(
            collection_name
        )
        result = collection.delete_one(query)

        return result.deleted_count

    def delete_many(self, collection_name: str, query: dict) -> int:


        collection = self._get_collection(
            collection_name
        )
        result = collection.delete_many(query)

        return result.deleted_count

    # =========================
    # Utils
    # =========================

    @staticmethod
    def _serialize(data):

        if not data:
            return None

        data["_id"] = str(data["_id"])

        return data