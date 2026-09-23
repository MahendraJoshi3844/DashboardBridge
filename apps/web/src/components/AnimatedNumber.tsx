"use client";

import { animate, useIsomorphicLayoutEffect, useReducedMotion } from "motion/react";
import { useRef, useState } from "react";

/**
 * A counter that animates 0 → the real value on arrival (03-ux-spec.md,
 * Motion).
 *
 * Two things here are deliberate and easy to get wrong:
 *
 * 1. **The final value is what renders first.** Server render and first client
 *    render both emit the real number, so there is no hydration mismatch and no
 *    moment where the page shows a zero it measured. The animation then runs
 *    from 0 in a layout effect, before paint.
 * 2. **Reduced motion is checked in JavaScript.** `MotionConfig
 *    reducedMotion="user"` governs `motion` components; this is an imperative
 *    `animate()` call on a plain number, so the media query would otherwise be
 *    ignored exactly where the spec says it must not be. With motion off the
 *    number is simply present — which is the requirement: every number remains,
 *    only the movement goes.
 */
export function AnimatedNumber({
  value,
  durationMs = 900,
  className,
}: {
  readonly value: number;
  readonly durationMs?: number;
  readonly className?: string;
}) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(value);
  const animated = useRef(false);

  useIsomorphicLayoutEffect(() => {
    if (reduced) {
      setShown(value);
      return;
    }
    // Only on arrival. A re-render must not replay the count.
    if (animated.current) {
      setShown(value);
      return;
    }
    animated.current = true;
    setShown(0);
    const controls = animate(0, value, {
      duration: durationMs / 1000,
      ease: [0.22, 0.61, 0.36, 1],
      onUpdate: (latest) => setShown(Math.round(latest)),
    });
    return () => controls.stop();
  }, [value, reduced, durationMs]);

  return (
    <span className={className}>
      {/* The number a screen reader announces is the measured one, never an
          intermediate frame of an animation. */}
      <span aria-hidden="true">{shown.toLocaleString()}</span>
      <span className="sr-only">{value.toLocaleString()}</span>
    </span>
  );
}
