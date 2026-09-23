"use client";

import type { ReactNode } from "react";

import { useSession } from "@/lib/hooks/useSession";
import { screenFor } from "@/lib/session/gate";

import { AlertIcon, PendingIcon } from "./Icons";
import { SignInScreen } from "./SignInScreen";

/**
 * Shows the application, the sign-in form, or neither.
 *
 * Wrapped around a page rather than checked inside one, so a route cannot
 * forget: the same reasoning as `current_user` being a dependency on the API's
 * routers rather than a line in each handler.
 *
 * The `loading` state is the one that is easy to lose and expensive to lose.
 * Rendering the sign-in form while `/auth/me` is still in flight flashes it at
 * every reload for someone who is already signed in, and a person who sees a
 * login form typically starts typing into it - so the flash is not cosmetic,
 * it costs them the action they came to do.
 */
export function SessionGate({ children }: { children: ReactNode }) {
  const { state } = useSession();

  switch (screenFor(state)) {
    case "loading":
      return (
        <main
          id="main"
          className="mx-auto flex min-h-dvh w-full max-w-md items-center justify-center px-6"
        >
          <p className="flex items-center gap-2.5 text-sm text-ink-muted">
            <PendingIcon className="h-4 w-4 shrink-0" />
            Checking your session…
          </p>
        </main>
      );

    case "sign-in":
      return <SignInScreen />;

    case "unreachable":
      // Deliberately not the sign-in form. Someone shown a login form because
      // the service is down will try their password, be told nothing useful,
      // and conclude their account is broken.
      return (
        <main
          id="main"
          className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-3 px-6"
        >
          <p className="flex items-center gap-2.5 text-sm font-medium text-critical">
            <AlertIcon className="h-4 w-4 shrink-0" />
            The DashboardBridge service is not answering.
          </p>
          <p className="text-sm text-ink-muted">
            {state.phase === "unreachable" ? state.error.message : ""} Check
            that it is running, then reload this page.
          </p>
        </main>
      );

    case "app":
      return <>{children}</>;
  }
}
