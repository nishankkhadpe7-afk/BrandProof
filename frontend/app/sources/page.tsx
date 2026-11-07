"use client";
import { useCallback, useEffect, useState } from "react";
import { useRole } from "@/components/Shell";
import { api, when } from "@/lib/api";

const TYPES = ["banned_term", "preferred_term", "tone_avoid", "tone_profile", "max_exclamations", "claim_evidence", "disclaimer_required",
  "max_sentence_words", "no_all_caps", "descriptive_links", "alt_text_required", "visual_palette", "visual_min_contrast", "visual_min_resolution"];

function RuleRow({ r, canEdit, onSave }: { r: any; canEdit: boolean; onSave: (body: any) => Promise<void> }) {
  const [edit, setEdit] = useState(false);
  const [type, setType] = useState(r.type);
  const [params, setParams] = useState(JSON.stringify(r.params));
  const [bad, setBad] = useState("");
  return (
    <tr>
      <td className="mono small muted">#{r.id}<br />{r.location}</td>
      <td>
        <div style={{ fontFamily: "var(--serif)", fontSize: 15 }}>{r.text}</div>
        <div className="muted small">{r.source_name} {r.source_version}{r.validated_by ? ` · validated by ${r.validated_by}` : ""}</div>
        {r.ambiguity.map((a: any, i: number) => <div key={i} className={"amb" + (a.kind === "conflict" ? " conflict" : "")}><b className="mono">{a.kind}</b> — {a.detail}</div>)}
        {edit && (
          <div className="stack" style={{ marginTop: 10 }}>
            <select className="in" value={type} onChange={(e) => setType(e.target.value)}>
              {r.type === "unclassified" && <option value="unclassified">unclassified</option>}
              {TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <input className="mono" value={params} onChange={(e) => setParams(e.target.value)} />
            <div className="row">
              <button className="btn sm" onClick={async () => { try { await onSave({ type, params: JSON.parse(params) }); setEdit(false); setBad(""); } catch (e: any) { setBad(e.message); } }}>Save</button>
              <button className="btn ghost sm" onClick={() => setEdit(false)}>Cancel</button>
              {bad && <span className="err">{bad}</span>}
            </div>
          </div>
        )}
      </td>
      <td><span className="tag">{r.category}</span><div className="mono small" style={{ marginTop: 6 }}>{r.type}</div>{r.engine === "ai" && <span className="tag ai">ai-typed</span>}</td>
      <td className="mono small" style={{ maxWidth: 240, wordBreak: "break-word" }}>{JSON.stringify(r.params)}</td>
      <td>
        <span className={`pill ${r.status === "active" ? "sub-approved" : r.status === "rejected" ? "sub-rejected" : "sub-in_review"}`}>{r.status}</span>
        {canEdit && (
          <div className="stack" style={{ marginTop: 8 }}>
            {r.status !== "active" && <button className="btn green sm" onClick={() => onSave({ status: "active" })}>Activate</button>}
            {r.status !== "rejected" && <button className="btn ghost sm" onClick={() => onSave({ status: "rejected" })}>Reject</button>}
            {!edit && <button className="btn ghost sm" onClick={() => setEdit(true)}>Edit</button>}
          </div>
        )}
      </td>
    </tr>
  );
}

const EMPTY = { key: "", label: "", value: "", numeric: "", unit: "", comparator: "max", aliases: "", disallowed: "", approved_phrasing: "", source_ref: "", owner: "", valid_from: "", valid_to: "" };

export default function Sources() {
  const role = useRole();
  const canEdit = role === "admin" || role === "brand_owner";
  const [tab, setTab] = useState("rules");
  const [rules, setRules] = useState<any[]>([]);
  const [facts, setFacts] = useState<any[]>([]);
  const [sources, setSources] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [f, setF] = useState<any>(EMPTY);
  const [up, setUp] = useState({ name: "", version: "v1", text: "" });
  const [file, setFile] = useState<File | null>(null);

  const load = useCallback(() => {
    api("/api/rules").then(setRules);
    api("/api/facts").then(setFacts);
    api("/api/sources").then(setSources);
  }, []);
  useEffect(() => { load(); }, [load]);

  const saveRule = async (id: number, body: any) => {
    setErr("");
    try { await api(`/api/rules/${id}`, { method: "PATCH", body: JSON.stringify(body) }); load(); }
    catch (e: any) { setErr(e.message); throw e; }
  };

  const sorted = [...rules].sort((a, b) => (a.status === "proposed" ? 0 : a.status === "active" ? 1 : 2) - (b.status === "proposed" ? 0 : b.status === "active" ? 1 : 2) || a.id - b.id);

  async function addFact() {
    setErr("");
    const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
    try {
      await api("/api/facts", { method: "POST", body: JSON.stringify({ ...f, numeric: f.numeric === "" ? null : Number(f.numeric), unit: f.unit || null,
        aliases: split(f.aliases), disallowed: split(f.disallowed), approved_phrasing: f.approved_phrasing || null,
        valid_from: f.valid_from || null, valid_to: f.valid_to || null }) });
      setF(EMPTY); load();
    } catch (e: any) { setErr(e.message); }
  }

  async function upload() {
    setErr(""); setMsg("");
    const fd = new FormData();
    fd.append("name", up.name || file?.name || "Guidelines");
    fd.append("version", up.version);
    fd.append("text", up.text);
    if (file) fd.append("file", file);
    try {
      const r = await api("/api/sources/guidelines", { method: "POST", body: fd });
      setMsg(`Compiled ${r.rules_proposed} rules; ${r.flagged_for_review} flagged for review. Validate them in the Rules tab.`);
      setTab("rules"); load();
    } catch (e: any) { setErr(e.message); }
  }

  return (
    <div className="stack">
      <div>
        <div className="eyebrow">Steps 1–2 · Configure & compile</div>
        <h1>Sources, rules and evidence</h1>
        <p className="lede">The policy compiler turns prose guidelines into typed, source-linked rules. Vague, unmeasurable, untyped or conflicting rules stay proposed until an admin validates them.</p>
      </div>
      {!canEdit && <div className="amb">You are viewing as {role}. Switch to Admin or Brand owner to validate rules, add facts or upload guidelines.</div>}
      {err && <div className="amb conflict err">{err}</div>}
      {msg && <div className="amb" style={{ background: "#e9f3ec", borderColor: "#c6dfcf" }}>{msg}</div>}

      <div className="tabs">
        {[["rules", `Rules (${rules.filter((r) => r.status === "proposed").length} to validate)`], ["facts", `Evidence ledger (${facts.length})`], ["upload", "Upload guidelines"], ["sources", "Source documents"]].map(([k, l]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === "rules" && (
        <div className="card" style={{ padding: 6 }}>
          <table>
            <thead><tr><th>ID</th><th>Guideline → rule</th><th>Type</th><th>Parameters</th><th>Status</th></tr></thead>
            <tbody>{sorted.map((r) => <RuleRow key={r.id + r.status + JSON.stringify(r.params)} r={r} canEdit={canEdit} onSave={(b) => saveRule(r.id, b)} />)}</tbody>
          </table>
        </div>
      )}

      {tab === "facts" && (
        <div className="stack">
          <div className="card" style={{ padding: 6 }}>
            <table>
              <thead><tr><th>Fact</th><th>Approved value</th><th>Check</th><th>Source · owner</th><th>Validity</th>{canEdit && <th />}</tr></thead>
              <tbody>
                {facts.map((x) => (
                  <tr key={x.id}>
                    <td><b>{x.label}</b><div className="mono small muted">{x.key} · aliases: {x.aliases.join(", ")}</div>{x.disallowed.length > 0 && <div className="small muted">contradicts: {x.disallowed.join(", ")}</div>}</td>
                    <td style={{ fontFamily: "var(--serif)", fontSize: 15 }}>{x.value}</td>
                    <td className="mono small">{x.comparator}{x.numeric != null && ` ${x.numeric} ${x.unit}`}</td>
                    <td className="small"><span className="mono">{x.source_ref}</span><div className="muted">{x.owner} · {x.scope}</div></td>
                    <td className="small"><span className={`pill ${x.is_valid ? "sub-approved" : "sub-rejected"}`}>{x.is_valid ? "valid" : "expired"}</span><div className="muted mono">{x.valid_from || "…"} → {x.valid_to || "…"}</div></td>
                    {canEdit && <td><button className="btn ghost sm" onClick={async () => { await api(`/api/facts/${x.id}`, { method: "DELETE" }); load(); }}>Remove</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {canEdit && (
            <div className="card stack">
              <h3>Add approved fact</h3>
              <div className="grid g3">
                {[["key", "Key (groups versions)"], ["label", "Label"], ["value", "Approved value (display)"], ["numeric", "Numeric value"], ["unit", "Unit (hours, dB, %, INR, years…)"],
                  ["aliases", "Aliases (comma separated)"], ["disallowed", "Contradicting phrases"], ["approved_phrasing", "Approved phrasing"], ["source_ref", "Source reference"],
                  ["owner", "Owner"], ["valid_from", "Valid from (YYYY-MM-DD)"], ["valid_to", "Valid to (YYYY-MM-DD)"]].map(([k, l]) => (
                  <label key={k} className="field"><span>{l}</span><input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
                ))}
                <label className="field"><span>Comparator</span>
                  <select className="in" value={f.comparator} onChange={(e) => setF({ ...f, comparator: e.target.value })}>
                    <option value="max">max (claim must not exceed)</option><option value="exact">exact</option><option value="text">text (phrases only)</option>
                  </select>
                </label>
              </div>
              <div><button className="btn" disabled={!f.key || !f.label || !f.value} onClick={addFact}>Add to ledger</button></div>
            </div>
          )}
        </div>
      )}

      {tab === "upload" && (
        <div className="card stack" style={{ maxWidth: 760 }}>
          <div className="grid g2">
            <label className="field"><span>Name</span><input value={up.name} onChange={(e) => setUp({ ...up, name: e.target.value })} placeholder="e.g. Social media addendum" /></label>
            <label className="field"><span>Version</span><input value={up.version} onChange={(e) => setUp({ ...up, version: e.target.value })} /></label>
          </div>
          <label className="field"><span>Guideline text</span><textarea value={up.text} onChange={(e) => setUp({ ...up, text: e.target.value })} placeholder={'Never use "cheapest" in headlines.\nSentences must not exceed 20 words.\nKeep visuals clean where possible.'} /></label>
          <label className="field"><span>…or a PDF / DOCX / TXT / MD file</span><input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
          <div><button className="btn" disabled={!canEdit || (!up.text.trim() && !file)} onClick={upload}>Compile into rules</button></div>
        </div>
      )}

      {tab === "sources" && (
        <div className="card" style={{ padding: 6 }}>
          <table>
            <thead><tr><th>Source</th><th>Kind</th><th>Owner</th><th>Uploaded</th></tr></thead>
            <tbody>{sources.map((x) => (
              <tr key={x.id}><td><b>{x.name}</b> <span className="mono small">{x.version}</span><div className="muted small">{x.filename}</div></td><td><span className="tag">{x.kind}</span></td><td className="small">{x.owner}</td><td className="small muted">{when(x.uploaded_at)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
