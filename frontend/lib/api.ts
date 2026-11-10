export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Role = "creator" | "reviewer" | "brand_owner" | "admin";
export const ROLE_LABEL: Record<Role, string> = { creator: "Creator", reviewer: "Reviewer", brand_owner: "Brand owner", admin: "Admin" };
export const ROLE_DOES: Record<Role, string> = {
  creator: "Submits content and applies fixes",
  reviewer: "Overrides with a reason, approves or rejects",
  brand_owner: "Owns guidelines and approved facts",
  admin: "Validates rules, manages the team",
};

export type Workspace = { id: number; name: string; brand: string | null; color: string | null; roles: Role[] };
export type Me = { user: { id: number; email: string; name: string; is_demo: number }; workspaces: Workspace[] };

const store = {
  get: (k: string) => { try { return window.localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string | null) => { try { v === null ? window.localStorage.removeItem(k) : window.localStorage.setItem(k, v); } catch {} },
};

export const session = {
  // remember=true keeps the session in localStorage (survives closing the browser);
  // otherwise sessionStorage, which the browser clears when it closes.
  token: () => {
    if (typeof window === "undefined") return null;
    try { return window.sessionStorage.getItem("bp_token") || store.get("bp_token"); } catch { return store.get("bp_token"); }
  },
  workspace: () => (typeof window === "undefined" ? null : store.get("bp_ws")),
  set(token: string, me: Me, remember?: boolean) {
    const keep = remember === undefined ? !!store.get("bp_token") : remember;
    try { window.sessionStorage.removeItem("bp_token"); } catch {}
    store.set("bp_token", null);
    if (keep) store.set("bp_token", token);
    else { try { window.sessionStorage.setItem("bp_token", token); } catch { store.set("bp_token", token); } }
    const cur = store.get("bp_ws");
    if (!cur || !me.workspaces.some((w) => String(w.id) === cur)) store.set("bp_ws", me.workspaces[0] ? String(me.workspaces[0].id) : null);
    window.dispatchEvent(new Event("bp-session"));
  },
  setWorkspace(id: number) { store.set("bp_ws", String(id)); window.dispatchEvent(new Event("bp-session")); },
  clear() {
    store.set("bp_token", null);
    try { window.sessionStorage.removeItem("bp_token"); } catch {}
    window.dispatchEvent(new Event("bp-session"));
  },
};

export class ApiError extends Error { status: number; constructor(m: string, s: number) { super(m); this.status = s; } }

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as any) };
  const t = session.token();
  const w = session.workspace();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (w) headers["X-Workspace"] = w;
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(API + path, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError("Can't reach the BrandProof server. It may be waking up — try again in a few seconds.", 0);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/login")) {
      session.clear();
      if (!location.pathname.startsWith("/login") && !location.pathname.startsWith("/welcome")) location.href = "/login";
    }
    throw new ApiError(msg, res.status);
  }
  return res.json();
}

export async function imageUrl(path: string): Promise<string> {
  const headers: Record<string, string> = {};
  const t = session.token(), w = session.workspace();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (w) headers["X-Workspace"] = w;
  const r = await fetch(API + path, { headers });
  if (!r.ok) throw new Error("image");
  return URL.createObjectURL(await r.blob());
}

export type Region = { x: number; y: number; w: number; h: number; img_w: number; img_h: number; page?: number; source?: string };
export type Finding = {
  id: number; category: string; status: string; severity: string;
  start: number | null; end: number | null; region: Region | null; excerpt: string;
  rule_id: number | null; rule_text: string | null; rule_type: string | null;
  fact_id: number | null; fact_label: string | null; fact_value: string | null;
  reason: string; suggestion: string | null; source_ref: string | null; confidence: number; engine: string;
  match: { model: string; score: number; runner_up: number | null; interpretation?: string; retrieved: { fact_id: number; label: string; score: number }[] } | null;
  decision: string; decision_text: string | null; decision_reason: string | null; decided_by: string | null;
};

export const STATUS_LABEL: Record<string, string> = {
  contradicted: "Contradicted", expired: "Expired", conflicting: "Conflicting", unverified: "Unverified", supported: "Supported", violation: "Rule broken",
};
export const STATUS_HELP: Record<string, string> = {
  contradicted: "Conflicts with an approved fact",
  expired: "The matching fact is out of date",
  conflicting: "Two approved sources disagree",
  unverified: "No approved fact covers this — not necessarily wrong",
  supported: "Matches an approved fact",
  violation: "Breaks a brand guideline",
};

export function when(ts: string) {
  const d = new Date(ts.endsWith("Z") || ts.includes("+") ? ts : ts + "Z");
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export const has = (roles: Role[] | undefined, ...need: Role[]) => !!roles && need.some((r) => roles.includes(r));
