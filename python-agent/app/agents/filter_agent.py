# 文件作用：
# 本文件实现文章筛选 Agent，负责判断 GoFrame 抓取到的文章是否值得继续总结和改写。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 层，是 ArticleWorkflow 文章处理链路的第一个节点。
#
# 主要内容：
# 1. FilterAgent 类：读取文章、用户画像和 MCP 策略，输出 article_results 初始结果。
# 2. run 方法：执行正文补全、画像上下文读取、embedding、Milvus 相似记忆检索和规则评分。
# 3. _score_article 方法：使用本地规则计算文章基础相关性分数。
# 4. _profile_keywords 方法：从 user_profile_snapshot 中提取兴趣关键词。
#
# 关键调用关系：
# - 被 ArticleWorkflow 的 LangGraph 或顺序流程调用。
# - 可调用 FetchClient、EmbeddingClient、MilvusClient、Neo4jClient。
# - 输出的 article_results 会继续传给 SummaryAgent、RewriteAgent 和 CheckAgent。
#
# 初学者阅读建议：
# 先看 run 方法中 state 的读取和 article_results 的构造，
# 再理解 MCP Client 只在 mcp_policy 允许且对应 client 存在时才会被调用。
from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict
from app.mcp.embedding_client import EmbeddingClient
from app.mcp.fetch_client import FetchClient
from app.mcp.milvus_client import MilvusClient
from app.mcp.neo4j_client import Neo4jClient


# 类作用：
# FilterAgent 负责文章流程的“入口筛选”。
# 它把原始文章转换成 article_results 中的标准结果项，并决定每篇文章的 keep、score 和 filter_reasons。
class FilterAgent(BaseAgent):
    # name 会写入 MCP 调用日志，也会被 MCPPolicy 用来判断当前 Agent 是否有权调用某个工具。
    name = "filter"

    # 函数作用：
    # 初始化筛选 Agent 及其可选 MCP Client。
    #
    # 参数说明：
    # - skill_text：筛选技能文本，目前本类主要用规则和 MCP 上下文筛选，保留该字段便于后续扩展。
    # - embedding_client：用于把文章标题和正文转换为向量。
    # - fetch_client：用于在文章缺少 raw_text 时按 URL 拉取网页内容。
    # - milvus_client：用于根据向量查找相似记忆或相关文章。
    # - neo4j_client：用于读取用户兴趣图谱上下文。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(
        self,
        skill_text: str = "",
        embedding_client: EmbeddingClient | None = None,
        fetch_client: FetchClient | None = None,
        milvus_client: MilvusClient | None = None,
        neo4j_client: Neo4jClient | None = None,
    ) -> None:
        # super() 调用父类初始化逻辑，保存 skill_text，避免每个 Agent 重复写同样代码。
        super().__init__(skill_text)
        # 保存各类 MCP Client；它们可能为 None，便于测试时只使用本地规则。
        self.embedding_client = embedding_client
        self.fetch_client = fetch_client
        self.milvus_client = milvus_client
        self.neo4j_client = neo4j_client

    # 函数作用：
    # 执行文章筛选流程，为每篇文章生成初始处理结果。
    #
    # 参数说明：
    # - state：包含 run_id、articles、user_profile_snapshot、mcp_policy 的工作流状态。
    #
    # 返回值：
    # - 返回写入 article_results 后的 state。
    #
    # 调用关系：
    # - 被 ArticleWorkflow 的文章 LangGraph 或顺序兜底流程调用。
    # - 内部可能调用 fetch-mcp、embedding-mcp、milvus-mcp、neo4j-mcp。
    def run(self, state: JsonDict) -> JsonDict:
        # run_id 用于把本次 Agent 产生的 MCP 调用日志关联到同一次任务。
        run_id = str(state.get("run_id", ""))
        # 用户画像快照包含兴趣、主题、关键词等字段，筛选时用来提高相关性文章的分数。
        profile = state.get("user_profile_snapshot", {})
        # mcp_policy 决定本次运行是否启用 fetch、embedding、milvus、neo4j 等外部能力。
        policy = state.get("mcp_policy", {})
        # article_results 会保存每篇文章的筛选结果，并作为后续 Agent 的输入。
        article_results = []
        # 遍历标准化后的文章列表；每篇文章独立产生一个 result。
        for article in state.get("articles", []):
            # logs 只保存当前文章产生的 MCP 调用日志，最后放入该文章 result。
            logs: list[JsonDict] = []
            # 如果允许 fetch、文章没有正文、文章有 URL 且 fetch_client 存在，就尝试补全文本。
            # 这样 RSS 只给标题或摘要时，后续 LLM 仍然有更多上下文。
            if policy.get("enable_fetch") and not article.get("raw_text") and article.get("url") and self.fetch_client:
                fetched = self.fetch_client.fetch_url(article["url"], agent_name=self.name, run_id=run_id)
                # fetched.log 是 BaseMcpClient 生成的标准日志，GoFrame 后续可写入 mcp_call_logs 表。
                logs.append(fetched.log)
                # fetch_mcp 返回的 raw_text 会回填到文章对象，供评分和摘要阶段使用。
                article["raw_text"] = str(fetched.result.get("raw_text", ""))

            # 先用本地可解释规则计算基础分数；即使 MCP 不可用，也能得到可运行的筛选结果。
            score, reasons = self._score_article(article, profile)
            # 如果允许 neo4j，就读取用户兴趣图谱上下文，用图谱匹配结果微调分数。
            if policy.get("enable_neo4j") and self.neo4j_client:
                context = self.neo4j_client.get_profile_context(str(profile.get("user_id", "")), profile, agent_name=self.name, run_id=run_id)
                logs.append(context.log)
                # mock 或真实 neo4j-mcp 返回 topics 时，说明找到了用户相关主题，因此小幅提高分数。
                if context.result.get("topics"):
                    score = min(score + 0.05, 1.0)
                    reasons.append("mock-profile-context")

            # embedding 初始为空列表；只有成功调用 embedding-mcp 后才会进入 Milvus 相似记忆检索。
            embedding: list[float] = []
            # 如果允许 embedding，就把标题和正文拼在一起生成文章向量。
            if policy.get("enable_embedding") and self.embedding_client:
                embedded = self.embedding_client.embed_text(
                    f"{article.get('title', '')}\n{article.get('raw_text', '')}",
                    agent_name=self.name,
                    run_id=run_id,
                )
                logs.append(embedded.log)
                # list(...) 把 MCP 返回的可迭代结果转换为普通列表，方便后续 JSON/gRPC 序列化。
                embedding = list(embedded.result.get("embedding", []))

            # 如果有向量且允许 milvus，就查找相似记忆，作为判断文章与用户长期兴趣是否相关的依据。
            if policy.get("enable_milvus") and embedding and self.milvus_client:
                related = self.milvus_client.search_similar_memory(embedding, agent_name=self.name, run_id=run_id)
                logs.append(related.log)
                # 找到相似记忆时小幅加分；这里是 mock/规则式信号，不把它当作真实推荐模型。
                if related.result.get("matches"):
                    score = min(score + 0.05, 1.0)
                    reasons.append("mock-related-articles")

            # keep 是最终是否进入摘要/改写流程的布尔值。
            # 这里要求分数达到阈值且标题存在，避免空标题内容进入后续发布链路。
            keep = score >= 0.5 and bool(article.get("title"))
            # 将每篇文章的结果写成统一结构，后续 Agent 在同一个 result 上追加字段。
            article_results.append(
                {
                    # article 保存原始/补全后的文章内容，SummaryAgent 和 RewriteAgent 会继续读取。
                    "article": article,
                    # article_id 是跨 Python、GoFrame、数据库表的文章主标识。
                    "article_id": article["article_id"],
                    # keep 控制 SummaryAgent、RewriteAgent 是否跳过该文章。
                    "keep": keep,
                    # round(score, 4) 让响应中的分数更稳定，便于日志和测试比较。
                    "score": round(score, 4),
                    # summary 初始为空，等待 SummaryAgent 填充。
                    "summary": "",
                    # post_text 初始为空，等待 RewriteAgent 填充。
                    "post_text": "",
                    # check_pass 初始为 False，等待 CheckAgent 最终校验。
                    "check_pass": False,
                    # 未通过筛选的文章记录 filtered_out，方便 GoFrame 或前端解释原因。
                    "issues": [] if keep else ["filtered_out"],
                    # mcp_call_logs 是当前文章触发的 MCP 调用日志。
                    "mcp_call_logs": logs,
                    # filter_reasons 记录可解释的筛选理由，便于调试筛选分数。
                    "filter_reasons": reasons,
                }
            )
        # 将所有文章结果写回 state，后续 Agent 通过这个字段继续处理。
        state["article_results"] = article_results
        return state

    # 函数作用：
    # 使用本地规则计算文章与用户画像的基础相关性分数。
    #
    # 参数说明：
    # - article：标准化后的文章字典。
    # - profile：user_profile_snapshot 字典，可能包含 interests、topics、keywords 等字段。
    #
    # 返回值：
    # - 返回二元组：(分数, 原因列表)。分数范围控制在 0 到 1。
    #
    # 调用关系：
    # - 被 run 方法调用，作为 MCP 信号之外的基础筛选逻辑。
    def _score_article(self, article: JsonDict, profile: JsonDict) -> tuple[float, list[str]]:
        # 取出标题并去除首尾空白，标题存在说明文章最基本信息完整。
        title = str(article.get("title", "")).strip()
        # 取出正文并去除首尾空白，正文长度会影响是否适合总结。
        raw_text = str(article.get("raw_text", "")).strip()
        # haystack 把标题和正文合并成小写文本，方便做关键词包含匹配。
        haystack = f"{title} {raw_text}".lower()
        # 初始分数给 0.1，表示即使信息较少也保留一个基础值，避免所有空字段都是 0 的极端情况。
        score = 0.1
        # reasons 保存本地规则命中的原因，供调试和最终结果解释。
        reasons: list[str] = []

        # 有标题说明文章可识别，因此提高分数。
        if title:
            score += 0.25
            reasons.append("has-title")
        # 有 URL 说明后续可以回溯原文，也方便 CheckAgent 做完整性校验。
        if article.get("url"):
            score += 0.1
            reasons.append("has-url")
        # 正文足够长时，LLM 摘要质量通常更可靠，因此加更高分。
        if len(raw_text) >= 80:
            score += 0.25
            reasons.append("has-enough-text")
        # 正文较短但非空时仍然提供少量信息，因此加较低分。
        elif raw_text:
            score += 0.12
            reasons.append("has-short-text")

        # 从用户画像中提取兴趣关键词，与文章文本匹配。
        keywords = self._profile_keywords(profile)
        # 列表推导式筛出同时非空且出现在文章文本中的关键词。
        # 这里做 lower() 是为了让英文关键词大小写不影响匹配。
        matched = [word for word in keywords if word and word.lower() in haystack]
        # 命中用户兴趣时提高分数，最多加 0.25，避免关键词数量过多导致分数失控。
        if matched:
            score += min(0.25, 0.08 * len(matched))
            reasons.append("matches-user-profile:" + ",".join(matched[:3]))

        # min(score, 1.0) 保证分数不会超过 1，便于前后端按百分比或阈值理解。
        return min(score, 1.0), reasons

    # 函数作用：
    # 从 user_profile_snapshot 中抽取可用于文章匹配的关键词。
    #
    # 参数说明：
    # - profile：用户画像快照，可能是 GoFrame 从 user_profile_snapshot 表读出的 map。
    #
    # 返回值：
    # - 返回去空后的关键词字符串列表。
    def _profile_keywords(self, profile: JsonDict) -> list[str]:
        # values 暂存从不同画像字段中解析出的关键词。
        values = []
        # 这些 key 是项目中约定的用户兴趣字段，可能来自配置、反馈更新或数据库快照。
        for key in ["interests", "topics", "keywords", "preferred_tags"]:
            raw = profile.get(key, "")
            # 如果字段是字符串，就支持用英文逗号或分号分隔多个关键词。
            if isinstance(raw, str):
                values.extend(part.strip() for part in raw.replace(";", ",").split(","))
            # 如果字段已经是列表，就逐项转成字符串，兼容 Python 内部测试或 JSON 输入。
            elif isinstance(raw, list):
                values.extend(str(part).strip() for part in raw)
        # 过滤空字符串，避免后续匹配出现无意义命中。
        return [value for value in values if value]
