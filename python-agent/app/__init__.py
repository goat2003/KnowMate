# 文件作用：
# 本文件标记 app 目录是 Python 包，并声明包级别对外模块。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 app 包入口。
#
# 主要内容：
# 1. __all__：声明 config、grpc_server 是包级别公开模块。
#
# 关键调用关系：
# - Python 导入系统会在 import app 时加载本文件。
#
# 初学者阅读建议：
# 这里没有业务逻辑；服务启动请看 server.py，gRPC 实现请看 app/grpc_server.py。
# __all__ 控制 from app import * 时导出的模块名。
__all__ = ["config", "grpc_server"]
