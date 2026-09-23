"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

import { SessionProvider } from "@/components/SessionProvider";
import { MigrationProvider } from "@/lib/state/context";

/**
 * `reducedMotion="user"` is the load-bearing line in this file.
 *
 * 03-ux-spec.md is explicit: a `prefers-reduced-motion` media query does not
 * stop a JavaScript animation library. Framer Motion drives transforms from
 * JS, so without this the CSS rule in tokens.css is ignored exactly where it
 * matters most — the entrance animations and card interactions.
 *
 * With it, every animation in the tree collapses to an instant state change
 * while layout, text and numbers stay identical. Motion is never the only
 * carrier of information here, so nothing is lost when it is off.
 *
 * `MigrationProvider` sits inside it and above every route, so the migration
 * state machine survives the move from the landing screen to the workspace.
 * One machine, one current state (03-ux-spec.md, "State machine").
 *
 * `SessionProvider` is above both, and asks `/auth/me` exactly once (`P7.1`).
 * Above, because a component that had to fetch its own answer would ask again
 * for every part of the screen that wanted to know who was signed in, and the
 * answers would arrive separately - so one screen would disagree with itself
 * for as long as the requests took.
 */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.24 }}>
      <SessionProvider>
        <MigrationProvider>{children}</MigrationProvider>
      </SessionProvider>
    </MotionConfig>
  );
}
