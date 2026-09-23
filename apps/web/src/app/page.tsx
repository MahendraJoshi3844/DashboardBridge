import { DirectionChoice } from "@/components/DirectionChoice";
import { Hero } from "@/components/Hero";
import { BridgeMark } from "@/components/Icons";
import { LicenseBanner } from "@/components/LicenseBanner";
import { AccountControl } from "@/components/AccountControl";
import { SessionGate } from "@/components/SessionGate";
import { StatusStrip } from "@/components/StatusStrip";
import { ThemeToggle } from "@/components/ThemeToggle";

/**
 * Landing — "choose direction" (01-product-spec.md, Screens).
 *
 * The screen answers the five questions before the user acts: where they are
 * (the header and the progress rail), what is happening (the status strip),
 * why the second direction is closed (the card says so), what to do next (one
 * decision), and what needs attention (privacy mode, service reachability).
 *
 * A server component: it holds no state and ships no JavaScript of its own.
 * The three interactive pieces are the only client boundaries on the page.
 */
export default function LandingPage() {
  return (
    <SessionGate>
      <div className="mx-auto flex min-h-screen max-w-shell flex-col px-5 sm:px-8">
        <header className="flex items-center justify-between gap-4 py-6">
          <div className="flex items-center gap-2.5">
            <BridgeMark className="h-6 w-6 text-source" />
            <span className="text-sm font-semibold tracking-tight text-ink">
              DashboardBridge <span className="text-ink-muted">AI</span>
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="eyebrow">Landing</span>
            <AccountControl />
            <ThemeToggle />
          </div>
        </header>

        <main id="main" className="flex-1 pb-16 pt-8 sm:pt-16">
          <Hero />

          <div className="mt-8 flex max-w-3xl flex-col gap-3">
            <LicenseBanner />
            <StatusStrip />
          </div>

          <DirectionChoice />

          <Principles />
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

/**
 * The three commitments the product is actually sold on. They are claims about
 * behaviour, not statistics — there is no measured number on this screen, and
 * putting an unmeasured one here would contradict the first of them.
 */
function Principles() {
  const items = [
    {
      title: "Never guessed",
      body: "If a transformation cannot be produced with certainty, nothing is written. The gap is named and handed to you, because a wrong expression that looks right is worse than an honest gap.",
    },
    {
      title: "Nothing dropped silently",
      body: "Every object that cannot be represented raises a flag with its source expression and a reason stated in the source tool's terms, not the parser's.",
    },
    {
      title: "Same input, same output",
      body: "Identifiers are derived from names, ordering is stable, and a second run of the same workbook produces an identical project.",
    },
  ];

  return (
    <section aria-labelledby="principles-heading" className="mt-14 sm:mt-20">
      <h2 id="principles-heading" className="eyebrow">
        What you can defend to a stakeholder
      </h2>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {items.map((item) => (
          <article key={item.title} className="panel p-5">
            <h3 className="text-sm font-semibold text-ink">{item.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">
              {item.body}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
