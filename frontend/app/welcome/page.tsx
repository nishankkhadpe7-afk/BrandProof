"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Mark } from "@/components/Shell";
import { ThemeToggle } from "@/components/Theme";
import { session } from "@/lib/api";

const CATCHES: [string, string, string, string][] = [
  ["contradicted", "Claims that beat the spec", "“Lasts all weekend” when the approved battery life is up to 24 hours.", "Contradicted"],
  ["expired", "Out-of-date facts", "A launch price that stopped being valid last week.", "Expired"],
  ["conflicting", "Sources that disagree", "One document says 1-year warranty, another says 2.", "Conflicting"],
  ["violation", "Off-brand wording", "“LUMORA”, hype words, missing disclaimers, off-palette colours.", "Rule broken"],
];

const STEPS: [string, string][] = [
  ["Add your guidelines and facts", "Upload the brand book and spec sheets. BrandProof turns each guideline into a rule it can check and asks you to confirm the vague ones."],
  ["Check content before it ships", "Paste copy, or drop in a banner, PDF or Word file. Text inside images and scans is read too, and claims are matched by meaning, not just keywords."],
  ["Decide, with the evidence in front of you", "Every flag shows the rule or fact it's based on and a suggested fix. A reviewer accepts, edits or overrides with a reason. Nothing publishes itself."],
];

export default function Welcome() {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => { setSignedIn(!!session.token()); }, []);

  return (
    <div className="lp">
      <header className="lp-nav">
        <Link href="/welcome" className="brand"><Mark /></Link>
        <nav className="row">
          <ThemeToggle />
          <a href="#how" className="lp-link">How it works</a>
          <a href="#catches" className="lp-link">What it catches</a>
          {signedIn ? <Link href="/" className="btn primary sm">Open the app</Link> : <>
            <Link href="/login" className="lp-link">Sign in</Link>
            <Link href="/login" className="btn primary sm">Try the demo</Link>
          </>}
        </nav>
      </header>

      <section className="lp-hero">
        <div className="lp-hero-copy">
          <h1>Catch unsupported claims before your content goes live.</h1>
          <p className="lp-lede">BrandProof checks marketing copy and creatives against your brand guidelines and approved product facts. Every flag points to its source, and a person makes the final call.</p>
          <div className="row">
            <Link href={signedIn ? "/" : "/login"} className="btn primary">{signedIn ? "Open the app" : "Try the demo"}</Link>
            <a href="#how" className="btn ghost">See how it works</a>
          </div>
          <p className="muted small">No setup for the demo: pick a role on the sign-in page.</p>
        </div>

        <figure className="lp-proof" aria-label="Example of a checked post">
          <div className="lp-proof-doc">
            Aura Earbuds <mark className="pm pm-red">last all weekend</mark> on one charge, and they're <mark className="pm pm-red">fully waterproof</mark> for the pool. Only from <mark className="pm pm-orange">LUMORA</mark>.
          </div>
          <div className="lp-proof-card">
            <div className="row tight"><span className="badge st-contradicted">Contradicted</span><span className="muted small">Battery life</span></div>
            <p><b>“last all weekend”</b> reads as about 48 hours. The approved spec says up to 24 hours.</p>
            <div className="lp-sugg"><span>Suggested</span>last up to 24 hours</div>
            <p className="muted small">Source: Aura Earbuds Product Spec v3, p.2</p>
          </div>
        </figure>
      </section>

      <section id="how" className="lp-section">
        <h2>How it works</h2>
        <ol className="lp-steps">
          {STEPS.map(([t, d], i) => (
            <li key={t}><span className="lp-n" aria-hidden>{i + 1}</span><div><h3>{t}</h3><p>{d}</p></div></li>
          ))}
        </ol>
      </section>

      <section id="catches" className="lp-section">
        <h2>What it catches</h2>
        <div className="lp-catches">
          {CATCHES.map(([k, t, d, l]) => (
            <div key={t} className="lp-catch"><span className={`badge st-${k}`}>{l}</span><h3>{t}</h3><p>{d}</p></div>
          ))}
        </div>
      </section>

      <section className="lp-section lp-features">
        <div><h3>Reads images and scans</h3><p>Text in banners and scanned PDFs is checked like any other copy, and problems are boxed on the image.</p></div>
        <div><h3>One workspace per brand</h3><p>Agencies keep each client's rules, facts, people and history separate.</p></div>
        <div><h3>Works in Figma</h3><p>Check a frame and apply fixes to text layers without leaving your design.</p></div>
        <div><h3>A record of every decision</h3><p>Who approved what, which rule applied, and why an exception was allowed.</p></div>
      </section>

      <section className="lp-cta">
        <h2>See it on real examples</h2>
        <p className="muted">The demo has two fictional brands with content already checked. Sign in as a creator, reviewer or brand owner.</p>
        <Link href={signedIn ? "/" : "/login"} className="btn primary">{signedIn ? "Open the app" : "Try the demo"}</Link>
      </section>

      <footer className="lp-foot">
        <span>BrandProof, a student project. Demo brands and data are fictional.</span>
        <span className="row"><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link></span>
      </footer>
    </div>
  );
}
