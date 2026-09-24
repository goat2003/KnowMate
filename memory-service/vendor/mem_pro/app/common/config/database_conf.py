from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from pathlib import Path

# 获取项目根目录（.env 文件所在位置）
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Neo4jConfig(BaseSettings):
    """Neo4j 数据库配置"""

    # 连接参数
    uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j 连接 URI"
    )

    username: str = Field(
        default="neo4j",
        description="数据库用户名"
    )

    password: str = Field(
        default="password",
        description="数据库密码"
    )

    # 连接池配置
    max_connection_lifetime: int = Field(
        default=3600,
        description="连接最大存活时间（秒）"
    )

    max_connection_pool_size: int = Field(
        default=50,
        description="连接池最大连接数"
    )

    connection_acquisition_timeout: int = Field(
        default=60,
        description="获取连接超时时间（秒）"
    )

    default_database: str = Field(
        default="neo4j",
        description="默认数据库名称"
    )

    model_config = SettingsConfigDict(
        env_prefix="NEO4J_",
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )



neo4j_config = Neo4jConfig()


class MilvusConfig(BaseSettings):
    """Milvus 数据库配置"""

    host: str = Field(
        default="localhost",
        description="Milvus 主机地址"
    )

    port: str = Field(
        default="19530",
        description="Milvus 端口"
    )

    db_name: str = Field(
        default="superCog_multi_2",
        description="Milvus 数据库名称"
    )

    timeout: float = Field(
        default=30.0,
        description="连接超时时间（秒）"
    )

    model_config = SettingsConfigDict(
        env_prefix="MILVUS_",
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )


milvus_config = MilvusConfig()

class MongoConfig(BaseSettings):
    # 连接参数
    uri: str = Field(
        default="mongodb://localhost:27017/",
        description="MongoDB 连接 URI"
    )

    db_name: str = Field(
        default="test_database_multi_2",
        description="数据库默认名"
    )

    collection_name: str = Field(
        default="user_profile_collection",
        description="用户画像集合默认名"
    )

    entity_collection_name: str = Field(
        default="session_entity_maps",
        description="实体对应集合默认名"
    )


    model_config = SettingsConfigDict(
        env_prefix="MONGODB_",
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )

mongodb_config = MongoConfig()


if __name__ == "__main__":
    print("NOE4J: ", neo4j_config.password)
    print("MILVUS: ", milvus_config.host)
    print("MONGODB: ", mongodb_config.uri)
