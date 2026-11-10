"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Empty, SubStatus } from "@/components/Badge";
import { useSession } from "@/components/Shell";
import { api, has, when } from "@/lib/api";

const FILTERS: [string, string][] = [["open", "Needs a decision"], ["approved", "Approved"], ["closed", "Rejected or changes requested"], ["all", "All"]];

export default function Queue() {
  const { roles } = useSession();
  const [subs, setSubs] = useState<any[] | null>(null);
  const [f, setF] = useState("open");
  const [q, setQ] = useState("");
  useEffect(() => { api("/api/submissions").then(setSubs).catch(() => setSubs([])); }, []);
  if (!subs) return <div className="loading">Loading…</div>;
  const live = subs.filter((s) => s.status !== "superseded");
  const shown = live.filter((s) =>
    (f === "all" || (f === "open" && ["in_review"].includes(s.status)) || (f === "approved" && s.status === "approved") ||
      (f === "closed" && ["rejected", "changes_requested"].includes(s.status))) &&
    (!q || (s.title + s.author + s.channel).toLowerCase().includes(q.toLowerCase())));
  return (
    <div className="page">
      <header className="page-h">
        <div><h1>Review queue</h1><p className="lede">Every piece of content checked in this workspace. Only the latest revision of each is listed.</p></div>
        {has(roles, "creator", "admin", "brand_owner") && <Link className="btn primary" href="/preflight">Check content</Link>}
      </header>
      <div className="toolbar">
        <div className="seg">
          {FILTERS.map(([k, l]) => <button key={k} className={f === k ? "on" : ""} onClick={() => setF(k)}>{l} <span className="muted">{
            live.filter((s) => k === "all" || (k === "open" && s.status === "in_review") || (k === "approved" && s.status === "approved") || (k === "closed" && ["rejected", "changes_requested"].includes(s.status))).length}</span></button>)}
        </div>
        <input className="search" placeholder="Search title, author or channel" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
      </div>
      {shown.length === 0 ? <Empty title="Nothing here">{f === "open" ? <p>All content has a decision. Nice.</p> : <p>Try another filter.</p>}</Empty> : (
        <div className="panel flush">
          <table className="table">
            <thead><tr><th>Content</th><th>Channel</th><th>Open findings</th><th>Status</th><th>Updated</th></tr></thead>
            <tbody>
              {shown.map((s) => (
                <tr key={s.id}>
                  <td><Link href={`/submissions/${s.id}`} className="cell-link"><span className={`kind k-${s.kind}`} aria-hidden>{s.kind === "image" ? "IMG" : s.kind === "pdf" ? "PDF" : "TXT"}</span><span><b>{s.title}</b><small>{s.author}{s.revision > 1 ? ` · revision ${s.revision}` : ""}</small></span></Link></td>
                  <td>{s.channel}</td>
                  <td>{s.pending ? <span className={`count ${s.high_pending ? "hi" : ""}`}>{s.pending}{s.high_pending ? ` (${s.high_pending} high)` : ""}</span> : <span className="muted">None</span>}</td>
                  <td>{["queued", "running"].includes(s.check_status) ? <span className="pill sub-in_review">Checking</span> : s.check_status === "failed" ? <span className="pill sub-rejected">Check failed</span> : <SubStatus s={s.status} />}</td>
                  <td className="muted">{when(s.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
