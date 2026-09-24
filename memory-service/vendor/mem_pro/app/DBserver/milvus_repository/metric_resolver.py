import app.common.config.parameters_config as config

# 统一注册不同 collection 的 metric_type
class MetricTypeResolver:
    """
    collection_name -> metric_type 的注册中心
    """

    # ====== 静态注册表（你当前业务规则就在这里）======
    _registry = {
        "ori_fact_schema": {
            "metric": "L2",
            "threshold": config.W1
        },
        "dev_fact_schema": {
            "metric": "L2",
            "threshold": config.W1
        },
        "SemanticEntity": {
            "metric": "COSINE",
            "threshold": config.W3
        },
    }

    _default = {
        "metric": "L2",
        "threshold": config.W1
    }

    @classmethod
    def register(cls, collection_name: str, metric: str, threshold=None):
        """
        动态新增 / 覆盖规则
        """
        cls._registry[collection_name] = {
            "metric": metric,
            "threshold": threshold if threshold is not None else cls._default["threshold"]
        }

    @classmethod
    def unregister(cls, collection_name: str):
        """
        删除规则
        """
        cls._registry.pop(collection_name, None)

    @classmethod
    def resolve(cls, collection_name: str) -> dict:
        """
        核心入口：获取 metric policy
        """
        return cls._registry.get(collection_name, cls._default)
