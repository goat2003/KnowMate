import { useMemo, useState } from "react";
import {
  Activity,
  ClipboardList,
  FileText,
  HeartHandshake,
  History,
  ListFilter,
  MessageSquareText,
  RotateCcw,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  UserRound
} from "lucide-react";
import { createApiClient, type ApiClient } from "./api";
import { isArrayEmpty, useAsyncData } from "./hooks";
import { JsonPreview, Metric, StateBlock, StatusPill } from "./components";
import type { Article, HealthResponse, McpCallLog, Post, TaskRun, UserProfileSnapshot } from "./types";

type View =
  | "overview"
  | "runs"
  | "articles"
  | "posts"
  | "feedback"
  | "profile"
  | "mcp"
  | "settings";

const navItems: Array<{ id: View; label: string; icon: React.ComponentType<{ size?: number }> }> = [
  { id: "overview", label: "系统概览", icon: Activity },
  { id: "runs", label: "任务运行记录", icon: ClipboardList },
  { id: "articles", label: "文章列表", icon: FileText },
  { id: "posts", label: "推文列表与详情", icon: MessageSquareText },
  { id: "feedback", label: "用户反馈", icon: HeartHandshake },
  { id: "profile", label: "用户画像", icon: UserRound },
  { id: "mcp", label: "MCP 调用日志", icon: History },
  { id: "settings", label: "系统配置与健康状态", icon: Settings }
];

export function App({ client }: { client?: ApiClient }) {
  const api = useMemo(() => client ?? createApiClient(), [client]);
  const [view, setView] = useState<View>("overview");
  const [selectedRunID, setSelectedRunID] = useState("");
  const [selectedPostID, setSelectedPostID] = useState("");
  const [notice, setNotice] = useState("");

  const health = useAsyncData(() => api.health(), () => false, [api]);

  const content = useMemo(() => {
    const common = { client: api, setNotice };
    switch (view) {
      case "overview":
        return <Overview client={api} health={health.state} setNotice={setNotice} openView={setView} />;
      case "runs":
        return <RunsPage {...common} selectedRunID={selectedRunID} setSelectedRunID={setSelectedRunID} />;
      case "articles":
        return <ArticlesPage client={api} />;
      case "posts":
        return <PostsPage {...common} selectedPostID={selectedPostID} setSelectedPostID={setSelectedPostID} />;
      case "feedback":
        return <FeedbackPage {...common} selectedPostID={selectedPostID} />;
      case "profile":
        return <ProfilePage {...common} />;
      case "mcp":
        return <McpPage client={api} />;
      case "settings":
        return <SettingsPage health={health.state} refreshHealth={health.refresh} />;
    }
  }, [api, health.state, health.refresh, selectedPostID, selectedRunID, view]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Sparkles size={22} />
          <div>
            <strong>KnowMate</strong>
            <span>管理后台</span>
          </div>
        </div>
        <nav aria-label="管理后台导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={view === item.id ? "active" : ""}
                data-testid={`nav-${item.id}`}
                onClick={() => setView(item.id)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <span className="eyebrow">GoFrame API</span>
            <h1>{navItems.find((item) => item.id === view)?.label}</h1>
          </div>
          <div className="topbar-status">
            <span>数据库 <StatusPill value={health.state.status === "success" ? String(health.state.data.db?.status || "unknown") : health.state.status} /></span>
            <span>Agent <StatusPill value={health.state.status === "success" ? String(health.state.data.agent?.status || "unknown") : health.state.status} /></span>
          </div>
        </header>
        {notice ? (
          <div className="notice" role="status">
            {notice}
            <button onClick={() => setNotice("")}>关闭</button>
          </div>
        ) : null}
        {content}
      </main>
    </div>
  );
}

function Overview({
  client,
  health,
  setNotice,
  openView
}: {
  client: ApiClient;
  health: ReturnType<typeof useAsyncData<HealthResponse>>["state"];
  setNotice: (value: string) => void;
  openView: (view: View) => void;
}) {
  const runs = useAsyncData(() => client.listRuns({ limit: 6 }), isArrayEmpty, [client]);
  const posts = useAsyncData(() => client.listPosts(), isArrayEmpty, [client]);
  const mcp = useAsyncData(() => client.listMcpCallLogs({ status: "failed", limit: 6 }), isArrayEmpty, [client]);

  async function triggerRun() {
    try {
      const result = await client.runArticles();
      setNotice(`已触发抓取任务：${result.run_id}（${result.status}）`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section className="page-grid">
      <div className="panel hero-panel">
        <div>
          <span className="eyebrow">实时操作</span>
          <h2>抓取、处理、反馈和画像更新集中在这里。</h2>
        </div>
        <button className="primary" onClick={triggerRun}>
          <ListFilter size={18} />
          手动触发抓取
        </button>
      </div>
      <div className="metrics-row">
        <Metric label="系统" value={<StatusPill value={health.status === "success" ? health.data.status : health.status} />} />
        <Metric label="最近任务" value={runs.state.status === "success" ? runs.state.data.length : "-"} />
        <Metric label="最近推文" value={posts.state.status === "success" ? posts.state.data.length : "-"} />
        <Metric label="失败 MCP" value={mcp.state.status === "success" ? mcp.state.data.length : 0} />
      </div>
      <RecentRuns state={runs.state} onOpen={(runID) => openView("runs")} />
      <RecentPosts state={posts.state} onOpen={(postID) => openView("posts")} />
    </section>
  );
}

function RecentRuns({ state }: { state: ReturnType<typeof useAsyncData<TaskRun[]>>["state"]; onOpen: (runID: string) => void }) {
  return (
    <div className="panel">
      <h2>最近任务</h2>
      <StateBlock state={state} emptyTitle="暂无任务运行记录">
        {(items) => (
          <table>
            <thead>
              <tr>
                <th>Run ID</th>
                <th>类型</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {items.map((run) => (
                <tr key={run.run_id}>
                  <td>{run.run_id}</td>
                  <td>{run.task_type}</td>
                  <td><StatusPill value={run.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </StateBlock>
    </div>
  );
}

function RecentPosts({ state }: { state: ReturnType<typeof useAsyncData<Post[]>>["state"]; onOpen: (postID: string) => void }) {
  return (
    <div className="panel">
      <h2>最近推文</h2>
      <StateBlock state={state} emptyTitle="暂无推文">
        {(items) => (
          <div className="stack-list">
            {items.slice(0, 6).map((post) => (
              <div className="list-item" key={post.post_uid}>
                <strong>{post.title}</strong>
                <span>{post.post_uid}</span>
                <StatusPill value={post.status} />
              </div>
            ))}
          </div>
        )}
      </StateBlock>
    </div>
  );
}

function RunsPage({
  client,
  selectedRunID,
  setSelectedRunID,
  setNotice
}: {
  client: ApiClient;
  selectedRunID: string;
  setSelectedRunID: (value: string) => void;
  setNotice: (value: string) => void;
}) {
  const [status, setStatus] = useState("");
  const runs = useAsyncData(() => client.listRuns({ status, limit: 30 }), isArrayEmpty, [client, status]);
  const detail = useAsyncData(() => (selectedRunID ? client.getRun(selectedRunID) : Promise.resolve({} as TaskRun)), (run) => !run.run_id, [client, selectedRunID]);

  async function retry(runID: string) {
    try {
      const result = await client.retryRun(runID);
      setNotice(`已重试任务：${result.run_id}（${result.status}）`);
      await runs.refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section className="split-page">
      <div className="panel">
        <div className="panel-header">
          <h2>运行记录</h2>
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="任务状态筛选">
            <option value="">全部</option>
            <option value="running">running</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
            <option value="partially_completed">partially_completed</option>
            <option value="cancelled">cancelled</option>
          </select>
        </div>
        <StateBlock state={runs.state} emptyTitle="暂无匹配任务">
          {(items) => (
            <div className="stack-list">
              {items.map((run) => (
                <button className="list-row" key={run.run_id} onClick={() => setSelectedRunID(run.run_id)}>
                  <span>{run.run_id}</span>
                  <span>{run.task_type}</span>
                  <StatusPill value={run.status} />
                </button>
              ))}
            </div>
          )}
        </StateBlock>
      </div>
      <div className="panel">
        <h2>任务步骤和错误</h2>
        <StateBlock state={detail.state} emptyTitle="选择一条任务查看步骤">
          {(run) => (
            <>
              <div className="detail-header">
                <strong>{run.run_id}</strong>
                <StatusPill value={run.status} />
                <button onClick={() => retry(run.run_id)}>
                  <RotateCcw size={16} />
                  重试失败任务
                </button>
              </div>
              {run.error_message ? <div className="state-panel error">{run.error_message}</div> : null}
              <div className="timeline">
                {(run.steps || []).map((step) => (
                  <div key={step.step_name} className="timeline-item">
                    <StatusPill value={step.status} />
                    <strong>{step.step_name}</strong>
                    <span>{step.output_summary || step.input_summary || step.error_message}</span>
                  </div>
                ))}
              </div>
              <JsonPreview value={run.partial_result} />
            </>
          )}
        </StateBlock>
      </div>
    </section>
  );
}

function ArticlesPage({ client }: { client: ApiClient }) {
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const articles = useAsyncData(() => client.listArticles({ source, status, q: query, limit: 50 }), isArrayEmpty, [client, source, status, query]);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>文章列表</h2>
        <div className="filters">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题 / URL" aria-label="文章搜索" />
          <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="来源" aria-label="文章来源筛选" />
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="抓取状态筛选">
            <option value="">全部状态</option>
            <option value="success">success</option>
            <option value="partial">partial</option>
            <option value="failed">failed</option>
          </select>
        </div>
      </div>
      <StateBlock state={articles.state} emptyTitle="暂无文章">
        {(items) => (
          <table>
            <thead>
              <tr>
                <th>标题</th>
                <th>来源</th>
                <th>状态</th>
                <th>语言</th>
                <th>发布时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((article: Article) => (
                <tr key={article.id}>
                  <td>
                    <strong>{article.title || article.id}</strong>
                    <span className="subtle">{article.url}</span>
                  </td>
                  <td>{article.source}</td>
                  <td><StatusPill value={article.fetch_status} /></td>
                  <td>{article.language || "-"}</td>
                  <td>{formatDate(article.published_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </StateBlock>
    </section>
  );
}

function PostsPage({
  client,
  selectedPostID,
  setSelectedPostID
}: {
  client: ApiClient;
  selectedPostID: string;
  setSelectedPostID: (value: string) => void;
  setNotice: (value: string) => void;
}) {
  const posts = useAsyncData(() => client.listPosts(), isArrayEmpty, [client]);
  const detail = useAsyncData(() => (selectedPostID ? client.getPost(selectedPostID) : Promise.resolve({} as Post)), (post) => !post.post_uid, [client, selectedPostID]);

  return (
    <section className="split-page wide-detail">
      <div className="panel">
        <h2>推文列表</h2>
        <StateBlock state={posts.state} emptyTitle="暂无推文">
          {(items) => (
            <div className="stack-list">
              {items.map((post) => (
                <button className="list-row" key={post.post_uid} onClick={() => setSelectedPostID(post.post_uid)}>
                  <span>{post.title}</span>
                  <StatusPill value={post.status} />
                </button>
              ))}
            </div>
          )}
        </StateBlock>
      </div>
      <div className="panel">
        <h2>推文详情</h2>
        <StateBlock state={detail.state} emptyTitle="选择一条推文查看详情">
          {(post) => (
            <>
              <div className="detail-header">
                <strong>{post.title}</strong>
                <StatusPill value={post.status} />
              </div>
              <div className="score-grid">
                <Metric label="评分" value={post.metadata?.score ?? "-"} />
                <Metric label="排名" value={post.metadata?.rank_position ?? "-"} />
                <Metric label="画像版本" value={post.metadata?.profile_version ?? "-"} />
              </div>
              <h3>评分明细</h3>
              <div className="breakdown">
                {(post.metadata?.score_breakdown || []).map((item, index) => (
                  <div key={`${item.dimension}-${index}`} className="breakdown-row">
                    <span>{item.dimension}</span>
                    <strong>{item.normalized_score ?? item.raw_score ?? "-"}</strong>
                    <span>{item.evidence?.join(", ")}</span>
                  </div>
                ))}
              </div>
              <h3>推荐原因</h3>
              <ul className="reason-list">
                {(post.metadata?.recommendation_reasons || []).map((reason) => <li key={reason}>{reason}</li>)}
                {(post.metadata?.recommendation_reasons || []).length === 0 ? <li>暂无推荐原因</li> : null}
              </ul>
              <h3>正文</h3>
              <pre className="markdown-preview">{post.markdown}</pre>
            </>
          )}
        </StateBlock>
      </div>
    </section>
  );
}

function FeedbackPage({ client, selectedPostID, setNotice }: { client: ApiClient; selectedPostID: string; setNotice: (value: string) => void }) {
  const [postID, setPostID] = useState(selectedPostID);
  const [text, setText] = useState("");
  const [rating, setRating] = useState(5);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      const result = await client.submitFeedback({ post_id: postID, feedback_text: text, rating, feedback_type: "text" });
      setNotice(`反馈已提交：${result.run_id}（${result.status}）`);
      setText("");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section className="panel form-panel">
      <h2>提交用户反馈</h2>
      <form onSubmit={submit}>
        <label>
          Post ID
          <input value={postID} onChange={(event) => setPostID(event.target.value)} required />
        </label>
        <label>
          评分
          <input type="number" min="1" max="5" value={rating} onChange={(event) => setRating(Number(event.target.value))} />
        </label>
        <label>
          反馈内容
          <textarea value={text} onChange={(event) => setText(event.target.value)} required rows={6} />
        </label>
        <button className="primary" type="submit">提交反馈</button>
      </form>
    </section>
  );
}

function ProfilePage({ client, setNotice }: { client: ApiClient; setNotice: (value: string) => void }) {
  const [userID, setUserID] = useState("default-user");
  const profile = useAsyncData(() => client.getProfile(userID), (item) => !item.user_id, [client, userID]);
  const history = useAsyncData(() => client.listProfileHistory(userID), isArrayEmpty, [client, userID]);

  async function rollback(version: number) {
    try {
      const result = await client.rollbackProfile({ user_id: userID, target_version: version, reason: "web_admin_rollback" });
      setNotice(`画像已回滚生成版本：${result.version}`);
      await Promise.all([profile.refresh(), history.refresh()]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section className="split-page">
      <div className="panel">
        <div className="panel-header">
          <h2>当前画像</h2>
          <input value={userID} onChange={(event) => setUserID(event.target.value)} aria-label="用户 ID" />
        </div>
        <StateBlock state={profile.state} emptyTitle="暂无画像">
          {(item) => (
            <>
              <div className="score-grid">
                <Metric label="用户" value={item.user_id} />
                <Metric label="版本" value={item.version} />
                <Metric label="状态" value={item.is_active ? "active" : "inactive"} />
              </div>
              <JsonPreview value={item.snapshot} />
            </>
          )}
        </StateBlock>
      </div>
      <div className="panel">
        <h2>画像历史</h2>
        <StateBlock state={history.state} emptyTitle="暂无历史版本">
          {(items: UserProfileSnapshot[]) => (
            <div className="stack-list">
              {items.map((item) => (
                <div className="list-item" key={item.version}>
                  <strong>v{item.version}</strong>
                  <span>{item.change_reason || "profile"}</span>
                  <button onClick={() => rollback(item.version)}>
                    <RotateCcw size={16} />
                    回滚
                  </button>
                </div>
              ))}
            </div>
          )}
        </StateBlock>
      </div>
    </section>
  );
}

function McpPage({ client }: { client: ApiClient }) {
  const [status, setStatus] = useState("");
  const [server, setServer] = useState("");
  const logs = useAsyncData(() => client.listMcpCallLogs({ status, server, limit: 50 }), isArrayEmpty, [client, status, server]);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>MCP Tool 调用状态</h2>
        <div className="filters">
          <input value={server} onChange={(event) => setServer(event.target.value)} placeholder="server" aria-label="MCP server 筛选" />
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="MCP 状态筛选">
            <option value="">全部</option>
            <option value="success">success</option>
            <option value="failed">failed</option>
            <option value="denied">denied</option>
          </select>
        </div>
      </div>
      <StateBlock state={logs.state} emptyTitle="暂无 MCP 调用日志">
        {(items: McpCallLog[]) => (
          <table>
            <thead>
              <tr>
                <th>工具</th>
                <th>Run ID</th>
                <th>状态</th>
                <th>耗时</th>
                <th>错误</th>
              </tr>
            </thead>
            <tbody>
              {items.map((log) => (
                <tr key={log.call_id}>
                  <td>
                    <strong>{log.server_name}</strong>
                    <span className="subtle">{log.tool_name}</span>
                  </td>
                  <td>{log.run_id}</td>
                  <td><StatusPill value={log.status} /></td>
                  <td>{log.latency_ms ?? 0}ms</td>
                  <td>{log.error_message || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </StateBlock>
    </section>
  );
}

function SettingsPage({ health, refreshHealth }: { health: ReturnType<typeof useAsyncData<HealthResponse>>["state"]; refreshHealth: () => Promise<void> }) {
  return (
    <section className="split-page">
      <div className="panel">
        <div className="panel-header">
          <h2>服务健康状态</h2>
          <button onClick={() => void refreshHealth()}>
            <SlidersHorizontal size={16} />
            刷新
          </button>
        </div>
        <StateBlock state={health} emptyTitle="暂无健康状态">
          {(item) => <JsonPreview value={item} />}
        </StateBlock>
      </div>
      <div className="panel">
        <h2>运维入口</h2>
        <div className="link-grid">
          <a href="http://127.0.0.1:8080/metrics">GoFrame Metrics</a>
          <a href="http://127.0.0.1:9101/metrics">Python Agent Metrics</a>
          <a href="http://127.0.0.1:9090">Prometheus</a>
          <a href="http://127.0.0.1:3000">Grafana</a>
          <a href="http://127.0.0.1:16686">Jaeger</a>
        </div>
        <div className="state-panel muted">
          <ShieldAlert size={18} />
          生产环境请配置 `GOFRAME_API_TOKEN`，无权限响应会显示为权限状态。
        </div>
      </div>
    </section>
  );
}

function formatDate(value?: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}
