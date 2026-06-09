import type { ReactNode } from "react";
import { AlertCircle, Lock, RefreshCw } from "lucide-react";
import type { AsyncState } from "./hooks";

interface StateBlockProps<T> {
  state: AsyncState<T>;
  emptyTitle: string;
  children: (data: T) => ReactNode;
}

export function StateBlock<T>({ state, emptyTitle, children }: StateBlockProps<T>) {
  if (state.status === "loading") {
    return (
      <div className="state-panel" role="status" aria-label="正在加载">
        <RefreshCw className="spin" size={18} />
        <span>正在加载</span>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className={state.forbidden ? "state-panel forbidden" : "state-panel error"} role="alert">
        {state.forbidden ? <Lock size={18} /> : <AlertCircle size={18} />}
        <span>{state.forbidden ? "无权限访问，请配置 API Token。" : state.error}</span>
      </div>
    );
  }

  if (state.status === "empty") {
    return <div className="state-panel muted">{emptyTitle}</div>;
  }

  return <>{children(state.data)}</>;
}

export function StatusPill({ value }: { value?: string | null }) {
  const normalized = (value || "unknown").toLowerCase();
  const tone =
    normalized.includes("failed") || normalized.includes("unavailable")
      ? "danger"
      : normalized.includes("running") || normalized.includes("pending")
        ? "warn"
        : normalized.includes("cancel")
          ? "muted"
          : "ok";
  return <span className={`pill ${tone}`}>{value || "unknown"}</span>;
}

export function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function JsonPreview({ value }: { value: unknown }) {
  let text = "";
  if (typeof value === "string") {
    try {
      text = JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      text = value;
    }
  } else {
    text = JSON.stringify(value ?? {}, null, 2);
  }
  return <pre className="json-preview">{text}</pre>;
}
