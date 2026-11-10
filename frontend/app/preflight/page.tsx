"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useSession } from "@/components/Shell";
import { api, has } from "@/lib/api";

const SAMPLES: [string, string][] = [
  ["Launch post", "Meet the revolutionary Aura buds from LUMORA! Enjoy 72-hour battery life, up to 35 dB of noise cancellation and a fully waterproof design for the gym. Every pair comes with a 2-year warranty. Grab yours today for just ₹3,999 — click here to order now!"],
  ["Paraphrased claims", "Lumora Aura Earbuds last all weekend on a single charge. Take them swimming without a second thought. They silence the world completely, so your commute simply disappears."],
  ["Clean copy", "Lumora Aura Earbuds give you up to 24 hours of battery life with the case, and they're sweat and splash resistant (IPX4) for the gym."],
];
const CHANNELS = ["Instagram", "Website", "Email", "LinkedIn", "Print", "Campaign"];
const ACCEPT = ".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp";

export default function Preflight() {
  const { roles, ws, toast } = useSession();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [channel, setChannel] = useState("Instagram");
  const [text, setText] = useState("");
  const [alt, setAlt] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const isImage = !!file && /\.(png|jpe?g|webp)$/i.test(file.name);
  const canSubmit = has(roles, "creator", "admin", "brand_owner");
  const isLumora = ws?.name === "Lumora";

  async function submit() {
    setBusy(true); setErr("");
    const fd = new FormData();
    fd.append("title", title.trim() || file?.name || text.trim().split(/\s+/).slice(0, 6).join(" ") || "Untitled draft");
    fd.append("channel", channel.toLowerCase());
    fd.append("text", text);
    fd.append("alt_text", alt);
    if (file) fd.append("file", file);
    try {
      const s = await api("/api/submissions", { method: "POST", body: fd });
      toast("Submitted. Checking now.");
      router.push(`/submissions/${s.id}`);
    } catch (e: any) { setErr(e.message); setBusy(false); }
  }

  function pick(f: File | null | undefined) {
    if (!f) return;
    if (f.size > 15 * 1024 * 1024) { setErr("That file is over 15 MB. Export a smaller version and try again."); return; }
    setErr(""); setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
  }

  if (!canSubmit) return (
    <div className="page narrow"><h1>Check content</h1>
      <div className="alert">Reviewers don't submit content in BrandProof, so this page is read-only for you. Open the <a href="/submissions">review queue</a> to make decisions.</div></div>
  );

  return (
    <div className="page narrow">
      <header className="page-h"><div>
        <h1>Check content</h1>
        <p className="lede">Paste copy or upload a file. BrandProof checks claims against approved facts — including claims phrased in other words — and checks wording, tone, accessibility and visuals against {ws?.name}'s rules. It reads text inside images and scanned PDFs.</p>
      </div></header>

      <div className="panel stack">
        <div className="grid2">
          <label className="field"><span>Title</span><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Diwali launch post" /></label>
          <label className="field"><span>Where it will be published</span>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>{CHANNELS.map((c) => <option key={c}>{c}</option>)}</select>
          </label>
        </div>

        {!file ? (
          <>
            <label className="field">
              <span>Copy</span>
              <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the draft here…" rows={9} />
            </label>
            {isLumora && (
              <div className="row small"><span className="muted">Try an example:</span>
                {SAMPLES.map(([l, t]) => <button key={l} type="button" className="chip" onClick={() => { setText(t); setTitle(title || l); }}>{l}</button>)}
              </div>
            )}
            <div className={`drop ${drag ? "over" : ""}`} onClick={() => input.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
              role="button" tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}>
              <b>Or drop a file here</b>
              <span className="muted small">Banner or social image (PNG, JPG, WEBP) · PDF, including scans · Word (DOCX) · TXT or Markdown</span>
            </div>
          </>
        ) : (
          <div className="file-chip">
            <span className={`kind k-${isImage ? "image" : /\.pdf$/i.test(file.name) ? "pdf" : "text"}`} aria-hidden>{isImage ? "IMG" : /\.pdf$/i.test(file.name) ? "PDF" : "DOC"}</span>
            <span className="grow"><b>{file.name}</b><small>{(file.size / 1024).toFixed(0)} KB{isImage ? " · text in the image will be read automatically" : ""}</small></span>
            <button className="btn ghost sm" onClick={() => setFile(null)}>Remove</button>
          </div>
        )}
        <input ref={input} type="file" hidden accept={ACCEPT} onChange={(e) => pick(e.target.files?.[0])} />

        {isImage && (
          <label className="field"><span>Alt text</span>
            <input value={alt} onChange={(e) => setAlt(e.target.value)} placeholder="Describe the image for people using screen readers" />
            <small className="hint">Required by most brand guidelines. Leave it empty and BrandProof will flag it.</small>
          </label>
        )}
        {err && <div className="alert err" role="alert">{err}</div>}
        <div className="row">
          <button className="btn primary" disabled={busy || (!text.trim() && !file)} onClick={submit}>{busy ? (file ? "Reading and checking…" : "Checking…") : "Run check"}</button>
          <span className="muted small">Usually takes a few seconds. Nothing is published.</span>
        </div>
      </div>
    </div>
  );
}
