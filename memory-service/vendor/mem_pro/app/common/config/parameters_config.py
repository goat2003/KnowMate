"""
该文件单独用于项目中所有参数

"""

"""
fact 层
"""

# chunk_summary_embedding - ori_fact_embedding 向量匹配
# 派生的内容与已有的 dev_fact_embedding 向量匹配
# L2 欧式距离 临界值
W1 = 0.5

# 实体节点的向量匹配  Cosine 计算相似度
W3 = 0.5

# 生成用户画像时，获取重要事件，ori_fact importance 的临界值
W_IMPORTANCE = 0.75
W_CONFIDENCE = 0.25

# 用于判定 dev_fact 节点的稳定的临界值
DEV_CONFIDENCE = 10