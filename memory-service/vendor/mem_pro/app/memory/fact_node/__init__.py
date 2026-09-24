"""fact_node 包初始化。

这里不主动导入 FactGraphService，避免 package import 时把整条
service/repository 依赖链提前拉起，增加测试收集和局部模块调试时的耦合。
"""

__all__: list[str] = []
