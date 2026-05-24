# 文件作用：
# 本文件是 Python Agent Service 的命令行启动入口。
# 它负责初始化日志、加载配置，并启动 gRPC Server。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的进程入口层，可通过 python server.py 启动。
#
# 主要内容：
# 1. main 函数：配置日志、加载 Settings、调用 serve。
#
# 关键调用关系：
# - 调用 app.config.load_settings。
# - 调用 app.grpc_server.serve。
#
# 初学者阅读建议：
# 这里没有业务处理逻辑；真正的 gRPC 方法在 app/grpc_server.py，真正的 Agent 工作流在 app/workflow/graph.py。
from __future__ import annotations

import logging

from app.config import load_settings
from app.grpc_server import serve


# 函数作用：
# 启动 Python Agent gRPC 服务进程。
#
# 参数说明：
# - 无。
#
# 返回值：
# - 无返回；serve 会阻塞直到服务退出。
#
# 调用关系：
# - 当直接执行 python server.py 时由文件底部的 if __name__ == "__main__" 调用。
def main() -> None:
    # 初始化标准日志格式，方便查看时间、级别、模块名和消息。
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # 加载 config.yaml 和环境变量，得到服务运行配置。
    settings = load_settings()
    # 启动 gRPC Server，等待 GoFrame 后端调用。
    serve(settings)


# Python 入口保护：只有直接运行本文件时才启动服务，被 import 时不会自动启动。
if __name__ == "__main__":
    main()
