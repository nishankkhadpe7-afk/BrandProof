"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ROLE_DOES, ROLE_LABEL, Role, api, session } from "@/lib/api";
import { Mark, useSession } from "@/components/Shell";
import { ThemeToggle } from "@/components/Theme";

type Demo = { id: number; email: string; name: string; workspaces: { name: string; roles: Role[] }[] };

export default function Login() {
  const router = useRouter();
  const { toast } = useSession();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [f, setF] = useState({ name: "", email: "", password: "", workspace_name: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [demo, setDemo] = useState<Demo[]>([]);
  const [remember, setRemember] = useState(false);

  useEffect(() => {
    api<Demo[]>("/api/auth/demo").then(setDemo).catch(() => {});
    const invite = new URLSearchParams(location.search).get("invite");
    if (invite) { setMode("up"); setF((x) => ({ ...x, email: invite })); }
  }, []);

  async function done(r: any) {
    session.set(r.token, r, remember);
    toast(`Signed in as ${r.user.name}`);
    router.replace("/");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      done(await api(mode === "in" ? "/api/auth/login" : "/api/auth/register", { method: "POST", body: JSON.stringify(f) }));
    } catch (x: any) { setErr(x.message); setBusy(false); }
  }

  async function demoLogin(email: string) {
    setBusy(true); setErr("");
    try { done(await api("/api/auth/demo", { method: "POST", body: JSON.stringify({ email }) })); }
    catch (x: any) { setErr(x.message); setBusy(false); }
  }

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="row" style={{ justifyContent: "space-between" }}><Link href="/welcome" className="brand"><Mark /></Link><ThemeToggle /></div>
        <div>
          <h1>{mode === "in" ? "Sign in" : "Create your account"}</h1>
          <p className="muted" style={{ marginTop: 6 }}>Check marketing content against your brand guidelines and approved facts before it's published.</p>
        </div>
        <div className="seg-full" role="tablist">
          <button role="tab" aria-selected={mode === "in"} className={mode === "in" ? "on" : ""} onClick={() => { setMode("in"); setErr(""); }}>Sign in</button>
          <button role="tab" aria-selected={mode === "up"} className={mode === "up" ? "on" : ""} onClick={() => { setMode("up"); setErr(""); }}>Create account</button>
        </div>
        <form onSubmit={submit} className="stack">
          {mode === "up" && <label className="field"><span>Name</span><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoComplete="name" /></label>}
          <label className="field"><span>Email</span><input required type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" /></label>
          <label className="field"><span>Password</span><input required type="password" minLength={mode === "up" ? 8 : undefined} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete={mode === "in" ? "current-password" : "new-password"} />
            {mode === "up" ? <small className="hint">At least 8 characters</small> : <Link href="/reset" className="small" style={{ alignSelf: "flex-end" }}>Forgot password?</Link>}</label>
          {mode === "up" && <label className="field"><span>Brand workspace</span><input value={f.workspace_name} onChange={(e) => setF({ ...f, workspace_name: e.target.value })} placeholder="e.g. Acme Coffee" />
            <small className="hint">You'll be its admin. Pending invites to your email are added too.</small></label>}
          <label className="check"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Keep me signed in on this device</label>
          {err && <div className="alert err" role="alert">{err}</div>}
          <button className="btn primary wide" disabled={busy}>{busy ? "Please wait…" : mode === "in" ? "Sign in" : "Create account"}</button>
        </form>

        {demo.length > 0 && (<>
          <div className="or">or explore the demo as</div>
          <div className="demo-list">
            {demo.map((d) => {
              const role = (d.workspaces[0]?.roles[0] || "creator") as Role;
              return (
                <button key={d.id} className="demo-card" disabled={busy} onClick={() => demoLogin(d.email)} title={ROLE_DOES[role]}>
                  <span className="avatar" aria-hidden>{d.name[0]}</span>
                  <span>{d.name}</span>
                  <span className="role">{ROLE_LABEL[role]}{d.workspaces.length > 1 ? `, ${d.workspaces.length} brands` : ""}</span>
                </button>
              );
            })}
          </div>
          <p className="muted small demo-creds">
            Using the Figma plugin or the API? Sign in with any demo email, e.g. <code>meera@agency.demo</code> (creator)
            or <code>kabir@lumora.demo</code> (reviewer), password <code>demo-pass-2026</code>.
          </p>
          <p className="muted small">Demo brands and data are fictional.</p>
        </>)}
      </div>
    </div>
  );
}
