"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Sev, Status, SubStatus } from "@/components/Badge";
import { useRole } from "@/components/Shell";
import { API, Finding, api, when } from "@/lib/api";

const LONG = 60;

function Highlighted({ text, findings, sel, onPick }: { text: string; findings: Finding[]; sel: number | null; onPick: (id: number) => void }) {
  const spans = findings.filter((f) => f.start !== null && f.end !== null) as (Finding & { start: number; end: number })[];
  const cuts = new Set<number>([0, text.length]);
  spans.forEach((f) => { cuts.add(f.start); cuts.add(f.end); });
  const pts = [...cuts].sort((a, b) => a - b);
  const out: React.ReactNode[] = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    // zero-length insertions (e.g. missing disclaimer)
    spans.filter((f) => f.start === a && f.end === a).forEach((f) =>
      out.push(<mark key={`ins${f.id}`} className={`m-${f.status} ${sel === f.id ? "sel" : ""}`} onClick={() => onPick(f.id)} title={f.reason}> ⟂ missing disclaimer</mark>));
    if (i === pts.length - 1) break;
    const b = pts[i + 1];
    const seg = text.slice(a, b);
    const cover = spans.filter((f) => f.start <= a && f.end >= b && f.end > f.start);
    const short = cover.filter((f) => f.end - f.start <= LONG).sort((x, y) => x.end - x.start - (y.end - y.start))[0];
    const long = cover.find((f) => f.end - f.start > LONG);
    let node: React.ReactNode = seg;
    if (short) {
      const done = short.decision !== "pending" && short.decision !== "n/a";
      node = <mark className={`m-${short.status} ${sel === short.id ? "sel" : ""} ${done ? "done" : ""}`} onClick={() => onPick(short.id)} title={short.reason}>{seg}</mark>;
    }
    if (long) node = <span className="long" onClick={() => !short && onPick(long.id)} title={long.reason}>{node}</span>;
    out.push(<Fragment key={a}>{node}</Fragment>);
  }
  return <div className="doc">{out}</div>;
}

function FindingCard({ f, sel, role, locked, onPick, onDecide }: {
  f: Finding; sel: boolean; role: string; locked: boolean; onPick: () => void;
  onDecide: (decision: string, extra?: { text?: string; reason?: string }) => Promise<void>;
}) {
  const [mode, setMode] = useState<"" | "edit" | "override">("");
  const [val, setVal] = useState("");
  const canOverride = role === "reviewer" || role === "brand_owner";
  const canFix = role !== "admin";
  const decided = f.decision !== "pending" && f.decision !== "n/a";
  return (
    <div id={`f${f.id}`} className={`finding f-${f.status} ${sel ? "sel" : ""}`} onClick={onPick}>
      <div className="row">
        <Status s={f.status} />
        <span className="tag">{f.category}</span>
        <Sev s={f.severity} />
        <span className="spacer" />
        <span className={`tag ${f.engine === "ai" ? "ai" : ""}`}>{f.engine} · {Math.round(f.confidence * 100)}%</span>
      </div>
      <div className="trigger">“{f.excerpt}”</div>
      <dl className="kv">
        {f.rule_text && (<><dt>Rule</dt><dd>{f.rule_text}</dd></>)}
        {f.fact_label && (<><dt>Evidence</dt><dd>{f.fact_label}: <b>{f.fact_value}</b></dd></>)}
        {f.source_ref && (<><dt>Source</dt><dd className="mono">{f.source_ref}</dd></>)}
        <dt>Why</dt><dd>{f.reason}</dd>
        {f.suggestion && (<><dt>Suggested</dt><dd><span className="sugg">{f.suggestion.trim()}</span></dd></>)}
      </dl>
      {decided && (
        <div className="decided">
          <b style={{ textTransform: "capitalize" }}>{f.decision}</b> by {f.decided_by}
          {f.decision_text != null && <> → <span className="sugg">{f.decision_text}</span></>}
          {f.decision_reason && <div className="muted">Reason: {f.decision_reason}</div>}
        </div>
      )}
      {!locked && f.decision !== "n/a" && (
        <div className="actions" onClick={(e) => e.stopPropagation()}>
          {!decided && mode === "" && (<>
            {f.suggestion != null && canFix && <button className="btn green sm" onClick={() => onDecide("accepted")}>Accept fix</button>}
            {canFix && <button className="btn ghost sm" onClick={() => { setMode("edit"); setVal(f.suggestion?.trim() ?? f.excerpt); }}>Edit</button>}
            {canOverride && <button className="btn ghost sm" onClick={() => { setMode("override"); setVal(""); }}>Override…</button>}
          </>)}
          {mode !== "" && (<>
            <input autoFocus value={val} onChange={(e) => setVal(e.target.value)} placeholder={mode === "edit" ? "Replacement text" : "Reason for override (required, logged)"} style={{ flex: 1, minWidth: 200 }} />
            <button className="btn sm" disabled={mode === "override" && !val.trim()}
              onClick={async () => { await onDecide(mode === "edit" ? "edited" : "overridden", mode === "edit" ? { text: val } : { reason: val }); setMode(""); }}>Save</button>
            <button className="btn ghost sm" onClick={() => setMode("")}>Cancel</button>
          </>)}
          {decided && <button className="btn ghost sm" onClick={() => onDecide("pending")}>Undo</button>}
        </div>
      )}
    </div>
  );
}

export default function Review() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const role = useRole();
  const [s, setS] = useState<any>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const [reason, setReason] = useState("");
  const [filter, setFilter] = useState("open");

  const load = useCallback(() => api(`/api/submissions/${id}`).then(setS).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { load(); }, [load]);

  const pick = (fid: number) => {
    setSel(fid);
    document.getElementById(`f${fid}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const findings: Finding[] = s?.findings || [];
  const shown = useMemo(() => findings.filter((f) =>
    filter === "all" ? true : filter === "open" ? f.decision === "pending" : filter === "supported" ? f.status === "supported" : f.decision !== "pending" && f.decision !== "n/a"),
    [findings, filter]);
  if (!s) return <p className="muted">{err || "Loading…"}</p>;

  const locked = !["in_review", "changes_requested"].includes(s.status);
  const blocking = findings.filter((f) => f.decision === "pending" && (f.severity === "high" || f.severity === "medium"));
  const fixes = findings.filter((f) => (f.decision === "accepted" || f.decision === "edited") && f.start !== null).length;
  const counts = findings.reduce<Record<string, number>>((m, f) => ((m[f.status] = (m[f.status] || 0) + 1), m), {});
  const regionF = findings.find((f) => f.id === sel && f.region) || null;

  async function decide(fid: number, decision: string, extra: { text?: string; reason?: string } = {}) {
    setErr("");
    try { await api(`/api/findings/${fid}/decision`, { method: "POST", body: JSON.stringify({ decision, ...extra }) }); await load(); }
    catch (e: any) { setErr(e.message); }
  }
  async function setStatus(status: string) {
    setErr("");
    try { await api(`/api/submissions/${id}/status`, { method: "POST", body: JSON.stringify({ status, reason }) }); setReason(""); await load(); }
    catch (e: any) { setErr(e.message); }
  }
  async function revise() {
    setErr("");
    try { const n = await api(`/api/submissions/${id}/revise`, { method: "POST" }); router.push(`/submissions/${n.id}`); }
    catch (e: any) { setErr(e.message); }
  }

  return (
    <div className="stack">
      <div className="head">
        <div>
          <div className="eyebrow">Preflight · {s.channel} · revision {s.revision} · by {s.author}</div>
          <h1>{s.title}</h1>
          <div className="row" style={{ marginTop: 10 }}>
            <SubStatus s={s.status} />
            {Object.entries(counts).map(([k, v]) => <span key={k} className="row small"><Status s={k} /> <b>{v}</b></span>)}
          </div>
        </div>
        <div className="row">
          {s.history.length > 0 && <Link className="btn ghost sm" href={`/submissions/${s.history[0].id}`}>← rev {s.history[0].revision}</Link>}
          {s.next_revision && <Link className="btn ghost sm" href={`/submissions/${s.next_revision.id}`}>rev {s.next_revision.revision} →</Link>}
        </div>
      </div>

      {err && <div className="amb conflict err">{err}</div>}

      <div className="review">
        <div className="stack">
          <div className="card">
            <div className="row" style={{ marginBottom: 12 }}>
              <h3>Content</h3><span className="spacer" />
              <div className="legend">
                <span><i style={{ background: "var(--red)" }} />contradicted</span>
                <span><i style={{ background: "var(--amber)" }} />expired</span>
                <span><i style={{ background: "var(--purple)" }} />conflicting</span>
                <span><i style={{ background: "var(--slate)" }} />unverified</span>
                <span><i style={{ background: "var(--orange)" }} />rule</span>
                <span><i style={{ background: "var(--green)" }} />supported</span>
              </div>
            </div>
            {s.has_image && (
              <div className="imgwrap" style={{ marginBottom: 14 }}>
                <img src={`${API}/api/submissions/${id}/image`} alt={s.alt_text || "Submitted image (no alt text provided)"} />
                {findings.filter((f) => f.region && (!regionF || f.id === regionF.id)).map((f) => (
                  <div key={f.id} className="region" style={{ left: `${(f.region!.x / f.region!.img_w) * 100}%`, top: `${(f.region!.y / f.region!.img_h) * 100}%`, width: `${(f.region!.w / f.region!.img_w) * 100}%`, height: `${(f.region!.h / f.region!.img_h) * 100}%` }} />
                ))}
              </div>
            )}
            {s.text ? <Highlighted text={s.text} findings={findings} sel={sel} onPick={pick} /> : <p className="muted">No text content.</p>}
          </div>

          <div className="card stack">
            <h3>Decision</h3>
            {locked ? (
              <div className="gate">This revision is <b>{s.status.replace("_", " ")}</b>; decisions are locked.</div>
            ) : (
              <>
                <div className="gate">
                  {blocking.length ? <>Approval blocked: <b>{blocking.length}</b> high/medium finding(s) still pending. Each must be accepted, edited or overridden with a reason.</> : <>All blocking findings resolved. A reviewer can approve.</>}
                </div>
                <div className="row">
                  <button className="btn" disabled={!fixes || role === "admin" || s.kind === "image"} onClick={revise}>Apply {fixes} fix{fixes === 1 ? "" : "es"} → new revision</button>
                  <span className="muted small">{s.kind === "image" ? "Images: upload a corrected file as a new preflight." : "Re-runs the preflight on the corrected text."}</span>
                </div>
                {(role === "reviewer" || role === "brand_owner") ? (
                  <div className="row">
                    <button className="btn green" disabled={blocking.length > 0} onClick={() => setStatus("approved")}>Approve</button>
                    <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (for changes / reject)" style={{ flex: 1, minWidth: 160 }} />
                    <button className="btn ghost" disabled={!reason.trim()} onClick={() => setStatus("changes_requested")}>Request changes</button>
                    <button className="btn red" disabled={!reason.trim()} onClick={() => setStatus("rejected")}>Reject</button>
                  </div>
                ) : <p className="muted small">Switch to Reviewer to override, approve or reject.</p>}
              </>
            )}
          </div>

          <div className="card">
            <h3 style={{ marginBottom: 12 }}>Decision trail</h3>
            <div className="timeline">
              {s.audit.map((a: any) => (
                <div key={a.id} className="ev">
                  <span className="mono small muted">{when(a.ts)}</span> · <b>{a.actor}</b> <span className="tag">{a.role}</span> {a.action}
                  {a.detail?.reason && <div className="muted">“{a.detail.reason}”</div>}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="findings">
          <div className="tabs" style={{ marginBottom: 12 }}>
            {[["open", "Open"], ["decided", "Decided"], ["supported", "Supported"], ["all", "All"]].map(([k, l]) => (
              <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
            ))}
          </div>
          {shown.length === 0 && <p className="muted">Nothing here.</p>}
          {shown.map((f) => (
            <FindingCard key={f.id} f={f} sel={sel === f.id} role={role} locked={locked} onPick={() => setSel(f.id)} onDecide={(d, x) => decide(f.id, d, x)} />
          ))}
        </div>
      </div>
    </div>
  );
}
