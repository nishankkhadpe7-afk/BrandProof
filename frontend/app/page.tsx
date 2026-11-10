"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { SubStatus } from "@/components/Badge";
import { useSession } from "@/components/Shell";
import { ROLE_LABEL, api, has, when } from "@/lib/api";

const CATS: [string, string][] = [["claim", "Claims"], ["term", "Terminology"], ["tone", "Tone"], ["accessibility", "Accessibility"], ["visual", "Visuals"]];

export default function Overview() {
  const { me, ws, roles } = useSession();
  const [ins, setIns] = useState<any>(null);
  const [subs, setSubs] = useState<any[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    api("/api/insights").then(setIns).catch((e) => setErr(e.message));
    api("/api/submissions").then(setSubs).catch(() => {});
  }, []);
  if (err) return <div className="alert err">{err}</div>;
  if (!ins) return <div className="loading">Loading…</div>;

  const t = ins.totals;
  const open = subs.filter((s) => s.status === "in_review" || s.status === "changes_requested");
  const mine = open.filter((s) => s.author === me?.user.name);
  const needsReview = open.filter((s) => s.high_pending === 0 && s.pending === 0);
  const setup = [
    { done: t.sources > 0, label: "Upload your brand guidelines", href: "/sources?tab=upload", who: has(roles, "admin", "brand_owner") },
    { done: t.rules_active > 0, label: "Check and switch on the rules BrandProof proposed", href: "/sources", who: has(roles, "admin", "brand_owner") },
    { done: t.facts > 0, label: "Add approved product facts (specs, prices, warranties)", href: "/sources?tab=facts", who: has(roles, "admin", "brand_owner") },
    { done: subs.length > 0, label: "Check your first piece of content", href: "/preflight", who: has(roles, "creator", "admin", "brand_owner") },
  ];
  const setupLeft = setup.filter((s) => !s.done).length;
  const maxCat = Math.max(1, ...Object.values(ins.by_category as Record<string, number>));
  const first = me?.user.name.split(" ")[0];

  return (
    <div className="page">
      <header className="page-h">
        <div>
          <h1>{ws?.name}</h1>
          <p className="lede small">Signed in as {first} · {roles.map((r) => ROLE_LABEL[r]).join(", ")}</p>
        </div>
        {has(roles, "creator", "admin", "brand_owner") && <Link href="/preflight" className="btn primary">Check content</Link>}
      </header>

      {setupLeft > 0 && (
        <section className="panel setup">
          <h2>Finish setting up</h2>
          <p className="muted small">{4 - setupLeft} of 4 done. BrandProof checks content against what you add here.</p>
          <ol className="checklist">
            {setup.map((s) => (
              <li key={s.label} className={s.done ? "done" : ""}>
                <span className="tick" aria-hidden>{s.done ? "✓" : ""}</span>
                {s.done || !s.who ? <span>{s.label}{!s.done && !s.who && <span className="muted"> (needs an admin or brand owner)</span>}</span> : <Link href={s.href}>{s.label}</Link>}
              </li>
            ))}
          </ol>
        </section>
      )}

      <dl className="stats-row">
        <div className="stat"><dt>Waiting for a decision</dt><dd>{open.length}</dd>{open.length > 0 && <Link href="/submissions">Open queue</Link>}</div>
        {has(roles, "reviewer", "brand_owner") && <div className="stat"><dt>Ready to approve</dt><dd>{needsReview.length}</dd></div>}
        {has(roles, "creator") && <div className="stat"><dt>Your drafts in review</dt><dd>{mine.length}</dd></div>}
        {has(roles, "admin", "brand_owner") && <div className="stat"><dt>Rules to check</dt><dd>{ins.rules_awaiting_validation.length}</dd>{ins.rules_awaiting_validation.length > 0 && <Link href="/sources">Review rules</Link>}</div>}
        <div className="stat"><dt>Caught by meaning</dt><dd>{ins.by_engine?.semantic || 0}</dd></div>
      </dl>

      <div className="cols">
        <section>
          <div className="section-h"><h2>Recent content</h2><Link href="/submissions" className="link">View all</Link></div>
          {subs.length === 0 ? <p className="muted">No content checked yet.</p> : (
            <ul className="list">
              {subs.filter((s) => s.status !== "superseded").slice(0, 7).map((s) => (
                <li key={s.id}>
                  <Link href={`/submissions/${s.id}`} className="list-row">
                    <span className="kind" aria-hidden>{s.kind === "image" ? "IMG" : s.kind === "pdf" ? "PDF" : "TXT"}</span>
                    <span className="grow"><b>{s.title}</b><small>{s.author}, {s.channel}, {when(s.created_at)}</small></span>
                    {s.pending > 0 && <span className={`count ${s.high_pending ? "hi" : ""}`}>{s.pending} open</span>}
                    {["queued", "running"].includes(s.check_status) ? <span className="pill sub-in_review">Checking</span> : <SubStatus s={s.status} />}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <div className="section-h"><h2>Issues by type</h2><span className="muted small">Override rate {Math.round(t.override_rate * 100)}%</span></div>
          <div className="bars">
            {CATS.map(([c, l]) => (
              <div key={c} className="barrow">
                <span>{l}</span>
                <span className="bar-track"><i style={{ width: `${((ins.by_category[c] || 0) / maxCat) * 100}%` }} /></span>
                <span className="num">{ins.by_category[c] || 0}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="cols three">
        <section>
          <h3>Repeated mistakes</h3>
          <p className="muted small">Guidelines broken most often.</p>
          {ins.repeated_issues.length === 0 ? <p className="muted small">None yet.</p> : ins.repeated_issues.slice(0, 5).map((r: any) => (
            <div key={r.rule_id} className="mini"><span>{r.rule_text}</span><b>{r.hits}</b></div>
          ))}
        </section>
        <section>
          <h3>Unclear guidelines</h3>
          <p className="muted small">Overridden half the time or more. Probably need rewording.</p>
          {ins.unclear_rules.length === 0 && <div className="mini"><span className="muted">None flagged</span></div>}
          {ins.unclear_rules.map((r: any) => <div key={r.rule_id} className="mini"><span>{r.rule_text}</span><b>{Math.round(r.override_rate * 100)}%</b></div>)}
        </section>
        <section>
          <h3>Missing evidence</h3>
          <p className="muted small">Claims no approved fact covers yet.</p>
          {ins.missing_evidence.length === 0 ? <div className="mini"><span className="muted">None yet</span></div> : ins.missing_evidence.map((m: any) => (
            <div key={m.excerpt} className="mini"><q>{m.excerpt}</q><b>{m.count}</b></div>
          ))}
        </section>
      </div>
    </div>
  );
}
