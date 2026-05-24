# 文件作用：
# 本文件提供 python -m app.main 形式的启动入口。
# 它复用项目根目录 server.py 中的 main 函数，避免维护两套启动逻辑。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的包入口层。
#
# 主要内容：
# 1. 从 server.py 导入 main。
# 2. 在直接执行时调用 main 启动 gRPC Server。
#
# 关键调用关系：
# - 调用 server.main。
#
# 初学者阅读建议：
# 如果你想理解服务如何启动，请继续阅读 python-agent/server.py 和 app/grpc_server.py。
from __future__ import annotations

from server import main


# Python 入口保护：直接执行该模块时启动服务，被其他模块 import 时不启动。
if __name__ == "__main__":
    main()
