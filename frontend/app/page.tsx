"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { SubStatus } from "@/components/Badge";
import { api, when } from "@/lib/api";

const CAT_ORDER = ["claim", "term", "tone", "accessibility", "visual"];

export default function Overview() {
  const [ins, setIns] = useState<any>(null);
  const [subs, setSubs] = useState<any[]>([]);
  const router = useRouter();
  useEffect(() => {
    api("/api/insights").then(setIns).catch(() => {});
    api("/api/submissions").then(setSubs).catch(() => {});
  }, []);
  if (!ins) return <p className="muted">Loading…</p>;
  const t = ins.totals;
  const maxCat = Math.max(1, ...Object.values(ins.by_category as Record<string, number>));
  return (
    <div className="stack">
      <div className="head">
        <div>
          <div className="eyebrow">Governance overview</div>
          <h1>Content checked against evidence, before it goes live</h1>
          <p className="lede">Every finding cites its rule, source and location. Reviewers accept, edit or override with a reason. Nothing is auto-published.</p>
        </div>
        <Link href="/preflight" className="btn">Run a preflight</Link>
      </div>

      <div className="grid g5">
        <div className="card kpi"><div className="eyebrow">In review</div><div className="n">{t.submissions.in_review || 0}</div><div className="l">submissions waiting</div></div>
        <div className="card kpi"><div className="eyebrow">Findings</div><div className="n">{t.findings}</div><div className="l">issues raised (excl. supported)</div></div>
        <div className="card kpi"><div className="eyebrow">Override rate</div><div className="n">{Math.round(t.override_rate * 100)}%</div><div className="l">of decided findings</div></div>
        <div className="card kpi"><div className="eyebrow">Active rules</div><div className="n">{t.rules_active}</div><div className="l">{ins.rules_awaiting_validation.length} awaiting validation</div></div>
        <div className="card kpi"><div className="eyebrow">Evidence</div><div className="n">{t.facts}</div><div className="l">approved facts in ledger</div></div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Submissions</h2>
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>Title</th><th>Rev</th><th>Open</th><th>Status</th><th>When</th></tr></thead>
            <tbody>
              {subs.filter((s) => s.status !== "superseded").map((s) => (
                <tr key={s.id} className="click" onClick={() => router.push(`/submissions/${s.id}`)}>
                  <td><b>{s.title}</b><div className="muted small">{s.channel} · {s.author}</div></td>
                  <td className="mono">r{s.revision}</td>
                  <td>{s.pending ? <span className={s.high_pending ? "sev sev-high" : "sev sev-medium"}>{s.pending} pending</span> : <span className="muted">—</span>}</td>
                  <td><SubStatus s={s.status} /></td>
                  <td className="muted small">{when(s.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card stack">
          <h2>Where issues come from</h2>
          {CAT_ORDER.map((c) => (
            <div key={c}>
              <div className="row small"><b style={{ textTransform: "capitalize" }}>{c}</b><span className="spacer" /><span className="mono">{ins.by_category[c] || 0}</span></div>
              <div className="bar"><i style={{ width: `${((ins.by_category[c] || 0) / maxCat) * 100}%` }} /></div>
            </div>
          ))}
          <div className="row small muted" style={{ marginTop: 18 }}>
            {Object.entries(ins.by_status).map(([k, v]) => <span key={k} className="tag">{k}: {v as number}</span>)}
          </div>
        </div>
      </div>

      <div className="grid g3">
        <div className="card">
          <h3>Repeated mistakes</h3>
          <p className="muted small">Rules triggered most often across submissions.</p>
          {ins.repeated_issues.map((r: any) => (
            <div key={r.rule_id} className="row small" style={{ padding: "6px 0", borderTop: "1px solid var(--line)" }}>
              <span style={{ flex: 1 }}>{r.rule_text}</span><span className="mono">{r.hits}×</span>
            </div>
          ))}
        </div>
        <div className="card">
          <h3>Unclear guidelines</h3>
          <p className="muted small">Rules waiting for admin validation, and rules reviewers override often (≥50%).</p>
          {ins.unclear_rules.map((r: any) => (
            <div key={"o" + r.rule_id} className="amb conflict">Overridden {Math.round(r.override_rate * 100)}%: {r.rule_text}</div>
          ))}
          {ins.rules_awaiting_validation.map((r: any) => (
            <div key={r.id} className={"amb" + (r.ambiguity.some((a: any) => a.kind === "conflict") ? " conflict" : "")}>
              <b className="mono small">{r.ambiguity.map((a: any) => a.kind).join(" · ")}</b> — {r.text}
            </div>
          ))}
          <Link href="/sources" className="btn ghost sm" style={{ marginTop: 10, display: "inline-block" }}>Validate rules →</Link>
        </div>
        <div className="card">
          <h3>Missing evidence</h3>
          <p className="muted small">Claims with no approved fact. Unverified, not wrong — candidates for the ledger.</p>
          {ins.missing_evidence.length === 0 && <p className="muted small">None yet.</p>}
          {ins.missing_evidence.map((m: any) => (
            <div key={m.excerpt} className="row small" style={{ padding: "6px 0", borderTop: "1px solid var(--line)" }}>
              <span style={{ flex: 1, fontFamily: "var(--serif)" }}>“{m.excerpt}”</span><span className="mono">{m.count}×</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
