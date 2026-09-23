import type { ReactNode } from "react";

import type { ApiError } from "@/types/contracts";

import { AlertIcon } from "./Icons";

/**
 * The one way this app renders a failure.
 *
 * `message` is written for a person and is the whole of what is shown by
 * default. `detail` is written for an engineer and lives behind *View technical
 * details*. Both are always present; neither substitutes for the other
 * (05-api-spec.md, Errors; §46).
 *
 * There is no HTTP status code anywhere in this component, and no apology. A
 * status code tells a user nothing they can act on, and an apology takes up the
 * space where the next step should be.
 *
 * `role="alert"` rather than colour: errors are announced, not merely coloured
 * (03-ux-spec.md, Accessibility).
 */
export function ErrorPanel({
  error,
  heading,
  children,
}: {
  readonly error: ApiError;
  /** What the user was trying to do, in their words. */
  readonly heading: string;
  /** The way out. There is always at least one. */
  readonly children?: ReactNode;
}) {
  return (
    <section
      role="alert"
      aria-labelledby="error-heading"
      className="panel border-line-strong p-6 sm:p-7"
    >
      <div className="flex items-start gap-3">
        <AlertIcon className="mt-0.5 h-5 w-5 shrink-0 text-critical" />
        <div className="min-w-0 flex-1">
          <h2
            id="error-heading"
            className="text-base font-semibold tracking-tight text-ink"
          >
            {heading}
          </h2>
          <p className="mt-2 max-w-prose break-words text-sm leading-relaxed text-ink-muted">
            {error.message}
          </p>

          <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="tag text-xs text-ink-faint">
              <span className="sr-only">Error category: </span>
              {error.category.replace(/_/g, " ").toLowerCase()}
            </span>
            {error.request_id ? (
              <span className="data text-[0.6875rem] text-ink-faint">
                <span className="sr-only">Request id </span>
                {error.request_id}
              </span>
            ) : null}
          </p>

          {error.detail ? (
            <details className="mt-4">
              <summary className="cursor-pointer text-xs text-ink-faint underline-offset-4 hover:underline">
                View technical details
              </summary>
              <p className="data mt-2 break-words rounded-control border border-line bg-raised px-3 py-2 text-xs text-ink-muted">
                {error.detail}
              </p>
            </details>
          ) : null}

          {children ? (
            <div className="mt-5 flex flex-wrap items-center gap-3">
              {children}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
