import { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpen, Brain, MessageCircle, Trash2 } from "lucide-react";
import type { ApiClient } from "./api";
import type { ChatMemory, ChatMessage, WeChatStatus } from "./types";
import { createRequestId } from "./requestId";

const labels: Record<string, string> = { interests: "兴趣方向", goal: "当前目标", avoid: "减少推荐", style: "内容风格", level: "知识水平" };
const deliveryLabels: Record<string, string> = { ready: "等待发往微信", sending: "正在发送", sent: "已发往微信", expired: "微信发送窗口已关闭", rejected: "微信拒绝发送，请检查账号权限", uncertain: "微信送达状态待核实，请勿重复发送" };

export function ChatPage({ client }: { client: ApiClient }) {
  const [userID, setUserID] = useState("default-user");
  const [users, setUsers] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [memories, setMemories] = useState<ChatMemory[]>([]);
  const [wechat, setWechat] = useState<WeChatStatus | null>(null);
  const [draft, setDraft] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [confirmClear, setConfirmClear] = useState(false);
  const last = useRef<HTMLDivElement>(null);
  // Reuse the request ID after a lost HTTP response; explicit duplicate clicks cannot enqueue twice.
  const pending = useRef<{ text: string; user: string; id: string; remember: boolean } | null>(null);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const [next, memory, people, wx] = await Promise.all([
          client.chatMessages(userID), client.chatMemories(userID), client.chatUsers(), client.wechatStatus()
        ]);
        if (disposed) return;
        setMessages(next); setMemories(memory); setUsers(people); setWechat(wx); setLoading(false);
      } catch (e) { if (!disposed) { setError(e instanceof Error ? e.message : "暂时无法加载会话"); setLoading(false); } }
      if (!disposed) timer = setTimeout(refresh, 2500);
    }
    void refresh();
    return () => { disposed = true; clearTimeout(timer); };
  }, [client, userID, revision]);

  const tail = messages.at(-1);
  useEffect(() => { last.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" }); }, [tail?.id, tail?.status]);

  async function send(text = draft) {
    if (!text.trim() || busy) return;
    setBusy(true); setError("");
    try {
      if (!pending.current || pending.current.text !== text || pending.current.user !== userID) {
        pending.current = { text, user: userID, id: createRequestId(), remember };
      }
      const request = pending.current;
      await client.sendChat({ user_id: userID, request_id: request.id, text, remember: request.remember });
      pending.current = null; setDraft(""); setRevision(v => v + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "发送失败，请重试"); }
    finally { setBusy(false); }
  }

  async function forget(key?: string) {
    setBusy(true); setError("");
    try { await client.forgetChatMemory(userID, key); setConfirmClear(false); setRevision(v => v + 1); }
    catch (e) { setError(e instanceof Error ? e.message : "删除失败"); }
    finally { setBusy(false); }
  }

  function switchUser(value: string) {
    setUserID(value); setMessages([]); setMemories([]); setLoading(true); setDraft(""); setError(""); setConfirmClear(false);
    pending.current = null;
  }

  return <div className="chat-layout">
    <section className="panel chat-main" aria-label="知识助手会话">
      <div className="chat-heading">
        <div><span className="eyebrow">KNOWMATE COMPANION</span><h2>聊聊你正在探索的事</h2><p>从一个问题开始，让每一次推荐更贴近你。</p></div>
        <label className="chat-user">管理会话<select aria-label="当前聊天用户" value={userID} disabled={busy} onChange={e => switchUser(e.target.value)}>
          {[...new Set(["default-user", ...users])].map(id => <option key={id} value={id}>{id === "default-user" ? "我的会话" : id}</option>)}
        </select></label>
      </div>
      {error && <div role="alert" className="chat-error">{error}<button onClick={() => { setError(""); setRevision(v => v + 1); }}>重新加载</button></div>}
      <div className="chat-stream" role="log" aria-label="聊天记录" aria-live="polite">
        {loading ? <p>正在加载会话…</p> : messages.length === 0 && <div className="chat-welcome">
          <div className="chat-orb"><MessageCircle size={28} /></div><h3>你好，我是你的知识助手</h3>
          <p>告诉我你的兴趣、正在解决的问题，或者今天想了解什么。</p>
          <div className="chat-prompts">{["我想了解你能怎样帮助我", "根据我的兴趣推荐内容", "你目前记得我哪些偏好？"].map(text => <button key={text} disabled={busy} onClick={() => void send(text)}>{text}</button>)}</div>
        </div>}
        {messages.map(message => <div className="chat-turn" key={message.id}>
          <div className="chat-bubble chat-human"><small>{message.channel === "wechat" ? "来自微信" : "你"}</small><p>{message.text}</p></div>
          <div className="chat-bubble chat-assistant"><small>KnowMate {message.result?.mock && <span className="chat-demo">演练模式</span>}</small>
            {message.status === "pending" || message.status === "processing" ? <p className="chat-thinking">正在整理思路…</p> : <div><p>{message.result?.reply || message.error}</p>{message.result?.memory_status === "unavailable" && <small className="chat-memory-unavailable">记忆暂时不可用，本次聊天已保存</small>}</div>}
            {(message.result?.recommendations ?? []).map(item => <a className="chat-recommendation" key={item.id} href={/^https?:\/\//i.test(item.url) ? item.url : undefined} target="_blank" rel="noopener noreferrer">
              <BookOpen size={18} /><span><strong>{item.title}</strong><small>{item.reason}</small></span><span aria-hidden="true">↗</span>
            </a>)}
            {(message.result?.memory_updates ?? []).length > 0 && <div className="chat-saved"><Brain size={14} />已更新：{message.result!.memory_updates.map(m => labels[m.key] || m.key).join("、")}</div>}
            {message.status === "failed" && <button disabled={busy} onClick={() => void send(message.text)}>重新提问</button>}
            {deliveryLabels[message.delivery] && <small>{deliveryLabels[message.delivery]}</small>}
          </div>
        </div>)}
        <div ref={last} />
      </div>
      <form className="chat-composer" onSubmit={e => { e.preventDefault(); void send(); }}>
        <label className="sr-only" htmlFor="chat-draft">发送给知识助手的消息</label>
        <textarea id="chat-draft" placeholder="例如：我在准备 Go 后端面试，想多看工程案例…" value={draft} maxLength={4000} onChange={e => setDraft(e.target.value)} disabled={busy}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
        <div className="chat-compose-footer"><label><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />允许从本条消息记住学习与内容偏好</label>
          <button className="primary chat-send" aria-label="发送消息" type="submit" disabled={busy || !draft.trim()}><ArrowUp size={18} />发送</button></div>
        <small>Enter 发送 · Shift + Enter 换行。关闭记忆仍会保存聊天记录。</small>
      </form>
    </section>
    <aside className="chat-aside">
      <section className="panel"><div className="chat-side-title"><Brain size={20} /><h2>助手记住了什么</h2></div><p className="muted">只保留与你的学习和推荐有关的偏好，你可以随时删除。</p>
        {memories.length === 0 && <p className="chat-empty-memory">还没有长期偏好。聊聊你的目标，或发送“记住兴趣：Go, 数据库”。</p>}
        {memories.map(memory => <div className="chat-memory" key={memory.key}><div><small>{labels[memory.key] || memory.key}</small><p>{memory.value}</p><details><summary>查看记忆来源</summary><q>{memory.evidence}</q></details></div><button aria-label={`删除${labels[memory.key] || memory.key}`} disabled={busy} onClick={() => void forget(memory.key)}><Trash2 size={16} /></button></div>)}
        {memories.length > 0 && (confirmClear ? <div role="alert"><p>清除全部聊天偏好？旧对话将不再作为助手的上下文。</p><button disabled={busy} onClick={() => void forget()}>确认清除</button><button onClick={() => setConfirmClear(false)}>取消</button></div> : <button className="chat-clear" onClick={() => setConfirmClear(true)}>清除全部聊天记忆</button>)}
      </section>
      <section className="panel chat-wechat"><div className="chat-side-title"><MessageCircle size={20} /><h2>在微信里继续聊</h2></div><p>{wechat?.enabled ? "公众号接入已启用，微信会话会自动出现在用户列表中。" : "公众号接入尚未启用。配置服务号后，就能在微信中提问和接收推荐。"}</p><p>发送“开启记忆”允许记录偏好；“关闭记忆”停止记录；“忘记全部记忆”清除聊天偏好。</p><small>推荐回复受微信会话窗口限制。此页面用于管理员管理会话，不是公共用户登录页。</small></section>
    </aside>
  </div>;
}
