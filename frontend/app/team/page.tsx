"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/Shell";
import { ROLE_DOES, ROLE_LABEL, Role, api, has, session, when } from "@/lib/api";

const ALL: Role[] = ["creator", "reviewer", "brand_owner", "admin"];

function RolePicker({ value, onChange, disabled }: { value: Role[]; onChange: (r: Role[]) => void; disabled?: boolean }) {
  return (
    <div className="roles">
      {ALL.map((r) => (
        <label key={r} className={`role-chip ${value.includes(r) ? "on" : ""}`} title={ROLE_DOES[r]}>
          <input type="checkbox" disabled={disabled} checked={value.includes(r)} onChange={() => onChange(value.includes(r) ? value.filter((x) => x !== r) : [...value, r])} />
          {ROLE_LABEL[r]}
        </label>
      ))}
    </div>
  );
}

export default function Team() {
  const { me, roles, toast, refresh } = useSession();
  const router = useRouter();
  const isAdmin = has(roles, "admin");
  const [w, setW] = useState<any>(null);
  const [err, setErr] = useState("");
  const [inv, setInv] = useState<{ email: string; roles: Role[] }>({ email: "", roles: ["creator"] });
  const [nw, setNw] = useState({ name: "", color: "#2346D8" });
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(() => api("/api/workspace").then(setW).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); if (new URLSearchParams(location.search).get("new")) setShowNew(true); }, [load]);

  async function call(p: Promise<any>, msg: string) {
    setErr("");
    try { const r = await p; if (r?.members) setW(r); if (msg) toast(msg); } catch (e: any) { setErr(e.message); }
  }
  const r_ok = "";

  async function createWs(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = await api("/api/workspaces", { method: "POST", body: JSON.stringify({ name: nw.name, color: nw.color }) });
      session.setWorkspace(r.id);
      await refresh();
      toast(`Created ${nw.name}. You're its admin.`);
      router.push("/");
    } catch (x: any) { setErr(x.message); }
  }

  if (!w) return <div className="loading">{err || "Loading…"}</div>;
  return (
    <div className="page narrow">
      <header className="page-h"><div>
        <h1>Team</h1>
        <p className="lede">People in <b>{w.name}</b> and what they can do. Each brand workspace has its own members, rules, facts and activity log, so an agency can work on several brands without mixing them up.</p>
      </div>
        <button className="btn ghost" onClick={() => setShowNew(!showNew)}>New workspace</button>
      </header>
      {err && <div className="alert err" role="alert">{err}</div>}

      {showNew && (
        <form className="panel stack" onSubmit={createWs}>
          <h3>Create a brand workspace</h3>
          <div className="row">
            <label className="field grow"><span>Brand name</span><input required value={nw.name} onChange={(e) => setNw({ ...nw, name: e.target.value })} placeholder="e.g. Acme Coffee" /></label>
            <label className="field"><span>Colour</span><input type="color" value={nw.color} onChange={(e) => setNw({ ...nw, color: e.target.value })} /></label>
          </div>
          <div className="row"><button className="btn primary">Create workspace</button><span className="muted small">It starts empty. You'll be its admin.</span></div>
        </form>
      )}

      <section className="panel">
        <h2>Members</h2>
        <ul className="members">
          {w.members.map((m: any) => (
            <li key={m.id}>
              <span className="avatar" aria-hidden>{m.name[0]}</span>
              <span className="grow"><b>{m.name}{m.id === me?.user.id ? " (you)" : ""}</b><small>{m.email} · joined {when(m.created_at)}</small></span>
              <RolePicker value={m.roles} disabled={!isAdmin} onChange={(r) => call(api(`/api/workspace/members/${m.id}`, { method: "PATCH", body: JSON.stringify({ roles: r }) }), "Roles updated")} />
              {isAdmin && m.id !== me?.user.id && <button className="link danger" onClick={() => confirm(`Remove ${m.name} from ${w.name}?`) && call(api(`/api/workspace/members/${m.id}`, { method: "DELETE" }), "Member removed")}>Remove</button>}
            </li>
          ))}
        </ul>
        {w.invitations.length > 0 && (<>
          <h3 style={{ marginTop: 18 }}>Invited, not joined yet</h3>
          <ul className="members">{w.invitations.map((i: any) => (
            <li key={i.id}><span className="avatar ghost" aria-hidden>@</span><span className="grow"><b>{i.email}</b><small>{i.roles.map((r: Role) => ROLE_LABEL[r]).join(", ")} · invited by {i.invited_by}</small></span>
              {isAdmin && <button className="link danger" onClick={() => call(api(`/api/workspace/invitations/${i.id}`, { method: "DELETE" }), "Invitation cancelled")}>Cancel</button>}</li>
          ))}</ul>
        </>)}
      </section>

      {isAdmin ? (
        <form className="panel stack" onSubmit={(e) => { e.preventDefault(); { const to = inv.email; call(api("/api/workspace/members", { method: "POST", body: JSON.stringify(inv) }).then((r) => { setInv({ email: "", roles: ["creator"] }); toast(r.email_sent ? `Email sent to ${to}` : r.status === "added" ? `${to} added` : `Invitation saved for ${to} (email isn't set up on the server)`); return r; }), r_ok); } }}>
          <h3>Add someone</h3>
          <label className="field"><span>Email</span><input type="email" required value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} placeholder="name@company.com" /></label>
          <div className="field"><span>Roles</span><RolePicker value={inv.roles} onChange={(r) => setInv({ ...inv, roles: r })} /></div>
          <div className="row"><button className="btn primary" disabled={!inv.roles.length}>Add to workspace</button>
            <span className="muted small">They get an email. If they already have an account they're added now; otherwise they join when they sign up with this email.</span></div>
        </form>
      ) : <p className="muted">Only admins can add people or change roles.</p>}

      <section className="panel">
        <h3>What each role can do</h3>
        <dl className="role-help">{ALL.map((r) => <div key={r}><dt>{ROLE_LABEL[r]}</dt><dd>{ROLE_DOES[r]}</dd></div>)}</dl>
      </section>
    </div>
  );
}
