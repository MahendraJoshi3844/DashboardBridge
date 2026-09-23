import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "DashboardBridge AI",
  description:
    "An explainable BI migration platform that analyses, maps, converts and " +
    "validates BI dashboards — deterministic engineering at its core, AI only " +
    "where it adds value.",
  applicationName: "DashboardBridge AI",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  // Both, so the browser's own chrome follows the page rather than staying
  // dark behind a light theme.
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#090b10" },
    { media: "(prefers-color-scheme: light)", color: "#f4f6fa" },
  ],
  colorScheme: "dark light",
};

/**
 * Resolve the theme before the first paint.
 *
 * This has to be inline and synchronous. A React effect runs after the first
 * paint, so a user who chose light would see a dark page flash first - on
 * every navigation, not once. The script is deliberately tiny and does the one
 * thing that cannot wait; everything else is in `ThemeToggle`.
 *
 * It writes only `dark` or `light`, never `system`: `system` is a preference,
 * and resolving it here is what keeps the stylesheet to two palettes instead of
 * two palettes written twice.
 *
 * Wrapped in try/catch because reading storage throws outright in some
 * contexts - a private window with site data blocked. Failing here would take
 * the page with it, to save a colour.
 *
 * It reaches the page through `dangerouslySetInnerHTML`, which is worth
 * justifying rather than leaving to be re-derived: this string is a
 * module-level constant with no interpolation and nothing from a request, a
 * user or storage is ever concatenated into it. The value it *reads* from
 * storage is compared against three literals and never emitted. If either of
 * those stops being true, this stops being safe.
 */
const applyThemeBeforePaint = `
(function () {
  try {
    var stored = window.localStorage.getItem("dbb-theme");
    var preference = stored === "light" || stored === "dark" || stored === "system"
      ? stored
      : "system";
    var dark = preference === "dark" ||
      (preference === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  } catch (error) {
    document.documentElement.dataset.theme = "dark";
  }
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // `dark` on the server pass so that no-JavaScript keeps the palette the
    // product was designed in. The script above corrects it before paint.
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: applyThemeBeforePaint }} />
      </head>
      <body>
        <Providers>
          <a className="skip-link" href="#main">
            Skip to content
          </a>
          {children}
        </Providers>
      </body>
    </html>
  );
}
