"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useRole } from "@/components/Shell";
import { api } from "@/lib/api";

const SAMPLE = `Meet the revolutionary Aura buds from LUMORA! Enjoy 72-hour battery life, up to 35 dB of noise cancellation and a fully waterproof design for the gym. Every pair comes with a 2-year warranty. Grab yours today for just ₹3,999 — click here to order now! These are the #1 earbuds for commuters, built for people who want all-day comfort, rich sound, and calls that stay clear even when the city around them gets loud and chaotic.`;

export default function Preflight() {
  const role = useRole();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [channel, setChannel] = useState("instagram");
  const [text, setText] = useState("");
  const [alt, setAlt] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const isImage = !!file && /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name);

  async function submit() {
    setBusy(true);
    setErr("");
    const fd = new FormData();
    fd.append("title", title || file?.name || "Untitled draft");
    fd.append("channel", channel);
    fd.append("text", text);
    fd.append("alt_text", alt);
    if (file) fd.append("file", file);
    try {
      const s = await api("/api/submissions", { method: "POST", body: fd });
      router.push(`/submissions/${s.id}`);
    } catch (e: any) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ maxWidth: 860 }}>
      <div>
        <div className="eyebrow">Step 3 · Submit</div>
        <h1>New preflight</h1>
        <p className="lede">Paste copy or upload a PDF, DOCX or image. BrandProof checks claims against the evidence ledger, then terms, tone, accessibility and visuals against active rules.</p>
      </div>
      {role === "reviewer" && <div className="amb">Reviewers cannot submit content. Switch to Creator in the top bar.</div>}
      <div className="card stack">
        <div className="grid g2">
          <label className="field"><span>Title</span><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Aura Earbuds launch post" /></label>
          <label className="field"><span>Channel</span>
            <select className="in" value={channel} onChange={(e) => setChannel(e.target.value)}>
              {["instagram", "web", "email", "linkedin", "print", "campaign"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
        </div>
        {!file && (
          <label className="field">
            <span className="row">Content <span className="spacer" />
              <button type="button" className="btn ghost sm" onClick={() => { setText(SAMPLE); setTitle(title || "Aura Earbuds launch post (live demo)"); }}>Load sample copy</button>
            </span>
            <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the draft here…" style={{ minHeight: 200 }} />
          </label>
        )}
        <label className="field">
          <span>…or upload a file (TXT, PDF, DOCX, PNG, JPG)</span>
          <input type="file" accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        {isImage && (
          <label className="field"><span>Alt text / caption (checked as text; leave empty to see the accessibility check)</span>
            <input value={alt} onChange={(e) => setAlt(e.target.value)} placeholder="Describe the image" />
          </label>
        )}
        <div className="row">
          <button className="btn" disabled={busy || role === "reviewer" || (!text.trim() && !file)} onClick={submit}>{busy ? "Checking…" : "Run preflight"}</button>
          {err && <span className="err">{err}</span>}
        </div>
      </div>
      <p className="muted small">Sample files for the demo are in <code>samples/</code>: guidelines, launch post, and an off-palette banner image.</p>
    </div>
  );
}
