"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API, PERSONAS, Role, getRole, setRole } from "@/lib/api";

const NAV = [
  ["/", "Overview"],
  ["/preflight", "New preflight"],
  ["/sources", "Sources & rules"],
  ["/audit", "Audit log"],
];

export function useRole(): Role {
  const [r, setR] = useState<Role>("creator");
  useEffect(() => {
    setR(getRole());
    const h = () => setR(getRole());
    window.addEventListener("bp-role", h);
    return () => window.removeEventListener("bp-role", h);
  }, []);
  return r;
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const role = useRole();
  const [ai, setAi] = useState<string>("");
  const [down, setDown] = useState(false);
  useEffect(() => {
    fetch(API + "/api/health")
      .then((r) => r.json())
      .then((j) => setAi(j.ai.provider ? `AI: ${j.ai.provider} · ${j.ai.model}` : "AI: off · deterministic + heuristic"))
      .catch(() => setDown(true));
  }, []);
  return (
    <div className="shell">
      <header className="top">
        <Link href="/" className="brand">
          <span className="mark">BP</span>
          <span>
            Brand<b>Proof</b>
          </span>
        </Link>
        <nav>
          {NAV.map(([href, label]) => (
            <Link key={href} href={href} className={path === href || (href !== "/" && path.startsWith(href)) ? "on" : ""}>
              {label}
            </Link>
          ))}
        </nav>
        <div className="who">
          <span className="ai">{ai}</span>
          <label>
            Acting as
            <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {(Object.keys(PERSONAS) as Role[]).map((r) => (
                <option key={r} value={r}>
                  {PERSONAS[r].label} — {PERSONAS[r].name.split(" ")[0]}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      {down && (
        <div className="banner">
          Cannot reach the API at <code>{API}</code>. Start the backend: <code>uvicorn app.main:app --reload</code>
        </div>
      )}
      <main>{children}</main>
      <footer>
        Demo data is fictional (Lumora / Aura Earbuds). AI suggests, humans decide. Nothing is auto-published.
      </footer>
    </div>
  );
}
