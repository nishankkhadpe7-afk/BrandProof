export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Role = "creator" | "reviewer" | "brand_owner" | "admin";

export const PERSONAS: Record<Role, { name: string; label: string; does: string }> = {
  creator: { name: "Meera (Agency creator)", label: "Creator", does: "Submit content, accept or edit fixes" },
  reviewer: { name: "Kabir (Reviewer)", label: "Reviewer", does: "Override with reason, approve or reject" },
  brand_owner: { name: "Ravi (Brand owner)", label: "Brand owner", does: "Upload guidelines, manage facts, review" },
  admin: { name: "Asha (Admin)", label: "Admin", does: "Validate rules, manage sources" },
};

export function getRole(): Role {
  if (typeof window === "undefined") return "creator";
  try {
    const r = window.localStorage.getItem("bp_role") as Role | null;
    return r && r in PERSONAS ? r : "creator";
  } catch {
    return "creator";
  }
}

export function setRole(r: Role) {
  try {
    window.localStorage.setItem("bp_role", r);
  } catch {}
  window.dispatchEvent(new Event("bp-role"));
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const role = getRole();
  const headers: Record<string, string> = { "X-Role": role, "X-User": PERSONAS[role].name, ...(init.headers as any) };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(API + path, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export type Finding = {
  id: number;
  category: string;
  status: string;
  severity: string;
  start: number | null;
  end: number | null;
  region: { x: number; y: number; w: number; h: number; img_w: number; img_h: number } | null;
  excerpt: string;
  rule_id: number | null;
  rule_text: string | null;
  rule_type: string | null;
  fact_id: number | null;
  fact_label: string | null;
  fact_value: string | null;
  reason: string;
  suggestion: string | null;
  source_ref: string | null;
  confidence: number;
  engine: string;
  decision: string;
  decision_text: string | null;
  decision_reason: string | null;
  decided_by: string | null;
};

export function when(ts: string) {
  const d = new Date(ts);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
