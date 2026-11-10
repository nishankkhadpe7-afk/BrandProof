"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

type Theme = "light" | "dark";
type Ctx = { theme: Theme; toggle: () => void; anim: { src: string; key: number } | null };
const ThemeCtx = createContext<Ctx>({ theme: "light", toggle: () => {}, anim: null });
export const useTheme = () => useContext(ThemeCtx);

const ANIM_MS = 1780; // total length of the shortened transition GIFs

/** Runs before first paint (in <head>) so the page never flashes the wrong theme. */
export const themeInitScript = `(function(){try{var t=localStorage.getItem("bp_theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.setAttribute("data-theme",t)}catch(e){document.documentElement.setAttribute("data-theme","light")}})();`;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");
  const [anim, setAnim] = useState<Ctx["anim"]>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setTheme((document.documentElement.getAttribute("data-theme") as Theme) || "light");
    // follow the OS setting until the person picks a theme themselves
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      let saved: string | null = null;
      try { saved = localStorage.getItem("bp_theme"); } catch {}
      if (!saved) { const t = e.matches ? "dark" : "light"; document.documentElement.setAttribute("data-theme", t); setTheme(t); }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduce) {
      // a fresh query string restarts the GIF from its first frame every time
      setAnim({ src: `/brand/${theme}_to_${next}.gif?t=${Date.now()}`, key: Date.now() });
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setAnim(null), ANIM_MS);
    }
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("bp_theme", next); } catch {}
    setTheme(next);
  }, [theme]);

  return <ThemeCtx.Provider value={{ theme, toggle, anim }}>{children}</ThemeCtx.Provider>;
}

/** Full wordmark or the square mark, in the right colour for the theme. Plays the transition when the theme changes. */
export function Logo({ kind = "full", height = 24, animate = true }: { kind?: "full" | "mark"; height?: number; animate?: boolean }) {
  const { anim } = useTheme();
  const playing = animate && kind === "full" && anim;
  return (
    <span className={`logo ${playing ? "animating" : ""}`} aria-label="BrandProof" role="img">
      <img className="for-light" src={`/brand/${kind === "full" ? "logo" : "mark"}-light.png`} alt="" style={{ height }} />
      <img className="for-dark" src={`/brand/${kind === "full" ? "logo" : "mark"}-dark.png`} alt="" style={{ height }} />
      {playing && <img key={anim.key} className="logo-anim" src={anim.src} alt="" style={{ height: height * 1.0 }} />}
    </span>
  );
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button className="theme-btn" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Light mode" : "Dark mode"}>
      {dark ? (
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
          <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
        </svg>
      )}
    </button>
  );
}
