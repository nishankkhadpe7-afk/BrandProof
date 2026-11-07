"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, when } from "@/lib/api";

export default function Audit() {
  const [log, setLog] = useState<any[]>([]);
  useEffect(() => { api("/api/audit").then(setLog).catch(() => {}); }, []);
  return (
    <div className="stack">
      <div>
        <div className="eyebrow">Governance</div>
        <h1>Audit log</h1>
        <p className="lede">Append-only record of every upload, rule validation, preflight, decision and approval — who, in which role, and why.</p>
      </div>
      <div className="card" style={{ padding: 6 }}>
        <table>
          <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
          <tbody>
            {log.map((a) => (
              <tr key={a.id}>
                <td className="mono small muted">{when(a.ts)}</td>
                <td><b>{a.actor}</b><div><span className="tag">{a.role}</span></div></td>
                <td className="mono small">{a.action}</td>
                <td className="small">{a.entity === "submission" ? <Link href={`/submissions/${a.entity_id}`}>submission #{a.entity_id}</Link> : `${a.entity} #${a.entity_id}`}</td>
                <td className="mono small" style={{ maxWidth: 420, wordBreak: "break-word", color: "var(--ink-2)" }}>{JSON.stringify(a.detail)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
