from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError
from typing import Any
import time

from app.common.config.database_conf import mongodb_config


class MongoManager:
    # _client = None
    # _db = None
    _client: MongoClient | None = None
    _db: Database[Any] | None = None

    @classmethod
    def connect(cls, retry_times: int = 5, retry_interval: int = 5):
        """
        初始化 MongoDB 连接池（带重试机制）
        """

        if cls._client:
            return

        last_error = None

        for attempt in range(1, retry_times + 1):
            try:
                print(f"[MongoDB] connection attempt {attempt}/{retry_times}")

                cls._client = MongoClient(
                    mongodb_config.uri,

                    maxPoolSize=50,
                    minPoolSize=5,

                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=10000,
                    socketTimeoutMS=10000,

                    retryWrites=True,
                    retryReads=True,

                    heartbeatFrequencyMS=10000,
                    waitQueueTimeoutMS=10000,
                )

                cls._db = cls._client[mongodb_config.db_name]

                # 强制触发连接检查
                cls._client.admin.command("ping")

                print("MongoDB connected successfully")
                return

            except PyMongoError as e:
                last_error = e
                print(f"[MongoDB] connection failed: {e}")

                # 清理失败连接
                cls._client = None
                cls._db = None

                if attempt < retry_times:
                    time.sleep(retry_interval)

        raise RuntimeError(
            f"MongoDB connection failed after {retry_times} retries: {last_error}"
        )

    """connect 无重试机制"""
    # def connect(cls):
    #     """
    #     初始化 MongoDB 连接池
    #     """
    #
    #     if cls._client:
    #         return
    #
    #     try:
    #         cls._client = MongoClient(
    #             mongodb_config.uri,
    #
    #             # 连接池
    #             maxPoolSize=50,
    #             minPoolSize=5,
    #
    #             # 超时
    #             serverSelectionTimeoutMS=5000,
    #             connectTimeoutMS=10000,
    #             socketTimeoutMS=10000,
    #
    #             # 自动重试
    #             retryWrites=True,
    #             retryReads=True,
    #
    #             # 心跳
    #             heartbeatFrequencyMS=10000,
    #
    #             # 等待队列
    #             waitQueueTimeoutMS=10000,
    #         )
    #
    #         cls._db = cls._client[mongodb_config.db_name]
    #
    #         # 健康检查
    #         cls._client.admin.command("ping")
    #
    #         print("MongoDB connected")
    #
    #     except PyMongoError as e:
    #         raise RuntimeError(
    #             f"MongoDB connection failed: {e}"
    #         )

    @classmethod
    def get_db(cls) -> Database:
        if cls._db is None:
            cls.connect()

        return cls._db

    @classmethod
    def get_collection(cls, name: str):

        db = cls.get_db()

        return db[name]

    @classmethod
    def close(cls):
        if cls._client:
            cls._client.close()

            cls._client = None
            cls._db = None

            print("MongoDB closed")