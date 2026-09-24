from pymilvus import connections, db
from app.common.config.database_conf import milvus_config
import logging

logger = logging.getLogger(__name__)

class MilvusClient:
    _connected = False

    @classmethod
    def connect(cls):
        if cls._connected:
            db.using_database(milvus_config.db_name)
            return

        try:
            connections.connect(
                alias="default",
                host=milvus_config.host,
                port=milvus_config.port,
                timeout=milvus_config.timeout,
            )

            # ✅ 切换数据库（关键）
            db.using_database(milvus_config.db_name)

            cls._connected = True
            logger.info(
                f"Milvus connected: {milvus_config.host}:{milvus_config.port}"
            )
            print("connect success")

            # 可选：检查数据库是否存在
            # cls._ensure_database()

        except Exception as e:
            logger.error(f"Milvus connection failed: {e}")
            raise

    @classmethod
    def disconnect(cls):
        connections.disconnect("default")
        cls._connected = False

if __name__ == "__main__":
    mc = MilvusClient()
    mc.connect()
