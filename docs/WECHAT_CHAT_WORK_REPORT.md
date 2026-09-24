# 聊天、用户记忆与微信服务号工作报告

日期：2026-09-19。交付范围：单机、单管理员、单后端实例。已实现并在隔离演练环境验证；真实模型和真实公众号未接入。

## 交付结果

打开 `https://localhost:9443`，登录后选择 **与知识助手聊天**。可发送问题、查看异步回复、获取文章推荐、查看记忆来源和删除记忆。管理员可以切换不同的聊天用户。

公众号服务号适配器已完成：安全模式加密回调、身份隔离、持久化去重、异步回复、客服消息发送和窗口检查。微信与网页共用聊天后端；微信用户的偏好按独立身份保存。实际消息发送开关保持关闭。

新增 `Chat` gRPC 契约、Python 聊天模块、Go 聊天 worker、四张 MySQL 表及增量迁移、React 页面、配置模板、接入手册。两个 proto 源文件及 Go/Python 生成代码同步，协议检查包含新 RPC。

## 验收与证据

| 项目 | 实测结果 | 本机记录 |
| --- | --- | --- |
| Go 全量测试、vet、格式和覆盖率门禁 | 通过 | `artifacts/chat-quality.log` |
| Python/MCP 质量门禁 | 133 通过、3 跳过；覆盖率 82.42% | 同上 |
| 聊天专项 Python 测试 | 5 通过，包括空标签文章与真实供应商失败不降级 | `python-agent/tests/test_chat.py` |
| 前端测试和构建 | 12 测试通过，TypeScript/Vite 构建成功 | `artifacts/chat-web-tests.log` |
| 聊天 HTTPS 实测 | 保存、授权关闭、读取偏好、用户隔离、去重、重启持久化、删除后不恢复均通过 | `.local-server/rehearsal/chat-acceptance.json` |
| 实际文章推荐 | 返回两篇已有 Hugging Face 来源文章及链接 | 同上 |
| 微信适配器 + 真实 MySQL | 加密回调、无效签名拒绝、重复回调、模拟推荐发送、额度不重复补充、窗口过期均通过 | `artifacts/chat-db-integration.log` |
| 删除与在途请求 | 删除前排队的消息取消；正在生成的旧版本回复不能恢复记忆 | 同上 |
| 浏览器交互 | 真实后台选择测试用户、Enter 发送、偏好显示、推荐卡片显示 | `output/playwright/` |
| 桌面/手机布局 | 1440×1050、390×844；页面宽度未溢出；浏览器控制台无错误 | 下方截图 |
| 服务健康 | MySQL ok、Agent SERVING，9 个监控目标 up | `artifacts/chat-final-health.log` |
| 密钥扫描、迁移静态检查、协议检查 | 通过 | `artifacts/chat-quality.log` |

质量门禁命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality_gate.ps1 -SkipDocker -SkipIntegration -SkipE2E -SkipVulnerabilityScan
```

另行构建并启动了实际演练镜像，运行 `python -B scripts/chat_acceptance.py`，以及带本机 MySQL 的 `TestLocalDatabaseWechatAndMemory`。数据库专项测试期间只短暂停止 `knowmate-rehearsal` 后端，结束后恢复；合成测试数据按精确用户清理。HTTPS 验收保留 `chat-acceptance-…` 命名用户供查看，未向真实微信发送消息。未运行会截断业务表的通用 smoke 脚本。

本轮修复了实际抓取文章 `tags=null` 导致推荐崩溃的问题；微信发送必须得到明确成功码才标记成功；提交重试保留原始记忆授权；删除记忆后排队和在途消息均受版本保护。推荐理由已改为可读中文。

截图：[桌面](../output/playwright/page-2026-09-19T08-20-49-666Z.png)、[手机输入区域](../output/playwright/page-2026-09-19T08-22-13-559Z.png)。截图和私有验收记录位于忽略目录，不作为公开仓库附件。

## 真实启用仍需提供

1. 真实聊天模型和 embedding 配置，以及供应商兼容性/额度验收；自然语言记忆抽取效果需用真实模型抽样验证。
2. 服务号 AppID、AppSecret、Token、EncodingAESKey，以及该账号相应接口权限。
3. 微信服务器可访问的 HTTPS 回调地址、可信域名证书、按平台要求配置的出口 IP 白名单；目前仅本机访问，未建立公网隧道。
4. 真实服务号收消息、回复、记忆变更和推荐链接的最终联调。

本轮新增微信渠道后，“只填模型 API”不再涵盖微信的账号和网络条件。已完成可离线开发及本机验收部分，不能把模拟微信接口通过等同于真实公众号上线。

暂不包含任意时间/每日主动推送、网页普通用户登录与微信账号绑定、多副本聊天 worker、完整账号数据删除。当前“忘记”清除聊天偏好与旧对话上下文，不清除历史记录或旧反馈画像。详细配置、命令、发送状态和限制见 [微信聊天接入手册](WECHAT_CHAT.md)。

生产环境仅重新渲染了默认关闭的微信配置；原开发环境和其他项目未改动。源码变更保留在工作区，未创建提交、推送或发布。
