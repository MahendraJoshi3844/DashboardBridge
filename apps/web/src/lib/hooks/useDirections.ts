"use client";

import { useEffect, useState } from "react";

import { directions } from "@/lib/api/client";
import type { DirectionsProbe } from "@/lib/migrator/paths";

/**
 * Which migration directions this deployment can run. Asked once, on mount.
 * A failed request stays `unknown` (see `directionLock`): it never locks a card.
 */
export function useDirections(): DirectionsProbe {
  const [probe, setProbe] = useState<DirectionsProbe>({ phase: "unknown" });

  useEffect(() => {
    const controller = new AbortController();
    directions({ signal: controller.signal })
      .then((list) => setProbe({ phase: "known", directions: list.directions ?? [] }))
      .catch(() => {
        // Deliberately swallowed: unknown locks nothing, and the server refuses
        // an unavailable direction with its own reason.
      });
    return () => controller.abort();
  }, []);

  return probe;
}
