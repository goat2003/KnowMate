"""
Neo4j 连接管理模块

提供单例模式的 Neo4j 异步连接管理器，用于管理数据库连接池、
执行 Cypher 查询、处理事务。
"""

from typing import Optional, Any, Dict, List
from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from neo4j.exceptions import DriverError, Neo4jError, ServiceUnavailable
import logging

from app.common.config.database_conf import neo4j_config

logger = logging.getLogger(__name__)


class Neo4jManager:
    """
    Neo4j 异步连接管理器（单例模式）

    职责:
    1. 管理连接池生命周期
    2. 提供会话创建接口
    3. 执行 Cypher 查询
    4. 处理异常和日志

    """

    _instance: Optional["Neo4jManager"] = None
    _driver: Optional[AsyncDriver] = None

    def __new__(cls) -> "Neo4jManager":
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化连接管理器（只执行一次）"""
        if self._driver is None:
            self._initialize_driver()

    def _initialize_driver(self):
        """初始化 Neo4j 驱动"""
        try:
            self._driver = AsyncGraphDatabase.driver(
                uri=neo4j_config.uri,
                auth=(neo4j_config.username, neo4j_config.password),
                max_connection_lifetime=neo4j_config.max_connection_lifetime,
                max_connection_pool_size=neo4j_config.max_connection_pool_size,
                connection_acquisition_timeout=neo4j_config.connection_acquisition_timeout,
            )

            logger.info(
                f"Neo4j driver initialized: {neo4j_config.uri} "
                f"(pool_size={neo4j_config.max_connection_pool_size})"
            )

        except DriverError as e:
            logger.error(f"Failed to initialize Neo4j driver: {e}")
            raise

    async def verify_connectivity(self) -> bool:
        """
        验证数据库连接是否可用

        Returns:
            bool: 连接可用返回 True，否则返回 False
        """
        try:
            if self._driver is None:
                return False

            await self._driver.verify_connectivity()
            logger.info("Neo4j connectivity verified")
            return True

        except (DriverError, ServiceUnavailable) as e:
            logger.error(f"Neo4j connectivity check failed: {e}")
            return False

    def session(self, database: Optional[str] = None) -> AsyncSession:
        """
        创建一个新的数据库会话

        Args:
            database: 数据库名称，默认使用配置中的默认数据库

        Returns:
            AsyncSession: 异步会话对象

        Raises:
            RuntimeError: 如果驱动未初始化
        """
        if self._driver is None:
            raise RuntimeError("Neo4j driver not initialized")

        db = database or neo4j_config.default_database
        return self._driver.session(database=db)

    async def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行 Cypher 查询并返回结果

        Args:
            query: Cypher 查询语句
            parameters: 查询参数（防止注入）
            database: 数据库名称

        Returns:
            List[Dict[str, Any]]: 查询结果列表

        Raises:
            Neo4jError: 查询执行失败
        """
        async with self.session(database=database) as session:
            try:
                result = await session.run(query, parameters or {})
                records = await result.data()
                logger.debug(f"Query executed: {query[:100]}...")
                return records

            except Neo4jError as e:
                logger.error(f"Query failed: {query[:100]}... Error: {e}")
                raise

    async def execute_write(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行写操作（使用写事务）

        Args:
            query: Cypher 写操作语句
            parameters: 查询参数
            database: 数据库名称

        Returns:
            List[Dict[str, Any]]: 操作结果（如果查询有 RETURN，返回数据；否则返回空列表）

        Raises:
            Neo4jError: 写操作失败
        """
        async with self.session(database=database) as session:
            try:
                result = await session.run(query, parameters or {})
                records = await result.data()
                logger.debug(f"Write executed: {query[:100]}...")
                return records

            except Neo4jError as e:
                logger.error(f"Write operation failed: {query[:100]}... Error: {e}")
                raise

    async def close(self):
        """关闭数据库连接池"""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j driver closed")

    @classmethod
    def get_instance(cls) -> "Neo4jManager":
        """
        获取单例实例

        Returns:
            Neo4jManager: 全局唯一实例
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def __aenter__(self):
        """支持异步上下文管理器"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出时关闭连接"""
        await self.close()


# 全局实例获取函数
async def get_neo4j_manager() -> Neo4jManager:
    """
    获取 Neo4j 管理器实例（用于依赖注入）

    Returns:
        Neo4jManager: 全局唯一实例

    Raises:
        RuntimeError: 如果无法建立连接
    """
    manager = Neo4jManager.get_instance()
    # 验证连接
    if not await manager.verify_connectivity():
        raise RuntimeError("Cannot establish Neo4j connection")
    return manager

