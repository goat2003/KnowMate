# KnowMate 内部长期记忆服务

KnowMate 通过 Go 适配层调用项目内的 `memory-service`，浏览器不会直接访问该服务。默认监听 `127.0.0.1:8091`，只接受 `Authorization: Bearer <MEMORY_SERVICE_TOKEN>`，并且只接受 `km_<40 位十六进制字符>` role_id。role_id 由 Go 后端使用 `MEMORY_ROLE_SECRET` 对当前后端会话用户 HMAC 派生。

## 本地启动

在项目根目录执行：

```powershell
$env:MEMORY_SERVICE_TOKEN = "仅保存在本机的随机值"
$env:MEMORY_ROLE_SECRET = "至少 32 字节的本机随机值"
.\scripts\start_memory_service.ps1
```

另一个终端配置 Go 后端（`MEMORY_ROLE_SECRET` 至少 32 字节，Go 适配层会拒绝更短的值）：

```powershell
$env:MEMORY_PROVIDER_URL = "http://127.0.0.1:8091"
$env:MEMORY_PROVIDER_TOKEN = $env:MEMORY_SERVICE_TOKEN
$env:MEMORY_ROLE_SECRET = "与服务启动时相同的值"
```

服务端点只有 `/health`、`/memory/retrieve`、`/memory/build`、`/memory/list` 和 `/memory/delete`。列表和删除操作始终按后端派生的 role_id 执行。检索和列表使用短超时；记忆构建使用 MEMORY_PROVIDER_BUILD_TIMEOUT_SECONDS（默认 180 秒），聊天回复先持久化，构建在后台更新 pending/saved/unavailable 状态。

当前项目内适配服务提供可验收的本地持久化实现；`/health` 会明确报告 MongoDB、Neo4j、Milvus 为 `not-configured`。因此在这三个依赖和真实模型接入前，不能宣称完成完整 Mem_Pro 多存储验收。替换 `Repository` 时保留同一鉴权和 role_id 契约，并让健康状态反映真实依赖。

## 真实 Mem_Pro 模式

项目内 `memory-service/vendor/mem_pro` 是从原工作树复制的只读运行源码，原 `D:\projects\Mem_Pro` 不会被服务导入或修改。设置 `MEMORY_BACKEND=mem_pro` 后，服务会调用复制的 `BuildMain` 和 `RetrievalService`，并通过 `role_id` 访问 MongoDB、Neo4j、Milvus；MongoDB、Neo4j、Milvus 和模型/embedding 均必须可用，健康检查会返回 `503` 直到全部依赖就绪。

真实模式只支持按 role 清空记忆；Mem_Pro 原生没有安全的单条语义事实删除合约，因此单条删除会明确失败，不会伪装成功。删除全部记忆会对 MongoDB 各集合、Neo4j 节点和 Milvus collection 使用当前 role_id 条件。
