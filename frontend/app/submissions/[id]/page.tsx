"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AuthImage, Sev, Status, SubStatus } from "@/components/Badge";
import { useSession } from "@/components/Shell";
import { Finding, STATUS_LABEL, api, has, when } from "@/lib/api";

const LONG = 60;
const ENGINE: Record<string, string> = { deterministic: "Exact rule", semantic: "Matched by meaning", ai: "AI", };

function Highlighted({ text, findings, sel, onPick }: { text: string; findings: Finding[]; sel: number | null; onPick: (id: number) => void }) {
  const spans = findings.filter((f) => f.start !== null && f.end !== null) as (Finding & { start: number; end: number })[];
  const cuts = new Set<number>([0, text.length]);
  spans.forEach((f) => { cuts.add(Math.min(f.start, text.length)); cuts.add(Math.min(f.end, text.length)); });
  const pts = [...cuts].sort((a, b) => a - b);
  const out: React.ReactNode[] = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    spans.filter((f) => f.start === a && f.end === a).forEach((f) =>
      out.push(<button key={`ins${f.id}`} className={`caret m-${f.status} ${sel === f.id ? "sel" : ""}`} onClick={() => onPick(f.id)} title={f.reason}>missing disclaimer</button>));
    if (i === pts.length - 1) break;
    const b = pts[i + 1];
    const seg = text.slice(a, b);
    const cover = spans.filter((f) => f.start <= a && f.end >= b && f.end > f.start);
    const short = cover.filter((f) => f.end - f.start <= LONG).sort((x, y) => x.end - x.start - (y.end - y.start))[0];
    const long = cover.find((f) => f.end - f.start > LONG);
    let node: React.ReactNode = seg;
    if (short) {
      const done = short.decision !== "pending" && short.decision !== "n/a";
      node = <mark className={`m-${short.status} ${sel === short.id ? "sel" : ""} ${done ? "done" : ""}`} onClick={() => onPick(short.id)} title={STATUS_LABEL[short.status]}>{seg}</mark>;
    }
    if (long) node = <span className={`long ${sel === long.id ? "sel" : ""}`} onClick={() => !short && onPick(long.id)}>{node}</span>;
    out.push(<Fragment key={a}>{node}</Fragment>);
  }
  return <div className="doc">{out}</div>;
}

function Creative({ sid, pages, findings, sel, onPick, alt }: { sid: number; pages: number; findings: Finding[]; sel: number | null; onPick: (id: number) => void; alt: string }) {
  const selF = findings.find((f) => f.id === sel);
  const [page, setPage] = useState(0);
  useEffect(() => { if (selF?.region?.page != null) setPage(selF.region.page); }, [selF]);
  const boxes = findings.filter((f) => f.region && (f.region.page ?? 0) === page);
  return (
    <div className="creative">
      {pages > 1 && <div className="seg sm">{Array.from({ length: pages }, (_, i) => <button key={i} className={page === i ? "on" : ""} onClick={() => setPage(i)}>Page {i + 1}</button>)}</div>}
      <div className="imgwrap">
        <AuthImage path={`/api/submissions/${sid}/image?page=${page}`} alt={alt} />
        {boxes.map((f) => {
          const r = f.region!;
          return <button key={f.id} className={`region r-${f.status} ${sel === f.id ? "sel" : ""} ${sel && sel !== f.id ? "dim" : ""}`} aria-label={`${STATUS_LABEL[f.status]}: ${f.excerpt}`}
            onClick={() => onPick(f.id)}
            style={{ left: `${(r.x / r.img_w) * 100}%`, top: `${(r.y / r.img_h) * 100}%`, width: `${(r.w / r.img_w) * 100}%`, height: `${(r.h / r.img_h) * 100}%` }} />;
        })}
      </div>
    </div>
  );
}

function FindingCard({ f, sel, roles, locked, onPick, onDecide }: {
  f: Finding; sel: boolean; roles: any[]; locked: boolean; onPick: () => void;
  onDecide: (decision: string, extra?: { text?: string; reason?: string }) => Promise<void>;
}) {
  const [mode, setMode] = useState<"" | "edit" | "override">("");
  const [val, setVal] = useState("");
  const [why, setWhy] = useState(false);
  const canOverride = has(roles, "reviewer", "brand_owner");
  const canFix = has(roles, "creator", "reviewer", "brand_owner");
  const decided = f.decision !== "pending" && f.decision !== "n/a";
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (sel) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [sel]);
  return (
    <div ref={ref} id={`f${f.id}`} className={`finding f-${f.status} ${sel ? "sel" : ""} ${decided ? "is-done" : ""}`} onClick={onPick} tabIndex={-1}>
      <div className="f-top">
        <Status s={f.status} />
        <Sev s={f.severity} />
        <span className="f-cat">{f.category}</span>
        <span className="grow" />
        <span className={`engine e-${f.engine}`} title={`Confidence ${Math.round(f.confidence * 100)}%`}>{ENGINE[f.engine] || f.engine}</span>
      </div>
      <q className="trigger">{f.excerpt}</q>
      <p className="f-reason">{f.reason}</p>
      {f.suggestion && <div className="f-sugg"><span>Suggested</span><b>{f.suggestion.trim()}</b></div>}
      <dl className="f-meta">
        {f.fact_label && <><dt>Approved fact</dt><dd>{f.fact_label}: {f.fact_value}</dd></>}
        {f.rule_text && <><dt>Guideline</dt><dd>{f.rule_text}</dd></>}
        {f.source_ref && <><dt>Source</dt><dd>{f.source_ref}</dd></>}
        {f.region?.source === "ocr" && <><dt>Location</dt><dd>Text read from the image{f.region.page ? `, page ${f.region.page + 1}` : ""}</dd></>}
      </dl>
      {f.match && (
        <div className="why" onClick={(e) => e.stopPropagation()}>
          <button className="link" onClick={() => setWhy(!why)} aria-expanded={why}>{why ? "Hide" : "Why this fact?"}</button>
          {why && (
            <div className="why-body">
              {f.match.interpretation && <p>Interpreted as: {f.match.interpretation}</p>}
              <p className="muted small">Closest approved facts by meaning ({f.match.model}):</p>
              {f.match.retrieved.map((r) => (
                <div key={r.fact_id} className="simrow"><span>{r.label}</span><span className="bar-track"><i style={{ width: `${Math.max(0, Math.min(1, r.score)) * 100}%` }} /></span><span className="num">{r.score.toFixed(2)}</span></div>
              ))}
            </div>
          )}
        </div>
      )}
      {decided && (
        <div className="decided">
          {f.decision === "accepted" ? "Fix accepted" : f.decision === "edited" ? "Edited" : "Overridden"} by {f.decided_by}
          {f.decision_text != null && <> → <b>{f.decision_text}</b></>}
          {f.decision_reason && <div className="muted">Reason: {f.decision_reason}</div>}
        </div>
      )}
      {!locked && f.decision !== "n/a" && (
        <div className="actions" onClick={(e) => e.stopPropagation()}>
          {!decided && mode === "" && (<>
            {f.suggestion != null && canFix && <button className="btn ok sm" onClick={() => onDecide("accepted")}>Accept fix</button>}
            {canFix && f.start !== null && <button className="btn ghost sm" onClick={() => { setMode("edit"); setVal(f.suggestion?.trim() ?? f.excerpt); }}>Write my own fix</button>}
            {canOverride && <button className="btn ghost sm" onClick={() => { setMode("override"); setVal(""); }}>Keep as is…</button>}
          </>)}
          {mode !== "" && (
            <form className="inline-form" onSubmit={async (e) => { e.preventDefault(); await onDecide(mode === "edit" ? "edited" : "overridden", mode === "edit" ? { text: val } : { reason: val }); setMode(""); }}>
              <input autoFocus value={val} onChange={(e) => setVal(e.target.value)} placeholder={mode === "edit" ? "Replacement text" : "Why is this OK to publish? (saved to the log)"} />
              <button className="btn primary sm" disabled={mode === "override" && !val.trim()}>{mode === "edit" ? "Save fix" : "Override"}</button>
              <button type="button" className="btn ghost sm" onClick={() => setMode("")}>Cancel</button>
            </form>
          )}
          {decided && <button className="link" onClick={() => onDecide("pending")}>Undo</button>}
          {!decided && mode === "" && !canFix && !canOverride && <span className="muted small">Your role can view this finding but not decide it.</span>}
        </div>
      )}
    </div>
  );
}

export default function Review() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { roles, toast } = useSession();
  const [s, setS] = useState<any>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const [reason, setReason] = useState("");
  const [filter, setFilter] = useState("open");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"content" | "trail">("content");
  const upload = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api(`/api/submissions/${id}`).then(setS).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { load(); }, [load]);
  const checking = !!s && ["queued", "running"].includes(s.check_status);
  useEffect(() => {
    if (!checking) return;
    const t = setTimeout(load, 1500);  // poll while the background check runs
    return () => clearTimeout(t);
  }, [s, checking, load]);

  const findings: Finding[] = s?.findings || [];
  const shown = useMemo(() => findings.filter((f) =>
    filter === "all" ? true : filter === "open" ? f.decision === "pending" : filter === "supported" ? f.status === "supported" : f.decision !== "pending" && f.decision !== "n/a"),
    [findings, filter]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input,textarea,select")) return;
      if (e.key !== "j" && e.key !== "k") return;
      const i = shown.findIndex((f) => f.id === sel);
      const n = shown[e.key === "j" ? Math.min(shown.length - 1, i + 1) : Math.max(0, i - 1)];
      if (n) setSel(n.id);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [shown, sel]);

  if (!s) return err ? <div className="page"><div className="alert err">{err}</div><Link href="/submissions">Back to the queue</Link></div> : <div className="loading">Loading…</div>;

  const locked = !["in_review", "changes_requested"].includes(s.status) || s.check_status !== "done";
  const actionable = findings.filter((f) => f.decision !== "n/a");
  const done = actionable.filter((f) => f.decision !== "pending").length;
  const blocking = findings.filter((f) => f.decision === "pending" && (f.severity === "high" || f.severity === "medium"));
  const fixes = findings.filter((f) => (f.decision === "accepted" || f.decision === "edited") && f.start !== null).length;
  const isCreative = s.kind === "image" || s.pages > 0;
  const canReview = has(roles, "reviewer", "brand_owner");
  const canFix = has(roles, "creator", "reviewer", "brand_owner");

  async function decide(fid: number, decision: string, extra: { text?: string; reason?: string } = {}) {
    setErr("");
    try {
      await api(`/api/findings/${fid}/decision`, { method: "POST", body: JSON.stringify({ decision, ...extra }) });
      await load();
      if (decision !== "pending") {
        const next = findings.find((f) => f.id !== fid && f.decision === "pending");
        if (next) setSel(next.id);
      }
    } catch (e: any) { setErr(e.message); }
  }
  async function setStatus(status: string) {
    setErr(""); setBusy(true);
    try {
      await api(`/api/submissions/${id}/status`, { method: "POST", body: JSON.stringify({ status, reason }) });
      setReason(""); await load();
      toast(status === "approved" ? "Approved" : status === "rejected" ? "Rejected" : "Changes requested");
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  async function revise() {
    setErr(""); setBusy(true);
    try { const n = await api(`/api/submissions/${id}/revise`, { method: "POST" }); toast(`Revision ${n.revision} created and re-checked`); router.push(`/submissions/${n.id}`); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  }
  async function reviseUpload(file: File) {
    setErr(""); setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    try { const n = await api(`/api/submissions/${id}/revise-upload`, { method: "POST", body: fd }); toast(`Revision ${n.revision} uploaded and re-checked`); router.push(`/submissions/${n.id}`); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  }

  const counts = actionable.reduce<Record<string, number>>((m, f) => ((m[f.status] = (m[f.status] || 0) + 1), m), {});

  return (
    <div className="page wide">
      <div className="crumbs"><Link href="/submissions">Review queue</Link> <span aria-hidden>/</span> {s.title}</div>
      <header className="page-h">
        <div>
          <h1>{s.title}</h1>
          <p className="lede small">{s.author} · {s.channel} · {when(s.created_at)} · revision {s.revision}
            {s.ocr_engine && <> · text read with {s.ocr_engine === "tesseract" ? "OCR" : s.ocr_engine} ({s.ocr_words || 0} words)</>}</p>
          <div className="row" style={{ marginTop: 10 }}>
            <SubStatus s={s.status} />
            {Object.entries(counts).map(([k, v]) => <span key={k} className="row tight"><Status s={k} /><span className="num">{v}</span></span>)}
          </div>
        </div>
        <div className="row">
          {s.history.length > 0 && <Link className="btn ghost sm" href={`/submissions/${s.history[0].id}`}>Previous revision</Link>}
          {s.next_revision && <Link className="btn primary sm" href={`/submissions/${s.next_revision.id}`}>Go to revision {s.next_revision.revision}</Link>}
        </div>
      </header>

      {err && <div className="alert err" role="alert">{err}</div>}
      {checking && (
        <div className="checking" role="status">
          <span className="spinner" aria-hidden />
          <div><b>{s.check_status === "queued" ? "Waiting to check…" : "Checking…"}</b>
            <small>{s.kind === "text" ? "Matching claims against approved facts and rules." : "Reading text in the file, then matching claims against approved facts and rules."} This page updates by itself.</small></div>
        </div>
      )}
      {s.check_status === "failed" && (
        <div className="alert err row" role="alert">
          <span className="grow">The check didn't finish{s.check_error ? `: ${s.check_error}` : "."}</span>
          <button className="btn sm" onClick={async () => { try { await api(`/api/submissions/${id}/recheck`, { method: "POST" }); await load(); } catch (e: any) { setErr(e.message); } }}>Check again</button>
        </div>
      )}

      <div className="review">
        <div className="stack">
          <div className="panel">
            <div className="seg sm" style={{ marginBottom: 14 }}>
              <button className={tab === "content" ? "on" : ""} onClick={() => setTab("content")}>Content</button>
              <button className={tab === "trail" ? "on" : ""} onClick={() => setTab("trail")}>Decision trail ({s.audit.length})</button>
            </div>
            {tab === "content" ? (<>
              {isCreative && s.pages > 0 && <Creative sid={s.id} pages={s.pages} findings={findings} sel={sel} onPick={setSel} alt={s.alt_text || "Submitted creative (no alt text provided)"} />}
              {isCreative && s.text && <h3 className="sub-h">Text read from the {s.kind === "image" ? "image" : "scan"}</h3>}
              {s.text ? <Highlighted text={s.text} findings={findings} sel={sel} onPick={setSel} /> : <p className="muted">{isCreative ? "No text was found in this file." : "No text content."}</p>}
              <div className="legend">
                {["contradicted", "expired", "conflicting", "unverified", "violation", "supported"].map((k) => <span key={k}><i className={`lg-${k}`} />{STATUS_LABEL[k]}</span>)}
              </div>
            </>) : (
              <ol className="timeline">
                {s.audit.map((a: any) => (
                  <li key={a.id}><b>{a.actor}</b> {a.action.replace(/[._]/g, " ")} <span className="muted small">{when(a.ts)}</span>
                    {a.detail?.reason && <div className="muted">“{a.detail.reason}”</div>}</li>
                ))}
              </ol>
            )}
          </div>

          <div className="panel decision">
            <div className="progress" aria-label={`${done} of ${actionable.length} findings decided`}>
              <div className="progress-bar"><i style={{ width: `${actionable.length ? (done / actionable.length) * 100 : 100}%` }} /></div>
              <span>{done} of {actionable.length} decided</span>
            </div>
            {locked ? (
              <p>This revision is <b>{s.status.replace("_", " ")}</b>, so it can no longer be changed.</p>
            ) : (<>
              <p className={blocking.length ? "gate blocked" : "gate clear"}>
                {blocking.length ? `${blocking.length} high or medium finding${blocking.length === 1 ? "" : "s"} still need a decision before this can be approved.` : "Every important finding has a decision. A reviewer can approve this now."}
              </p>
              {canFix && (
                <div className="row">
                  {isCreative ? (<>
                    <button className="btn" disabled={busy} onClick={() => upload.current?.click()}>Upload corrected file</button>
                    <input ref={upload} type="file" hidden accept=".png,.jpg,.jpeg,.webp,.pdf" onChange={(e) => e.target.files?.[0] && reviseUpload(e.target.files[0])} />
                    <span className="muted small">Creates the next revision and checks it again. Overrides carry over.</span>
                  </>) : (<>
                    <button className="btn" disabled={!fixes || busy} onClick={revise}>Apply {fixes || ""} fix{fixes === 1 ? "" : "es"} and re-check</button>
                    <span className="muted small">{fixes ? "Creates a corrected revision and checks it again." : "Accept or write fixes first."}</span>
                  </>)}
                </div>
              )}
              {canReview ? (
                <div className="review-actions">
                  <button className="btn ok" disabled={blocking.length > 0 || busy} onClick={() => setStatus("approved")}>Approve for publishing</button>
                  <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason, needed to request changes or reject" aria-label="Reason" />
                  <button className="btn ghost" disabled={!reason.trim() || busy} onClick={() => setStatus("changes_requested")}>Request changes</button>
                  <button className="btn danger" disabled={!reason.trim() || busy} onClick={() => setStatus("rejected")}>Reject</button>
                </div>
              ) : <p className="muted small">A reviewer or brand owner makes the final call.</p>}
            </>)}
          </div>
        </div>

        <aside className="findings">
          <div className="seg sm">
            {[["open", "Open", findings.filter((f) => f.decision === "pending").length], ["decided", "Decided", done], ["supported", "Supported", findings.filter((f) => f.status === "supported").length], ["all", "All", findings.length]].map(([k, l, n]) => (
              <button key={k as string} className={filter === k ? "on" : ""} onClick={() => setFilter(k as string)}>{l} <span className="muted">{n}</span></button>
            ))}
          </div>
          <p className="muted small hint-keys">Click a highlight to jump to its finding. Press j / k to move between findings.</p>
          {shown.length === 0 && <div className="empty small"><h3>{filter === "open" ? "No open findings" : "Nothing here"}</h3>{filter === "open" && !locked && <p>{canReview ? "You can approve this content." : "Waiting for a reviewer."}</p>}</div>}
          {shown.map((f) => (
            <FindingCard key={f.id} f={f} sel={sel === f.id} roles={roles} locked={locked} onPick={() => setSel(f.id)} onDecide={(d, x) => decide(f.id, d, x)} />
          ))}
        </aside>
      </div>
    </div>
  );
}
