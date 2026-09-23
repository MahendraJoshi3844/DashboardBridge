import { describe, expect, it } from "vitest";

import {
  screenFor,
  sessionFromProbe,
  signInFailure,
  whyCannotSubmit,
} from "../src/lib/session/gate";
import type { ApiError, UserAccount } from "../src/types/contracts";

const USER = {
  user_id: "8f0f1d0e-0000-4000-8000-000000000001",
  email: "ana@northwind.test",
  display_name: "Ana",
  is_admin: false,
  is_active: true,
} as UserAccount;

function error(message: string, category = "AUTH_ERROR"): ApiError {
  return {
    category,
    message,
    detail: message,
    request_id: "r",
    project_id: null,
  } as ApiError;
}

describe("what the app shows about the session", () => {
  it("shows neither the app nor the sign-in form until it knows", () => {
    // The state most easily lost. `isSignedIn: false` is true before the first
    // answer as well as after a refusal, so a boolean flashes the sign-in form
    // at every reload for someone who is already signed in.
    expect(screenFor({ phase: "checking" })).toBe("loading");
  });

  it("reads a 401 as nobody signed in rather than as a failure", () => {
    const state = sessionFromProbe({
      ok: false,
      status: 401,
      error: error("Sign in to continue."),
    });
    expect(state.phase).toBe("signed-out");
    expect(screenFor(state)).toBe("sign-in");
  });

  it("reads anything else as the service being unreachable", () => {
    // Telling someone their password is wrong when the API is down sends them
    // to reset a password that was never the problem.
    const state = sessionFromProbe({
      ok: false,
      status: 503,
      error: error("The service is unavailable.", "SYSTEM_ERROR"),
    });
    expect(state.phase).toBe("unreachable");
    expect(screenFor(state)).toBe("unreachable");
  });

  it("shows the app once someone is signed in", () => {
    const state = sessionFromProbe({ ok: true, user: USER });
    expect(state).toEqual({ phase: "signed-in", user: USER });
    expect(screenFor(state)).toBe("app");
  });
});

describe("before the form is sent", () => {
  it("will not post an empty address or an empty password", () => {
    expect(whyCannotSubmit("", "pw")).toContain("email");
    expect(whyCannotSubmit("a@b.test", "")).toContain("password");
  });

  it("lets anything else through", () => {
    expect(whyCannotSubmit("a@b.test", "x")).toBeNull();
  });

  it("does not re-implement the password rule", () => {
    // The minimum length belongs to `engines/identity` and is enforced when a
    // password is *set*. A copy here could not enforce it and would, on the day
    // the two disagree, refuse a password that actually works.
    expect(whyCannotSubmit("a@b.test", "short")).toBeNull();
  });
});

describe("when signing in is refused", () => {
  it("repeats the server's sentence rather than improving on it", () => {
    // The server says one thing for every cause on purpose: a form that can
    // distinguish them is a list of who works at the customer. A client that
    // helpfully added "no account with that address" would undo that decision
    // from the outside.
    const said = "That email address and password do not match an active account.";
    expect(signInFailure(401, error(said))).toBe(said);
  });

  it("says something different when the service is the problem", () => {
    const message = signInFailure(500, error("boom", "SYSTEM_ERROR"));
    expect(message).toContain("service");
    expect(message).not.toContain("boom");
  });

  it("names rate limiting as itself", () => {
    // Otherwise a locked-out person reads "wrong password" and keeps trying,
    // which is the one thing guaranteed to keep them locked out.
    expect(signInFailure(429, error("slow down"))).toContain("Too many");
  });
});
