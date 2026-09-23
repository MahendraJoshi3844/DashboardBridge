import type { Config } from "tailwindcss";

/**
 * Tailwind is a delivery mechanism for the design tokens, not a second source
 * of truth. Every colour here resolves to a custom property declared in
 * `src/styles/tokens.css`, so `scripts/check-contrast.mjs` can measure the one
 * place the values actually live.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "var(--dbb-bg-base)",
        raised: "var(--dbb-bg-raised)",
        surface: "var(--dbb-surface)",
        "surface-strong": "var(--dbb-surface-strong)",
        line: "var(--dbb-line)",
        "line-strong": "var(--dbb-line-strong)",
        ink: "var(--dbb-ink)",
        "ink-muted": "var(--dbb-ink-muted)",
        "ink-faint": "var(--dbb-ink-faint)",
        source: "var(--dbb-ink-source)",
        target: "var(--dbb-ink-target)",
        held: "var(--dbb-ink-held)",
        good: "var(--dbb-status-good)",
        warning: "var(--dbb-status-warning)",
        serious: "var(--dbb-status-serious)",
        critical: "var(--dbb-status-critical)",
        focus: "var(--dbb-focus)",
      },
      fontFamily: {
        sans: "var(--dbb-font-sans)",
        mono: "var(--dbb-font-mono)",
      },
      borderRadius: {
        card: "var(--dbb-radius-card)",
        control: "var(--dbb-radius-control)",
      },
      boxShadow: {
        panel: "var(--dbb-shadow-panel)",
        lift: "var(--dbb-shadow-lift)",
      },
      maxWidth: {
        shell: "72rem",
      },
    },
  },
  plugins: [],
};

export default config;
