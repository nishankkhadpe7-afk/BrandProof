"use client";
import { useEffect, useState } from "react";
import { STATUS_HELP, STATUS_LABEL, imageUrl } from "@/lib/api";

export function Status({ s }: { s: string }) {
  return <span className={`badge st-${s}`} title={STATUS_HELP[s]}>{STATUS_LABEL[s] || s}</span>;
}

export function Sev({ s }: { s: string }) {
  if (s === "info") return null;
  return <span className={`sev sev-${s}`}>{s === "high" ? "High" : s === "medium" ? "Medium" : "Low"}</span>;
}

const SUB: Record<string, string> = { in_review: "In review", approved: "Approved", rejected: "Rejected", changes_requested: "Changes requested", superseded: "Superseded" };
export function SubStatus({ s }: { s: string }) {
  return <span className={`pill sub-${s}`}>{SUB[s] || s}</span>;
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="empty"><h3>{title}</h3>{children}</div>;
}

export function AuthImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let url: string | null = null;
    imageUrl(path).then((u) => { url = u; setSrc(u); }).catch(() => setErr(true));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [path]);
  if (err) return <div className="img-missing">Image not available</div>;
  if (!src) return <div className="img-loading" />;
  return <img src={src} alt={alt} className={className} />;
}
