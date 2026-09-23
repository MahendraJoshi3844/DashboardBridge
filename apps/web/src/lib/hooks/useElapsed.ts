"use client";

import { useEffect, useState } from "react";

/**
 * Milliseconds since `startedAt`, ticking while `running` is true.
 *
 * This is a *measurement*, not an animation: it reports how long the user has
 * actually been waiting. 03-ux-spec.md forbids a bar creeping toward 90% and
 * requires the real elapsed time instead — this is the thing it requires.
 *
 * It is deliberately not driven by requestAnimationFrame. Sixty updates a
 * second of a number nobody can read at that rate is motion, and motion that
 * communicates nothing is removed. Ten a second is legible and calm, and under
 * `prefers-reduced-motion` even a clock should not flicker, so it slows down.
 */
export function useElapsed(startedAt: number | null, running: boolean): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (startedAt === null) {
      setElapsed(0);
      return;
    }
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    setElapsed(performance.now() - startedAt);
    if (!running) return;

    const id = window.setInterval(
      () => setElapsed(performance.now() - startedAt),
      reduced ? 500 : 100,
    );
    return () => window.clearInterval(id);
  }, [startedAt, running]);

  return elapsed;
}

/** A duration a person reads, at the precision the number deserves. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes} min ${seconds.toString().padStart(2, "0")} s`;
}
