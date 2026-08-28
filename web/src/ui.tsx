import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from "react";
import {
  Boxes,
  CheckCircle2,
  CircleAlert,
  ClipboardList,
  FlaskConical,
  LoaderCircle,
  PlaySquare,
  ShieldCheck
} from "lucide-react";

import type { Meta } from "./types";

export type PageKey = "blueprint" | "cases" | "runs";

const pages: Array<{ key: PageKey; label: string; icon: typeof ClipboardList }> = [
  { key: "blueprint", label: "Blueprint", icon: ClipboardList },
  { key: "cases", label: "Case Factory", icon: FlaskConical },
  { key: "runs", label: "Runs & Scores", icon: PlaySquare }
];

export function Shell({
  page,
  meta,
  children,
  onNavigate
}: PropsWithChildren<{ page: PageKey; meta: Meta | null; onNavigate: (page: PageKey) => void }>) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" type="button" onClick={() => onNavigate("blueprint")}>
          <span className="brand-mark" aria-hidden="true">
            <Boxes size={22} />
          </span>
          <span>
            Workflow
            <br />
            Environment Factory
          </span>
        </button>
        <nav aria-label="Primary navigation">
          {pages.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={page === item.key ? "nav-item active" : "nav-item"}
                key={item.key}
                type="button"
                onClick={() => onNavigate(item.key)}
              >
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-status" aria-label="Local service status">
          <div>
            <span className="status-dot good" /> Local only
          </div>
          <div>
            <span className={`status-dot ${meta?.docker_available ? "good" : "warn"}`} />
            {meta?.docker_available ? "Docker ready" : "Docker required"}
          </div>
          <div>
            <ShieldCheck size={15} /> Protocol v0.1
          </div>
        </div>
      </aside>
      <main className="main-surface">{children}</main>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="header-actions">{actions}</div> : null}
    </header>
  );
}

export function Button({
  tone = "primary",
  busy,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "primary" | "secondary" | "quiet" | "danger";
  busy?: boolean;
}) {
  return (
    <button className={`button ${tone}`} {...props} disabled={busy || props.disabled}>
      {busy ? <LoaderCircle className="spin" size={16} /> : null}
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
  wide = false
}: PropsWithChildren<{ label: string; hint?: string; wide?: boolean }>) {
  return (
    <label className={wide ? "field wide" : "field"}>
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function StatusTag({ status, label }: { status: string | boolean; label?: string }) {
  const normalized = typeof status === "boolean" ? (status ? "pass" : "fail") : status;
  const positive = ["pass", "completed", "ready", "confirmed"].includes(normalized);
  const pending = ["preparing", "running", "validating", "recording"].includes(normalized);
  return (
    <span className={`status-tag ${positive ? "positive" : pending ? "pending" : "negative"}`}>
      {positive ? <CheckCircle2 size={13} /> : pending ? <LoaderCircle className="spin" size={13} /> : <CircleAlert size={13} />}
      {label ?? normalized.replaceAll("_", " ")}
    </span>
  );
}

export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div className="error-banner" role="alert">
      <CircleAlert size={18} />
      <span>{message}</span>
      {onDismiss ? (
        <button type="button" onClick={onDismiss} aria-label="Dismiss error">
          Dismiss
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children }: PropsWithChildren<{ title: string }>) {
  return (
    <div className="empty-state">
      <FlaskConical size={26} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function shortId(value: string, length = 8): string {
  if (value.startsWith("sha256:")) return `${value.slice(0, length + 7)}…`;
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
