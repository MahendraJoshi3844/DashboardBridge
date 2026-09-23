/**
 * What the application should show, given what it knows about the session.
 *
 * Pure, and tested, because this is where being wrong is a false claim rather
 * than a visual glitch: showing the workspace to someone who is not signed in
 * produces a screen full of failed requests, and showing the sign-in form to
 * someone who *is* signed in throws away their work to ask a question that has
 * already been answered.
 *
 * ## Three states, not two booleans
 *
 * `checking` is a real state and the most easily lost one. `isSignedIn: false`
 * is true before the first answer arrives as well as after a refusal, so a
 * boolean flashes the sign-in form at every reload for anyone who is already
 * signed in. The machine in `lib/state/machine.ts` exists for the same reason:
 * four booleans describe sixteen situations of which twelve are impossible.
 *
 * ## A refusal is not an outage
 *
 * `/auth/me` answers 401 for "nobody is signed in", which is the ordinary case
 * and not an error to report. Every *other* failure is the service being
 * unreachable, and telling someone their password is wrong when the API is down
 * sends them to reset a password that was never the problem.
 */

import type { ApiError, UserAccount } from "@/types/contracts";

export type SessionState =
  | { readonly phase: "checking" }
  | { readonly phase: "signed-in"; readonly user: UserAccount }
  | { readonly phase: "signed-out" }
  | { readonly phase: "unreachable"; readonly error: ApiError };

/**
 * What the answer to `/auth/me` means.
 *
 * A 401 is "nobody", not a failure. Anything else is the service, not the
 * credential.
 */
export function sessionFromProbe(
  outcome:
    | { readonly ok: true; readonly user: UserAccount }
    | { readonly ok: false; readonly status: number; readonly error: ApiError },
): SessionState {
  if (outcome.ok) return { phase: "signed-in", user: outcome.user };
  if (outcome.status === 401) return { phase: "signed-out" };
  return { phase: "unreachable", error: outcome.error };
}

export type Screen = "loading" | "sign-in" | "app" | "unreachable";

export function screenFor(session: SessionState): Screen {
  switch (session.phase) {
    case "checking":
      return "loading";
    case "signed-in":
      return "app";
    case "signed-out":
      return "sign-in";
    case "unreachable":
      return "unreachable";
  }
}

/**
 * Why a sign-in attempt cannot be sent yet, or `null` when it can.
 *
 * Checked here rather than left to the server for one reason only: a round trip
 * that can only fail is a round trip that teaches an attacker the response time
 * of a request the server did not have to do. It is **not** a password policy -
 * the minimum length lives in `engines/identity` and is enforced when a
 * password is *set*. Re-implementing it here would put a second copy of a rule
 * in a place that cannot enforce it, and the day they disagree the form refuses
 * a password that works.
 */
export function whyCannotSubmit(
  email: string,
  password: string,
): string | null {
  if (!email.trim()) return "Enter your email address.";
  if (!password) return "Enter your password.";
  return null;
}

/**
 * What to tell someone whose sign-in was refused.
 *
 * The server says one sentence for every kind of failure - unknown address,
 * wrong password, deactivated account - because a form that distinguishes them
 * is a list of who works at the customer. This passes that sentence through
 * rather than improving on it; a client that helpfully added "no account with
 * that address" would undo the decision from the outside.
 */
export function signInFailure(status: number, error: ApiError): string {
  if (status === 401) return error.message;
  if (status === 429) {
    return "Too many attempts. Wait a moment and try again.";
  }
  return (
    "We could not reach the DashboardBridge service to sign you in. " +
    "Check that it is running, then try again."
  );
}
