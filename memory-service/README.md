# KnowMate 内部记忆服务

该目录是 KnowMate 项目内的受限 Mem_Pro 适配服务。浏览器不能访问它；Go 后端通过 `MEMORY_SERVICE_TOKEN` 调用 `/memory/retrieve`、`/memory/build`、`/memory/list` 和 `/memory/delete`。默认只绑定 `127.0.0.1:8091`，开发数据保存在 `memory-service/memory.sqlite3`，不写入 `D:\projects\Mem_Pro`。

当前实现提供可重复的本地验收后端。接入真实 Mem_Pro 时，只需替换 `Repository`，保留 role_id 校验、Bearer 鉴权和端点契约；MongoDB、Neo4j、Milvus 的连接状态应由替换后的 repository 在 `/health` 中报告。
