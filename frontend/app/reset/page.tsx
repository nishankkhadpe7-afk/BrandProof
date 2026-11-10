"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Mark, useSession } from "@/components/Shell";
import { ThemeToggle } from "@/components/Theme";
import { api, session } from "@/lib/api";

export default function Reset() {
  const router = useRouter();
  const { toast } = useSession();
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [sent, setSent] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setToken(new URLSearchParams(location.search).get("token")); }, []);

  async function request(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    try { const r = await api("/api/auth/forgot", { method: "POST", body: JSON.stringify({ email }) }); setSent(r.message); }
    catch (x: any) { setErr(x.message); }
    setBusy(false);
  }
  async function reset(e: React.FormEvent) {
    e.preventDefault();
    if (pw !== pw2) { setErr("The two passwords don't match."); return; }
    setBusy(true); setErr("");
    try {
      const r = await api("/api/auth/reset", { method: "POST", body: JSON.stringify({ token, password: pw }) });
      session.set(r.token, r); toast("Password changed. You're signed in."); router.replace("/");
    } catch (x: any) { setErr(x.message); setBusy(false); }
  }

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="row" style={{ justifyContent: "space-between" }}><span className="brand"><Mark /></span><ThemeToggle /></div>
        {token ? (
          <form className="stack" onSubmit={reset}>
            <div><h1>Choose a new password</h1><p className="muted" style={{ marginTop: 6 }}>You'll be signed out on other devices.</p></div>
            <label className="field"><span>New password</span><input type="password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /><small className="hint">At least 8 characters</small></label>
            <label className="field"><span>Repeat it</span><input type="password" required minLength={8} value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" /></label>
            {err && <div className="alert err" role="alert">{err} {err.includes("expired") && <Link href="/reset">Get a new link</Link>}</div>}
            <button className="btn primary wide" disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
          </form>
        ) : sent ? (
          <div className="stack">
            <h1>Check your email</h1>
            <p className="muted">{sent} The link expires in 1 hour.</p>
            <Link href="/login" className="btn wide">Back to sign in</Link>
          </div>
        ) : (
          <form className="stack" onSubmit={request}>
            <div><h1>Reset your password</h1><p className="muted" style={{ marginTop: 6 }}>Enter your account email and we'll send you a link.</p></div>
            <label className="field"><span>Email</span><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
            {err && <div className="alert err" role="alert">{err}</div>}
            <button className="btn primary wide" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
            <Link href="/login" className="muted small">Back to sign in</Link>
          </form>
        )}
      </div>
    </div>
  );
}
