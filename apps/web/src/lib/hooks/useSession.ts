"use client";

import { createContext, useContext } from "react";

import type { SessionState } from "@/lib/session/gate";
import type { UserAccount } from "@/types/contracts";

export interface Session {
  readonly state: SessionState;
  /** Re-ask `/auth/me`. Called after signing in or out. */
  readonly refresh: () => Promise<void>;
  readonly signOut: () => Promise<void>;
}

/**
 * The session, shared rather than fetched per component.
 *
 * A context because `/auth/me` must be asked **once**: a hook that fetched on
 * mount would ask again for every component that wanted to know who was signed
 * in, and each answer would arrive separately, so different parts of one screen
 * would disagree about whether there was a user for as long as the requests
 * took.
 */
export const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (session === null) {
    // A hard failure rather than a default. A component that silently reads
    // "signed out" because it is outside the provider renders a sign-in prompt
    // inside a signed-in application, and looks like a session bug rather than
    // a wiring one.
    throw new Error("useSession was called outside <SessionProvider>");
  }
  return session;
}

/** The signed-in user, or `null`. For anything that only needs the name. */
export function useCurrentUser(): UserAccount | null {
  const { state } = useSession();
  return state.phase === "signed-in" ? state.user : null;
}
