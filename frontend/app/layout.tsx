import type { Metadata } from "next";
import Shell from "@/components/Shell";
import { ThemeProvider, themeInitScript } from "@/components/Theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "BrandProof — check content before it's published",
  description: "Evidence-backed brand governance: claims, terms, tone, accessibility and visuals checked before publishing, with people in control.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <ThemeProvider>
          <Shell>{children}</Shell>
        </ThemeProvider>
      </body>
    </html>
  );
}
