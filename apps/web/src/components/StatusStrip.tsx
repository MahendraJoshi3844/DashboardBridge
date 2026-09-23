"use client";

import { useEffect, useState } from "react";

import { ApiRequestError, health } from "@/lib/api/client";
import type { ApiError, HealthResponse } from "@/types/contracts";

import { AlertIcon, CheckIcon, CloudIcon, LockIcon, PendingIcon } from "./Icons";

/**
 * The strip answers two of the five questions before the user does anything:
 * *what is happening* (is the service there) and *what needs my attention*
 * (where will my workbook be processed).
 *
 * One typed state, never a pair of booleans.
 */
type Probe =
  | { readonly phase: "checking" }
  | { readonly phase: "ready"; readonly health: HealthResponse }
  | { readonly phase: "unreachable"; readonly error: ApiError };

interface PrivacyCopy {
  readonly label: string;
  readonly detail: string;
  readonly locked: boolean;
}

/**
 * Privacy mode is stated in the user's terms — where the file goes — not as an
 * enum value they would have to look up.
 */
function privacyCopy(mode: HealthResponse["privacy_mode"]): PrivacyCopy {
  switch (mode) {
    case "local_only":
      return {
        label: "Local only",
        detail: "Local processing — your dashboard stays on this machine.",
        locked: true,
      };
    case "enterprise_private":
      return {
        label: "Enterprise private",
        detail:
          "Processing stays inside your own infrastructure. Nothing is sent to a public provider.",
        locked: true,
      };
    case "standard":
      return {
        label: "Standard",
        detail:
          "Your workbook is processed by the service you are connected to.",
        locked: false,
      };
  }
}

export function StatusStrip() {
  const [probe, setProbe] = useState<Probe>({ phase: "checking" });

  useEffect(() => {
    const controller = new AbortController();

    health({ signal: controller.signal })
      .then((response) => setProbe({ phase: "ready", health: response }))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        // Every failure reaches the screen as the contract error, so the person
        // gets `message` and the engineer gets `detail` behind a disclosure.
        const error: ApiError =
          cause instanceof ApiRequestError
            ? cause.payload
            : {
                category: "SYSTEM_ERROR",
                message: "We could not check the service.",
                detail: cause instanceof Error ? cause.message : String(cause),
                request_id: "",
                project_id: null,
              };
        setProbe({ phase: "unreachable", error });
      });

    return () => controller.abort();
  }, []);

  return (
    <section
      aria-label="Service status"
      className="panel px-4 py-3 sm:px-5"
      // Progress and availability are announced, not merely coloured.
      role="status"
      aria-live="polite"
    >
      {probe.phase === "checking" ? <Checking /> : null}
      {probe.phase === "ready" ? <Ready health={probe.health} /> : null}
      {probe.phase === "unreachable" ? <Unreachable error={probe.error} /> : null}
    </section>
  );
}

function Checking() {
  return (
    <p className="flex items-center gap-2.5 text-sm text-ink-muted">
      <PendingIcon className="h-4 w-4 shrink-0" />
      Checking the conversion service…
    </p>
  );
}

function Ready({ health: response }: { health: HealthResponse }) {
  const privacy = privacyCopy(response.privacy_mode);
  const Glyph = privacy.locked ? LockIcon : CloudIcon;

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="flex items-center gap-2 text-sm font-medium text-good">
          <CheckIcon className="h-4 w-4 shrink-0" />
          Service ready
        </span>
        <span
          className="hidden h-4 w-px bg-line-strong sm:block"
          aria-hidden="true"
        />
        <span className="flex items-center gap-2 text-sm text-ink">
          <Glyph
            className={
              privacy.locked
                ? "h-4 w-4 shrink-0 text-good"
                : "h-4 w-4 shrink-0 text-warning"
            }
          />
          <span className="sr-only">Privacy mode: </span>
          <span className="tag text-xs text-ink-muted">
            {privacy.label}
          </span>
          <span className="text-ink-muted">{privacy.detail}</span>
        </span>
      </div>

      <div className="flex items-center gap-3">
        {/*
          AI is absent, not disabled. When the gateway reports no provider there
          is no AI affordance on this page at all — an offer that cannot be
          honoured is worse than no offer (01-product-spec.md, "AI as informed
          consent").
        */}
        {response.ai_available ? (
          <span className="rounded-control border border-line px-2.5 py-1 text-xs text-held">
            AI assistance available
          </span>
        ) : null}
        <span className="data text-xs text-ink-faint">
          <span className="sr-only">Service version </span>v{response.version}
        </span>
      </div>
    </div>
  );
}

function Unreachable({ error }: { error: ApiError }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="flex items-start gap-2.5 text-sm text-ink">
        <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        {/* `message` is the whole of what a person is shown. No status code,
            no stack trace, no apology (03-ux-spec.md, "Copy"). */}
        <span>{error.message}</span>
      </p>
      {error.detail ? (
        <details className="ml-7">
          <summary className="cursor-pointer text-xs text-ink-faint underline-offset-4 hover:underline">
            View technical details
          </summary>
          <p className="data mt-2 break-words rounded-control border border-line bg-raised px-3 py-2 text-xs text-ink-muted">
            {error.detail}
          </p>
        </details>
      ) : null}
    </div>
  );
}
