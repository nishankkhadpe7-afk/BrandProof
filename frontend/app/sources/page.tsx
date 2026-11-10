"use client";
import { useCallback, useEffect, useState } from "react";
import { Empty, Status } from "@/components/Badge";
import { useSession } from "@/components/Shell";
import { api, has, when } from "@/lib/api";

const TYPES = ["banned_term", "preferred_term", "tone_avoid", "tone_profile", "max_exclamations", "claim_evidence", "disclaimer_required",
  "max_sentence_words", "no_all_caps", "descriptive_links", "alt_text_required", "visual_palette", "visual_min_contrast", "visual_min_resolution"];
const AMB: Record<string, string> = { vague: "Too vague to check", conflict: "Conflicts with another rule", untyped: "BrandProof couldn't tell what to check", incomplete: "Missing a measurable value" };

function RuleRow({ r, canEdit, onSave }: { r: any; canEdit: boolean; onSave: (body: any) => Promise<void> }) {
  const [edit, setEdit] = useState(false);
  const [type, setType] = useState(r.type);
  const [params, setParams] = useState(JSON.stringify(r.params, null, 0));
  const [bad, setBad] = useState("");
  return (
    <li className={`rule rs-${r.status}`}>
      <div className="rule-main">
        <q className="rule-text">{r.text}</q>
        <div className="muted small">{r.source_name} {r.source_version}, {r.location}{r.validated_by ? ` · checked by ${r.validated_by}` : ""}{r.engine === "ai" ? " · typed by AI" : ""}</div>
        {r.ambiguity.map((a: any, i: number) => <div key={i} className={`flag ${a.kind === "conflict" ? "conflict" : ""}`}><b>{AMB[a.kind] || a.kind}.</b> {a.detail}</div>)}
        <div className="rule-type"><span className="tag">{r.category}</span> <code>{r.type}</code> {Object.keys(r.params || {}).length > 0 && <code className="muted">{JSON.stringify(r.params)}</code>}</div>
        {edit && (
          <div className="rule-edit">
            <label className="field"><span>What to check</span>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {r.type === "unclassified" && <option value="unclassified">Choose a rule type…</option>}
                {TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
              </select></label>
            <label className="field"><span>Values (JSON)</span><input className="mono" value={params} onChange={(e) => setParams(e.target.value)} placeholder='{"max": 25}' /></label>
            <div className="row">
              <button className="btn primary sm" onClick={async () => { try { await onSave({ type, params: JSON.parse(params || "{}") }); setEdit(false); setBad(""); } catch (e: any) { setBad(e instanceof SyntaxError ? "Values must be valid JSON, e.g. {\"max\": 25}" : e.message); } }}>Save</button>
              <button className="btn ghost sm" onClick={() => setEdit(false)}>Cancel</button>
              {bad && <span className="err small">{bad}</span>}
            </div>
          </div>
        )}
      </div>
      <div className="rule-side">
        <span className={`pill rp-${r.status}`}>{r.status === "active" ? "On" : r.status === "proposed" ? "Needs checking" : "Off"}</span>
        {canEdit && (<>
          {r.status !== "active" && <button className="btn ok sm" onClick={() => onSave({ status: "active" }).catch(() => {})}>Switch on</button>}
          {r.status === "active" && <button className="btn ghost sm" onClick={() => onSave({ status: "rejected" }).catch(() => {})}>Switch off</button>}
          {r.status === "proposed" && <button className="btn ghost sm" onClick={() => onSave({ status: "rejected" }).catch(() => {})}>Dismiss</button>}
          {!edit && <button className="link" onClick={() => setEdit(true)}>Edit</button>}
        </>)}
      </div>
    </li>
  );
}

const EMPTY = { key: "", label: "", value: "", numeric: "", unit: "", comparator: "max", aliases: "", disallowed: "", examples: "", approved_phrasing: "", source_ref: "", owner: "", valid_from: "", valid_to: "" };
const FIELDS: [string, string, string][] = [
  ["label", "Name", "Battery life"], ["value", "Approved wording of the value", "up to 24 hours"], ["key", "Group key (same key = versions of one fact)", "battery"],
  ["numeric", "Number to compare against", "24"], ["unit", "Unit", "hours, dB, %, INR, years"], ["aliases", "Words people use for it (comma separated)", "battery, playtime"],
  ["examples", "Example paraphrases (comma separated)", "lasts all day, keeps going between charges"], ["disallowed", "Phrases it rules out", "waterproof, swim-proof"],
  ["approved_phrasing", "Suggested replacement wording", "up to 24 hours of battery life"], ["source_ref", "Source document and page", "Product Spec v3, p.2"],
  ["owner", "Owner", "Product team"], ["valid_from", "Valid from", "YYYY-MM-DD"], ["valid_to", "Valid until", "YYYY-MM-DD"],
];

export default function Sources() {
  const { roles, ws, toast } = useSession();
  const canEdit = has(roles, "admin", "brand_owner");
  const [tab, setTab] = useState("rules");
  const [rules, setRules] = useState<any[]>([]);
  const [facts, setFacts] = useState<any[]>([]);
  const [sources, setSources] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [f, setF] = useState<any>(EMPTY);
  const [editing, setEditing] = useState<number | null>(null);
  const [showFact, setShowFact] = useState(false);
  const [up, setUp] = useState({ name: "", version: "v1", text: "" });
  const [file, setFile] = useState<File | null>(null);
  const [probe, setProbe] = useState("They last all weekend on one charge.");
  const [probeRes, setProbeRes] = useState<any>(null);
  const [rf, setRf] = useState("proposed");

  useEffect(() => { const t = new URLSearchParams(location.search).get("tab"); if (t) setTab(t); }, []);
  const load = useCallback(() => {
    api("/api/rules").then(setRules).catch(() => {});
    api("/api/facts").then(setFacts).catch(() => {});
    api("/api/sources").then(setSources).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const saveRule = async (id: number, body: any) => {
    setErr("");
    try { await api(`/api/rules/${id}`, { method: "PATCH", body: JSON.stringify(body) }); load(); if (body.status) toast(body.status === "active" ? "Rule switched on" : "Rule switched off"); }
    catch (e: any) { setErr(e.message); throw e; }
  };

  async function saveFact() {
    setErr("");
    const split = (s: string) => (s || "").split(",").map((x) => x.trim()).filter(Boolean);
    const body = { ...f, key: f.key || f.label.toLowerCase().replace(/\W+/g, "_"), numeric: f.numeric === "" || f.numeric == null ? null : Number(f.numeric), unit: f.unit || null,
      aliases: split(f.aliases), disallowed: split(f.disallowed), examples: split(f.examples), approved_phrasing: f.approved_phrasing || null,
      valid_from: f.valid_from || null, valid_to: f.valid_to || null };
    try {
      await api(editing ? `/api/facts/${editing}` : "/api/facts", { method: editing ? "PATCH" : "POST", body: JSON.stringify(body) });
      toast(editing ? "Fact updated" : "Fact added"); setF(EMPTY); setEditing(null); setShowFact(false); load();
    } catch (e: any) { setErr(e.message); }
  }

  async function upload() {
    setErr("");
    const fd = new FormData();
    fd.append("name", up.name || file?.name?.replace(/\.[^.]+$/, "") || "Guidelines");
    fd.append("version", up.version);
    fd.append("text", up.text);
    if (file) fd.append("file", file);
    try {
      const r = await api("/api/sources/guidelines", { method: "POST", body: fd });
      toast(`${r.rules_proposed} rules proposed, ${r.flagged_for_review} need a closer look`);
      setUp({ name: "", version: "v1", text: "" }); setFile(null); setTab("rules"); setRf("proposed"); load();
    } catch (e: any) { setErr(e.message); }
  }

  const proposed = rules.filter((r) => r.status === "proposed").length;
  const shownRules = rules.filter((r) => rf === "all" || r.status === rf || (rf === "rejected" && r.status === "rejected"));

  return (
    <div className="page">
      <header className="page-h"><div>
        <h1>Brand rules & facts</h1>
        <p className="lede">BrandProof turns {ws?.name}'s written guidelines into rules it can check, and compares claims with approved facts. Rules that are vague or conflicting stay off until someone checks them.</p>
      </div></header>
      {!canEdit && <div className="alert">You can view these, but only an admin or brand owner can change them.</div>}
      {err && <div className="alert err" role="alert">{err}</div>}

      <div className="tabs" role="tablist">
        {[["rules", "Rules", proposed ? `${proposed} to check` : ""], ["facts", "Approved facts", String(facts.length)], ["probe", "Test a claim", ""], ["upload", "Add guidelines", ""], ["sources", "Documents", String(sources.length)]].map(([k, l, n]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}{n && <span className={`tab-n ${k === "rules" && proposed ? "hot" : ""}`}>{n}</span>}</button>
        ))}
      </div>

      {tab === "rules" && (rules.length === 0 ? <Empty title="No rules yet"><p>Add your brand guidelines and BrandProof will propose rules from them.</p>{canEdit && <button className="btn primary" onClick={() => setTab("upload")}>Add guidelines</button>}</Empty> : (
        <>
          <div className="seg sm">{[["proposed", "Needs checking"], ["active", "On"], ["rejected", "Off"], ["all", "All"]].map(([k, l]) => <button key={k} className={rf === k ? "on" : ""} onClick={() => setRf(k)}>{l} <span className="muted">{k === "all" ? rules.length : rules.filter((r) => r.status === k).length}</span></button>)}</div>
          {shownRules.length === 0 ? <p className="muted">Nothing in this list.</p> : <ul className="rules">{shownRules.map((r) => <RuleRow key={r.id + r.status + JSON.stringify(r.params) + r.type} r={r} canEdit={canEdit} onSave={(b) => saveRule(r.id, b)} />)}</ul>}
        </>
      ))}

      {tab === "facts" && (
        <div className="stack">
          {canEdit && !showFact && <div><button className="btn primary" onClick={() => { setF(EMPTY); setEditing(null); setShowFact(true); }}>Add a fact</button></div>}
          {showFact && (
            <div className="panel stack">
              <h3>{editing ? "Edit fact" : "Add an approved fact"}</h3>
              <p className="muted small">Example paraphrases help BrandProof recognise the same claim written in other words.</p>
              <div className="grid3">
                {FIELDS.map(([k, l, ph]) => <label key={k} className="field"><span>{l}</span><input value={f[k] ?? ""} placeholder={ph} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>)}
                <label className="field"><span>How to compare</span>
                  <select value={f.comparator} onChange={(e) => setF({ ...f, comparator: e.target.value })}>
                    <option value="max">Claims must not exceed the number</option><option value="exact">Claims must match exactly</option><option value="text">Wording only (no number)</option>
                  </select></label>
              </div>
              <div className="row"><button className="btn primary" disabled={!f.label || !f.value} onClick={saveFact}>{editing ? "Save changes" : "Add fact"}</button><button className="btn ghost" onClick={() => { setShowFact(false); setEditing(null); }}>Cancel</button></div>
            </div>
          )}
          {facts.length === 0 ? <Empty title="No approved facts yet"><p>Add product specs, prices and warranties so claims can be checked.</p></Empty> : (
            <div className="facts">
              {facts.map((x) => (
                <div key={x.id} className={`fact ${x.is_valid ? "" : "expired"}`}>
                  <div className="fact-h"><b>{x.label}</b><span className={`pill ${x.is_valid ? "sub-approved" : "sub-rejected"}`}>{x.is_valid ? "Current" : "Expired"}</span></div>
                  <div className="fact-v">{x.value}</div>
                  <div className="small muted">{x.source_ref}{x.owner ? ` · ${x.owner}` : ""}</div>
                  <div className="small muted">{x.valid_from || "…"} to {x.valid_to || "…"}{x.comparator !== "text" && x.numeric != null ? ` · ${x.comparator === "max" ? "at most" : "exactly"} ${x.numeric} ${x.unit || ""}` : ""}</div>
                  {(x.aliases.length > 0 || x.examples?.length > 0) && <div className="small fact-words">{[...x.aliases, ...(x.examples || [])].map((a: string) => <span key={a} className="chip static">{a}</span>)}</div>}
                  {x.disallowed.length > 0 && <div className="small">Rules out: {x.disallowed.join(", ")}</div>}
                  {canEdit && <div className="row"><button className="link" onClick={() => { setF({ ...x, numeric: x.numeric ?? "", unit: x.unit ?? "", aliases: x.aliases.join(", "), disallowed: x.disallowed.join(", "), examples: (x.examples || []).join(", "), approved_phrasing: x.approved_phrasing ?? "", valid_from: x.valid_from ?? "", valid_to: x.valid_to ?? "", source_ref: x.source_ref ?? "", owner: x.owner ?? "" }); setEditing(x.id); setShowFact(true); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Edit</button>
                    <button className="link danger" onClick={async () => { if (confirm(`Remove “${x.label}: ${x.value}” from approved facts?`)) { await api(`/api/facts/${x.id}`, { method: "DELETE" }); toast("Fact removed"); load(); } }}>Remove</button></div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "probe" && (
        <div className="panel stack narrow-panel">
          <h3>Test how a claim is matched</h3>
          <p className="muted small">Type a sentence to see which approved fact it's closest to in meaning, and what BrandProof would decide. Useful when adding example paraphrases.</p>
          <form className="row" onSubmit={async (e) => { e.preventDefault(); try { setProbeRes(await api("/api/facts/probe", { method: "POST", body: JSON.stringify({ text: probe }) })); } catch (x: any) { setErr(x.message); } }}>
            <input className="grow" value={probe} onChange={(e) => setProbe(e.target.value)} aria-label="Claim to test" />
            <button className="btn primary">Test</button>
          </form>
          {probeRes && (<div className="stack">
            <div>{probeRes.findings.length === 0 ? <p>No finding: either no fact is close enough, or the wording can't be compared.</p> :
              probeRes.findings.map((x: any, i: number) => <p key={i}><Status s={x.status} /> <q>{x.excerpt}</q> {x.reason}</p>)}</div>
            <div>{probeRes.ranked.map((r: any) => (
              <div key={r.fact_id} className="simrow"><span>{r.label} <span className="muted">({r.value})</span></span><span className="bar-track"><i style={{ width: `${Math.max(0, Math.min(1, r.score)) * 100}%` }} /></span><span className="num">{r.score.toFixed(2)}</span></div>
            ))}<p className="muted small">Facts scoring below {probeRes.threshold} aren't used.</p></div>
          </div>)}
        </div>
      )}

      {tab === "upload" && (
        <div className="panel stack narrow-panel">
          <h3>Add guidelines</h3>
          <p className="muted small">Upload a PDF (including scans), Word file or text, or paste the text. Each sentence becomes a proposed rule for you to check.</p>
          <div className="grid2">
            <label className="field"><span>Name</span><input value={up.name} onChange={(e) => setUp({ ...up, name: e.target.value })} placeholder="e.g. Social media addendum" /></label>
            <label className="field"><span>Version</span><input value={up.version} onChange={(e) => setUp({ ...up, version: e.target.value })} /></label>
          </div>
          <label className="field"><span>File</span><input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
          {!file && <label className="field"><span>Or paste the text</span><textarea rows={8} value={up.text} onChange={(e) => setUp({ ...up, text: e.target.value })} placeholder={'Never use "cheapest" in headlines.\nSentences must not exceed 20 words.'} /></label>}
          <div><button className="btn primary" disabled={!canEdit || (!up.text.trim() && !file)} onClick={upload}>Propose rules</button></div>
        </div>
      )}

      {tab === "sources" && (sources.length === 0 ? <Empty title="No documents yet" /> : (
        <div className="panel flush"><table className="table">
          <thead><tr><th>Document</th><th>Type</th><th>Added by</th><th>Added</th></tr></thead>
          <tbody>{sources.map((x) => (
            <tr key={x.id}><td><b>{x.name}</b> {x.version}<small className="block muted">{x.filename}</small></td><td>{x.kind === "guideline" ? "Guidelines" : x.kind === "fact_sheet" ? "Fact sheet" : x.kind}</td><td>{x.owner}</td><td className="muted">{when(x.uploaded_at)}</td></tr>
          ))}</tbody>
        </table></div>
      ))}
    </div>
  );
}
