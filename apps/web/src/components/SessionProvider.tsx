"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiRequestError, logout, me } from "@/lib/api/client";
import { SessionContext, type Session } from "@/lib/hooks/useSession";
import { sessionFromProbe, type SessionState } from "@/lib/session/gate";
import type { ApiError } from "@/types/contracts";

function asApiError(cause: unknown): { status: number; error: ApiError } {
  if (cause instanceof ApiRequestError) {
    return { status: cause.status, error: cause.payload };
  }
  return {
    status: 0,
    error: {
      category: "SYSTEM_ERROR",
      message: "We could not reach the DashboardBridge service.",
      detail: cause instanceof Error ? cause.message : String(cause),
      request_id: "",
      project_id: null,
    } as ApiError,
  };
}

/**
 * Asks once who is signed in, and lets the rest of the app read the answer.
 *
 * The decisions are in `lib/session/gate.ts` and tested there; this holds the
 * state and makes the request. In particular a **401 is not an error here** -
 * it is the ordinary answer for "nobody", and treating it as a failure would
 * put an outage banner in front of every person who has not signed in yet.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ phase: "checking" });

  const refresh = useCallback(async () => {
    try {
      setState(sessionFromProbe({ ok: true, user: await me() }));
    } catch (cause) {
      const { status, error } = asApiError(cause);
      setState(sessionFromProbe({ ok: false, status, error }));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    try {
      await logout();
    } finally {
      // Signed out locally whatever the server said. A failed logout that left
      // the interface signed in would show someone a workspace whose every
      // request is about to be refused.
      setState({ phase: "signed-out" });
    }
  }, []);

  const value = useMemo<Session>(
    () => ({ state, refresh, signOut }),
    [state, refresh, signOut],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}
