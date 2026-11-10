"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Logo, ThemeToggle } from "@/components/Theme";
import { API, Me, ROLE_LABEL, Role, Workspace, api, session } from "@/lib/api";

type Ctx = { me: Me | null; ws: Workspace | null; roles: Role[]; refresh: () => Promise<void>; toast: (msg: string, kind?: "ok" | "err") => void };
const SessionCtx = createContext<Ctx>({ me: null, ws: null, roles: [], refresh: async () => {}, toast: () => {} });
export const useSession = () => useContext(SessionCtx);
export const useRoles = () => useContext(SessionCtx).roles;

const NAV: [string, string][] = [
  ["/", "Overview"],
  ["/preflight", "Check"],
  ["/submissions", "Review"],
  ["/sources", "Rules & facts"],
  ["/team", "Team"],
  ["/audit", "Activity"],
];

export function Mark() {
  return <Logo height={26} />;
}

function useOutside(ref: React.RefObject<HTMLElement | null>, close: () => void) {
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close(); };
    const k = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); document.removeEventListener("keydown", k); };
  }, [ref, close]);
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [wsId, setWsId] = useState<string | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [down, setDown] = useState(false);
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: string }[]>([]);
  const [open, setOpen] = useState<"" | "ws" | "me" | "nav">("");
  const tid = useRef(0);
  const barRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(""), []);
  useOutside(barRef, close);
  const isAuthPage = ["/login", "/reset", "/privacy", "/terms", "/welcome"].some((p) => path.startsWith(p));

  const toast = useCallback((msg: string, kind: "ok" | "err" = "ok") => {
    const id = ++tid.current;
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 6000 : 3200);
  }, []);

  const refresh = useCallback(async () => {
    if (!session.token()) { setMe(null); return; }
    try {
      const m = await api<Me>("/api/auth/me");
      session.set(session.token()!, m);
      setMe(m);
      setWsId(session.workspace());
    } catch {}
  }, []);

  useEffect(() => {
    const sync = () => setWsId(session.workspace());
    window.addEventListener("bp-session", sync);
    fetch(API + "/api/health").then((r) => r.json()).then(setHealth).catch(() => setDown(true));
    return () => window.removeEventListener("bp-session", sync);
  }, []);

  useEffect(() => {
    if (isAuthPage) return;
    if (!session.token()) { router.replace(path === "/" ? "/welcome" : "/login"); return; }
    refresh();
  }, [isAuthPage, refresh, router]);

  useEffect(() => { setOpen(""); }, [path]);

  const ws = me?.workspaces.find((w) => String(w.id) === wsId) || me?.workspaces[0] || null;
  const roles = (ws?.roles || []) as Role[];
  const ctx: Ctx = { me, ws, roles, refresh, toast };

  if (isAuthPage) return <SessionCtx.Provider value={ctx}>{children}<Toasts toasts={toasts} /></SessionCtx.Provider>;

  async function logout() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch {}
    session.clear();
    router.replace("/login");
  }

  const navLinks = NAV.map(([href, label]) => {
    const on = href === "/" ? path === "/" : path.startsWith(href);
    return <Link key={href} href={href} className={on ? "on" : ""} aria-current={on ? "page" : undefined}>{label}</Link>;
  });

  return (
    <SessionCtx.Provider value={ctx}>
      <header className="topbar">
        <div className="bar" ref={barRef}>
          <Link href="/" className="brand" aria-label="BrandProof home"><Logo height={24} /></Link>
          <nav className="navlinks" aria-label="Main">{navLinks}</nav>
          <div className="bar-right">
            <ThemeToggle />
            {me && ws && (
              <div className="pop">
                <button className="ws-btn" onClick={() => setOpen(open === "ws" ? "" : "ws")} aria-expanded={open === "ws"} aria-haspopup="menu">
                  <span className="swatch" style={{ background: ws.color || "var(--ink)" }} />
                  <span className="ws-label">{ws.name}</span>
                  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M2 4l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
                </button>
                {open === "ws" && (
                  <div className="menu" role="menu">
                    <div className="menu-h">Switch brand</div>
                    {me.workspaces.map((w) => (
                      <button key={w.id} role="menuitem" className={w.id === ws.id ? "on" : ""}
                        onClick={() => { session.setWorkspace(w.id); close(); router.push("/"); }}>
                        <span className="swatch" style={{ background: w.color || "var(--ink)" }} />
                        <span className="grow">{w.name}<small>{(w.roles as Role[]).map((r) => ROLE_LABEL[r]).join(", ")}</small></span>
                      </button>
                    ))}
                    <Link href="/team?new=1" className="menu-foot">New workspace</Link>
                  </div>
                )}
              </div>
            )}
            {me && (
              <div className="pop">
                <button className="avatar-btn" onClick={() => setOpen(open === "me" ? "" : "me")} aria-expanded={open === "me"} aria-label="Account">
                  {me.user.name.slice(0, 1)}
                </button>
                {open === "me" && (
                  <div className="menu right" role="menu">
                    <div className="menu-id"><b>{me.user.name}</b><small>{me.user.email}</small><small>{roles.map((r) => ROLE_LABEL[r]).join(", ")} in {ws?.name}</small></div>
                    {health && (
                      <div className="menu-sys">
                        <span><i className={health.ocr ? "dot on" : "dot"} />Reading images {health.ocr ? "on" : "off"}</span>
                        <span><i className="dot on" />Meaning match {health.semantic?.remote ? "local + Gemini" : "local"}</span>
                        <span><i className={health.ai?.provider ? "dot on" : "dot"} />AI checks {health.ai?.provider || "off"}</span>
                      </div>
                    )}
                    <button role="menuitem" onClick={logout}>Sign out</button>
                  </div>
                )}
              </div>
            )}
            <button className="burger" onClick={() => setOpen(open === "nav" ? "" : "nav")} aria-label="Menu" aria-expanded={open === "nav"}>
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden><path d="M3 5h12M3 9h12M3 13h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
          </div>
          {open === "nav" && <nav className="navsheet" aria-label="Main">{navLinks}</nav>}
        </div>
      </header>
      {down && <div className="notice err">Can't reach the server at <code>{API}</code>. On a free plan it can take up to a minute to wake up.</div>}
      <main key={ws?.id}>{me ? children : <div className="loading">Loading…</div>}</main>
      {me?.user.is_demo ? <footer className="foot">Demo data. Brands are fictional and changes reset when the server restarts.</footer> : null}
      <Toasts toasts={toasts} />
    </SessionCtx.Provider>
  );
}

function Toasts({ toasts }: { toasts: { id: number; msg: string; kind: string }[] }) {
  return <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}</div>;
}
