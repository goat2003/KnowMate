import { useEffect, useRef, useState } from "react";
import { ArrowUp, Brain, BookOpen, RotateCcw, Trash2 } from "lucide-react";
import type { ApiClient } from "./api";
import type { ChatMemory, ChatMessage, ChatResult } from "./types";
import { createRequestId } from "./requestId";

const labels: Record<string, string> = { interests: "兴趣", goal: "目标", avoid: "避开", style: "风格", level: "水平" };

export function WeChatChatPage({ client }: { client: ApiClient }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [memories, setMemories] = useState<ChatMemory[]>([]);
  const [recommendations, setRecommendations] = useState<ChatResult["recommendations"]>([]);
  const [draft, setDraft] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const tail = useRef<HTMLDivElement>(null);

  async function refresh() {
    try {
      await client.wechatMe();
      setAuthorized(true);
    } catch (e) {
      const status = (e as { status?: number }).status;
      setError(e instanceof Error ? e.message : "暂时无法验证登录状态");
      if (status === 401) {
        setAuthorized(false);
      } else {
        setAuthorized(null);
      }
      if (status === 401 && !new URLSearchParams(window.location.search).has("auth_retry")) {
        const url = new URL("/api/wechat/auth", window.location.origin);
        url.searchParams.set("auth_retry", "1");
        window.location.assign(url.toString());
      }
      setLoading(false);
      return;
    }

    const results = await Promise.allSettled([
      client.wechatConversations(), client.wechatMemories(), client.wechatRecommendations()
    ]);
    const [conversation, memory, recs] = results;
    if (conversation.status === "fulfilled") setMessages(conversation.value);
    if (memory.status === "fulfilled") setMemories(memory.value);
    if (recs.status === "fulfilled") setRecommendations(recs.value);
    const failure = results.find(result => result.status === "rejected");
    if (!failure) setError("");
    else {
      const cause = failure.reason;
      setError(cause instanceof Error ? cause.message : "部分聊天功能暂时不可用");
    }
    setLoading(false);
  }
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 2500); return () => window.clearInterval(timer); }, []);
  useEffect(() => { tail.current?.scrollIntoView?.({ behavior: "smooth" }); }, [messages.length]);

  async function send(text = draft) {
    if (!text.trim() || busy) return;
    setBusy(true); setError("");
    try { await client.wechatSend({ request_id: createRequestId(), text: text.trim(), remember }); setDraft(""); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "发送失败，请重试"); }
    finally { setBusy(false); }
  }
  async function forget(key?: string) {
    setBusy(true); setError("");
    try { await client.wechatForget(key); setConfirmClear(false); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "删除失败"); }
    finally { setBusy(false); }
  }

  if (authorized === null) return <main className="wechat-page"><section className="wechat-card wechat-auth-error"><div className="wechat-mark">K</div><h1>暂时无法连接</h1><p>{error || "正在验证登录状态…"}</p><button className="wechat-primary" onClick={() => { setLoading(true); void refresh(); }}><RotateCcw size={17} />重试</button></section></main>;
  if (authorized === false) return <main className="wechat-page"><section className="wechat-card wechat-auth-error"><div className="wechat-mark">K</div><h1>需要微信授权</h1><p>{error || "请完成微信网页授权后继续聊天。"}</p><a className="wechat-primary" href="/api/wechat/auth"><RotateCcw size={17} />重新授权</a></section></main>;
  return <main className="wechat-page">
    <header className="wechat-header"><div className="wechat-mark">K</div><div><h1>KnowMate</h1><p>你的知识助手</p></div></header>
    {error && <div className="wechat-alert" role="alert">{error}<button onClick={() => void refresh()}>重试</button></div>}
    <section className="wechat-card wechat-conversation" aria-label="微信聊天">
      <div className="wechat-stream" role="log" aria-live="polite">
        {loading ? <div className="wechat-empty">正在加载你的会话…</div> : messages.length === 0 ? <div className="wechat-empty"><div className="wechat-empty-icon"><Brain size={23} /></div><h2>从一个问题开始</h2><p>告诉我你正在学习什么，或者想解决哪件事。</p><div className="wechat-prompts"><button disabled={busy} onClick={() => void send("根据我的兴趣推荐内容")}>推荐适合我的内容</button><button disabled={busy} onClick={() => void send("你能怎样帮助我？")}>你能怎样帮助我？</button></div></div> : messages.map(message => <article className="wechat-turn" key={message.id}><div className="wechat-user-bubble"><span>你</span><p>{message.text}</p></div><div className="wechat-assistant-bubble"><span>KnowMate</span>{message.status === "pending" || message.status === "processing" ? <p className="wechat-thinking">正在思考…</p> : <div><p>{message.result?.reply || message.error}</p>{message.result?.memory_status === "unavailable" && <small className="wechat-muted">记忆暂时不可用，本次聊天已保存</small>}</div>}{(message.result?.recommendations ?? []).map(item => <Recommendation key={item.id} item={item} />)}</div></article>)}
        <div ref={tail} />
      </div>
      <form className="wechat-composer" onSubmit={e => { e.preventDefault(); void send(); }}><textarea aria-label="输入消息" maxLength={4000} value={draft} disabled={busy} placeholder="输入你想聊的内容…" onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} /><div className="wechat-compose-footer"><label><input type="checkbox" checked={remember} disabled={busy} onChange={e => setRemember(e.target.checked)} /> 允许记住偏好</label><button className="wechat-send" aria-label="发送" disabled={busy || !draft.trim()}><ArrowUp size={19} /></button></div></form>
    </section>
    <section className="wechat-card wechat-panel"><div className="wechat-panel-title"><Brain size={18} /><h2>我的记忆</h2></div>{memories.length === 0 ? <p className="wechat-muted">还没有保存的偏好。你可以在消息中说“记住兴趣：Go”。</p> : memories.map(memory => <div className="wechat-memory" key={memory.key}><div><strong>{labels[memory.key] || memory.key}</strong><p>{memory.value}</p><small>来源：{memory.evidence}</small></div><button aria-label={`删除${labels[memory.key] || memory.key}`} disabled={busy} onClick={() => void forget(memory.key)}><Trash2 size={16} /></button></div>)}{memories.length > 0 && (confirmClear ? <div className="wechat-confirm"><p>确定清空全部记忆吗？</p><button onClick={() => void forget()}>确认清空</button><button onClick={() => setConfirmClear(false)}>取消</button></div> : <button className="wechat-text-button" onClick={() => setConfirmClear(true)}>清空全部记忆</button>)}</section>
    {recommendations.length > 0 && <section className="wechat-card wechat-panel"><div className="wechat-panel-title"><BookOpen size={18} /><h2>为你推荐</h2></div>{recommendations.map(item => <Recommendation key={item.id} item={item} />)}</section>}
  </main>;
}

function Recommendation({ item }: { item: ChatResult["recommendations"][number] }) { return <a className="wechat-recommendation" href={item.url} target="_blank" rel="noopener noreferrer"><BookOpen size={17} /><span><strong>{item.title}</strong>{item.summary && <small>{item.summary}</small>}<small>{item.reason}{item.published_at ? ` · ${item.published_at}` : ""}</small></span><span aria-hidden="true">↗</span></a>; }
