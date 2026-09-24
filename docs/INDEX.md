# 项目文档入口

这里区分当前操作依据、架构说明和历史证据，避免把一次性工作报告当成现役配置。

## 当前依据

- [README](../README.md)：项目范围、模块和基础启动方式。
- [ARCHITECTURE](../ARCHITECTURE.md)：服务边界与调用关系。
- [OPERATIONS](../OPERATIONS.md)：通用运维和生产 Compose。
- [SECURITY](../SECURITY.md)：安全约束。
- [配置文件边界](../configs/env/README.md)：环境模板的唯一用途。
- [微信聊天接入](WECHAT_CHAT.md)：网页 OAuth、服务号回调和用户 API 合同。
- [本机服务器手册](LOCAL_SERVER.md)：本机阶段的启动、备份和恢复。
- [项目进度](../项目进度.md)：当前已完成项、启动方式和未完成条件。

## 当前限制与发布检查

- [已知限制](../KNOWN_LIMITATIONS.md)
- [下一版本规划](../NEXT_VERSION_PLAN.md)
- [发布检查清单](../RELEASE_CHECKLIST.md)

## 历史证据

`*_WORK_REPORT.md` 是特定日期的验收记录，不是当前运行状态；运行前必须重新检查
配置、镜像和服务。`docs/superpowers/` 下的 plans/specs 是设计历史，不能替代当前代码
和配置。中文镜像入口见 [docs/zh-CN/INDEX.md](zh-CN/INDEX.md)。
