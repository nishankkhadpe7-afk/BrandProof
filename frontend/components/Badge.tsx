export function Status({ s }: { s: string }) {
  return <span className={`badge st-${s}`}>{s}</span>;
}

export function Sev({ s }: { s: string }) {
  return <span className={`sev sev-${s}`}>{s}</span>;
}

export function SubStatus({ s }: { s: string }) {
  return <span className={`pill sub-${s}`}>{s.replace("_", " ")}</span>;
}
