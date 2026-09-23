"use client";

import { useId, useState, type FormEvent } from "react";

import { ApiRequestError, login } from "@/lib/api/client";
import { useSession } from "@/lib/hooks/useSession";
import { signInFailure, whyCannotSubmit } from "@/lib/session/gate";

import { BridgeMark } from "./Icons";
import { LicenseBanner } from "./LicenseBanner";

/**
 * The sign-in form.
 *
 * Everything it decides - whether the form can be sent, and what a refusal
 * means - is in `lib/session/gate.ts` and tested there. This renders.
 *
 * ## What it deliberately does not offer
 *
 * **No "create an account".** Accounts are made by an administrator inside the
 * deployment, and the first one by an operator setting an environment variable
 * (`P7.1`). A sign-up link on a product that runs on the customer's premises
 * would either not work or let anyone who can reach the page give themselves
 * one.
 *
 * **No "forgot password".** There is no mail server to send to on an
 * air-gapped install, and a reset flow that silently does nothing is worse
 * than no link at all. An administrator sets a new password. Saying that here
 * is the honest version of the link.
 */
export function SignInScreen() {
  const { refresh } = useSession();
  const emailId = useId();
  const passwordId = useId();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const cannot = whyCannotSubmit(email, password);
    if (cannot) {
      setProblem(cannot);
      return;
    }

    setSending(true);
    setProblem(null);
    try {
      await login({ email, password });
      // Re-ask rather than trusting the login response: the session the rest
      // of the app reads is the one `/auth/me` returns, and one source for it
      // is the reason the two cannot disagree.
      await refresh();
    } catch (cause) {
      const status = cause instanceof ApiRequestError ? cause.status : 0;
      const payload =
        cause instanceof ApiRequestError
          ? cause.payload
          : {
              category: "SYSTEM_ERROR" as const,
              message: "",
              detail: "",
              request_id: "",
              project_id: null,
            };
      setProblem(signInFailure(status, payload));
      setPassword("");
    } finally {
      setSending(false);
    }
  }

  return (
    <main
      id="main"
      className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-6 px-6 py-12"
    >
      {/* The name, because the rest of the shell is inside the gate and this
          screen would otherwise be an anonymous form on an anonymous page -
          which is exactly the shape a phishing page has. */}
      <div className="flex items-center gap-2.5 self-center">
        <BridgeMark className="h-6 w-6 text-source" />
        <span className="text-sm font-semibold tracking-tight text-ink">
          DashboardBridge <span className="text-ink-muted">AI</span>
        </span>
      </div>

      <LicenseBanner />

      <div className="panel px-6 py-7">
        <h1 className="text-xl font-medium text-ink">Sign in</h1>
        <p className="mt-1.5 text-sm text-ink-muted">
          DashboardBridge runs on your own machines. Your workbooks stay here.
        </p>

        <form
          className="mt-6 flex flex-col gap-4"
          onSubmit={onSubmit}
          noValidate
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor={emailId} className="text-sm text-ink">
              Email
            </label>
            <input
              id={emailId}
              type="email"
              autoComplete="username"
              className="field"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              // The form is validated on submit, not per keystroke: a field
              // that turns red while someone is still typing their address is
              // telling them they are wrong before they have finished.
              aria-invalid={problem !== null}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor={passwordId} className="text-sm text-ink">
              Password
            </label>
            <input
              id={passwordId}
              type="password"
              autoComplete="current-password"
              className="field"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={problem !== null}
            />
          </div>

          {/* Announced, not merely coloured. */}
          <p
            role="alert"
            aria-live="polite"
            className="min-h-5 text-sm text-critical"
          >
            {problem}
          </p>

          <button type="submit" className="btn" disabled={sending}>
            {sending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>

      <p className="text-xs text-ink-faint">
        Accounts are created by an administrator on this deployment. If you have
        forgotten your password, ask them to set a new one — there is no email
        server here to send a reset to.
      </p>
    </main>
  );
}
