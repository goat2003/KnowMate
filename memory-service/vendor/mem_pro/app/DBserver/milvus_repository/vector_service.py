from pymilvus import Collection, utility, db
import logging

from app.common.client.milvus_client import MilvusClient
from app.common.config.database_conf import milvus_config
from app.DBserver.milvus_repository.milvus_schemas import COLLECTION_REGISTRY
from app.DBserver.milvus_repository.metric_resolver import MetricTypeResolver
from app.common.manager.milvus_manager import MilvusManager

logger = logging.getLogger(__name__)

class MilvusInitializer:
    """
    统一负责 Milvus 初始化：
    - collection 创建
    - schema 初始化
    - index 创建
    - load
    """

    # =========================
    # 1. 外部入口（唯一入口）
    # =========================
    @staticmethod
    def init_collections():
        """
        幂等初始化所有 collections
        """

        # 保证 Milvus 已连接（第一次会 connect，以后不会）
        MilvusManager()

        # 切换数据库（虽然 MilvusManager 已经切过，再调用一次也没有问题）
        if milvus_config.db_name != "default":
            db.using_database(milvus_config.db_name)

        for collection_name in COLLECTION_REGISTRY.keys():
            schema_factory, _ = COLLECTION_REGISTRY[collection_name]

            MilvusInitializer._create_collection_if_not_exists(
                collection_name,
                schema_factory()
            )

    # =========================
    # 2. 创建 collection（核心）
    # =========================
    @staticmethod
    def _create_collection_if_not_exists(name: str, schema):
        try:
            if utility.has_collection(name):
                logger.info(f"[SKIP] Collection exists: {name}")
                collection = Collection(name)
                MilvusInitializer._ensure_loaded(collection)
                return collection

            collection = Collection(
                name=name,
                schema=schema,
                using="default"
            )

            logger.info(f"[CREATE] Collection created: {name}")

            MilvusInitializer._create_indexes(name, collection)
            MilvusInitializer._ensure_loaded(collection)

            return collection

        except Exception as e:
            logger.error(f"Create collection failed: {name}, error: {e}")
            raise

    # =========================
    # 3. index 创建（关键逻辑）
    # =========================
    @staticmethod
    def _create_indexes(collection_name: str, collection: Collection):
        """
        根据 registry 自动创建所有 vector field index
        """

        _, vector_fields = COLLECTION_REGISTRY[collection_name]

        policy = MetricTypeResolver.resolve(collection_name)
        metric_type = policy["metric"]

        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": metric_type,
            "params": {"nlist": 128}
        }

        existing_indexes = collection.indexes or []
        existing_fields = set()

        for idx in existing_indexes:
            if hasattr(idx, "field_name"):
                existing_fields.add(idx.field_name)

        for field in vector_fields:
            if field in existing_fields:
                logger.info(f"[INDEX SKIP] exists: {collection_name}.{field}")
                continue

            try:
                collection.create_index(
                    field_name=field,
                    index_params=index_params
                )
                logger.info(
                    f"[INDEX CREATE] {collection_name}.{field} -> {metric_type}"
                )

            except Exception as e:
                logger.warning(
                    f"[INDEX FAIL] {collection_name}.{field} err={e}"
                )

    # =========================
    # 4. load（统一入口）
    # =========================
    @staticmethod
    def _ensure_loaded(collection: Collection):
        """
        确保 collection 可查询
        """
        try:
            collection.load()
            logger.info(f"[LOAD] Collection loaded: {collection.name}")
        except Exception as e:
            logger.warning(f"[LOAD SKIP] {collection.name}: {e}")

    # =========================
    # 5. （可选）单表初始化
    # =========================
    @staticmethod
    def init_single_collection(collection_name: str):
        """
        用于动态扩展 schema
        """

        if collection_name not in COLLECTION_REGISTRY:
            raise ValueError(f"Unknown collection: {collection_name}")

        schema_factory, _ = COLLECTION_REGISTRY[collection_name]

        MilvusInitializer._create_collection_if_not_exists(
            collection_name,
            schema_factory()
        )