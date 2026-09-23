import Link from "next/link";
import { Suspense } from "react";

import { BridgeMark } from "@/components/Icons";
import { LicenseBanner } from "@/components/LicenseBanner";
import { AccountControl } from "@/components/AccountControl";
import { SessionGate } from "@/components/SessionGate";
import { StatusStrip } from "@/components/StatusStrip";
import { Workspace } from "@/components/Workspace";
import { ThemeToggle } from "@/components/ThemeToggle";

/**
 * The workspace route: open a workbook, watch it be read, see what is in it.
 *
 * A server component holding no state. The one client boundary is `<Workspace>`,
 * which reads the migration machine that lives above the router — so the
 * direction chosen on the landing screen is still the current state here, and
 * this screen never re-derives it.
 *
 * `<Suspense>` is required rather than decorative: `useSearchParams` inside the
 * client boundary opts the route into client-side rendering, and Next asks for
 * an explicit fallback rather than silently making the whole page dynamic.
 */
export default function WorkspacePage() {
  return (
    <SessionGate>
      <div className="mx-auto flex min-h-screen max-w-shell flex-col px-5 sm:px-8">
        <header className="flex items-center justify-between gap-4 py-6">
          <Link
            href="/"
            className="flex items-center gap-2.5 rounded-control"
            aria-label="DashboardBridge AI — back to the landing screen"
          >
            <BridgeMark className="h-6 w-6 text-source" />
            <span className="text-sm font-semibold tracking-tight text-ink">
              DashboardBridge <span className="text-ink-muted">AI</span>
            </span>
          </Link>
          <div className="flex items-center gap-4">
            <span className="eyebrow">Workspace</span>
            <AccountControl />
            <ThemeToggle />
          </div>
        </header>

        <main id="main" className="flex-1 pb-16 pt-4 sm:pt-8">
          <div className="mb-8 flex max-w-3xl flex-col gap-3">
            <LicenseBanner />
            <StatusStrip />
          </div>

          <Suspense fallback={<Loading />}>
            <Workspace />
          </Suspense>
        </main>

        <footer className="border-t border-line py-6">
          <p className="text-xs text-ink-faint">
            Offline by default. Your workbook is read on the machine you run
            this on, and no part of it is sent anywhere you have not chosen.
          </p>
        </footer>
      </div>
    </SessionGate>
  );
}

function Loading() {
  return (
    <p className="text-sm text-ink-muted" role="status">
      Opening the workspace…
    </p>
  );
}
