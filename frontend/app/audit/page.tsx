"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Empty } from "@/components/Badge";
import { useSession } from "@/components/Shell";
import { api, when } from "@/lib/api";

const LABEL: Record<string, string> = {
  "submission.preflight": "checked content", "submission.revise": "created a new revision", "submission.approved": "approved",
  "submission.rejected": "rejected", "submission.changes_requested": "requested changes", "finding.accepted": "accepted a fix",
  "finding.edited": "wrote a fix", "finding.overridden": "overrode a finding", "finding.pending": "undid a decision",
  "rule.update": "changed a rule", "fact.add": "added a fact", "fact.update": "edited a fact", "fact.delete": "removed a fact",
  "source.upload+compile": "added guidelines", "member.add": "added a member", "member.invite": "invited someone",
  "member.roles": "changed roles", "member.remove": "removed a member", "member.joined": "joined", "workspace.create": "created the workspace",
  "workspace.update": "updated the workspace",
};
const GROUPS: [string, string][] = [["all", "Everything"], ["submission", "Content"], ["finding", "Decisions"], ["rule|fact|source", "Rules & facts"], ["member|workspace", "Team"]];

function detail(a: any) {
  const d = a.detail || {};
  if (d.reason) return `“${d.reason}”`;
  if (d.excerpt) return `“${d.excerpt}”${d.text ? ` → ${d.text}` : ""}`;
  if (d.findings != null) return `${d.findings} findings${d.ocr ? ` · OCR: ${d.ocr}` : ""}`;
  if (d.email) return d.email + (d.roles ? ` (${d.roles.join(", ")})` : "");
  if (d.rules_proposed != null) return `${d.rules_proposed} rules proposed, ${d.flagged} flagged`;
  if (d.label) return `${d.label}: ${d.value}`;
  if (d.after?.status) return `status → ${d.after.status}`;
  return "";
}

export default function Audit() {
  const { ws } = useSession();
  const [log, setLog] = useState<any[] | null>(null);
  const [g, setG] = useState("all");
  useEffect(() => { api("/api/audit").then(setLog).catch(() => setLog([])); }, []);
  if (!log) return <div className="loading">Loading…</div>;
  const shown = log.filter((a) => g === "all" || new RegExp(`^(${g})$`).test(a.entity === "invitation" || a.entity === "user" ? "member" : a.entity));
  return (
    <div className="page narrow">
      <header className="page-h"><div>
        <h1>Activity log</h1>
        <p className="lede">Every change in {ws?.name}: who did it, with which role, and why. Entries can't be edited or deleted.</p>
      </div></header>
      <div className="seg sm">{GROUPS.map(([k, l]) => <button key={k} className={g === k ? "on" : ""} onClick={() => setG(k)}>{l}</button>)}</div>
      {shown.length === 0 ? <Empty title="No activity yet" /> : (
        <ol className="feed">
          {shown.map((a) => (
            <li key={a.id}>
              <span className="avatar sm" aria-hidden>{a.actor[0]}</span>
              <div className="grow">
                <div><b>{a.actor}</b> {LABEL[a.action] || a.action}{" "}
                  {a.entity === "submission" && <Link href={`/submissions/${a.entity_id}`}>#{a.entity_id}</Link>}
                  <span className="muted small"> · {a.role.replace(/_/g, " ")} · {when(a.ts)}</span></div>
                {detail(a) && <div className="muted small">{detail(a)}</div>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
