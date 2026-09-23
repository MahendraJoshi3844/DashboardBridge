import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Tests for the **pure** modules only.
 *
 * `apps/web` had no test runner, which was a real gap in the definition of
 * done: `scripts/check-ordering.mjs` and `scripts/check-contrast.mjs` covered
 * two rules and nothing covered the rest. What is covered here is the logic
 * that decides what the product is allowed to claim — the verdict, the
 * comparison pairing, the state machine, the upload pre-check, the flag
 * ordering — because those are the places where a regression is a false claim
 * rather than a visual glitch.
 *
 * There are deliberately **no component or DOM tests**. A screenshot that a
 * person actually looked at is better evidence about a screen than an assertion
 * that a `<div>` exists, and a DOM harness would drag jsdom, a React test
 * renderer and their transitive trees into a product that ships air-gapped.
 *
 * `environment: "node"` for the same reason: nothing under test touches a
 * browser API.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
