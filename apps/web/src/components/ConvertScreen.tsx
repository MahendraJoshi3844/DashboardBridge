"use client";

import { motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";

import { getAiSettings } from "@/lib/api/client";
import type { HealthProbe } from "@/lib/hooks/useHealth";
import { summarise } from "@/lib/results/verdict";
import type {
  Analysis,
  ConversionRequest,
  ProviderSettings,
} from "@/types/contracts";

import {
  ArrowRightIcon,
  CloudIcon,
  HandIcon,
  InfoIcon,
  LockIcon,
  SparkIcon,
} from "./Icons";

/**
 * The AI decision (§24) and the Convert action, which are one screen because
 * they are one decision: *how* this workbook is converted, made once, before
 * anything is produced.
 *
 * `CONFIGURING` is client-only (03-ux-spec.md): there is no endpoint behind
 * this screen. What it collects becomes the body of `POST /conversion`, which
 * is why the whole of its output is a `ConversionRequest` handed to the caller.
 *
 * ## Absent, not degraded
 *
 * When the gateway reports no model, there is **no AI control on this page** —
 * not a greyed-out one. A disabled button is a promise the product cannot keep,
 * and a promise it cannot keep is worse than silence
 * (01-product-spec.md, "AI as informed consent").
 *
 * What replaces it is not an apology. §24 requires the product to state what it
 * found, how many operations would need a model, and that continuing without
 * one is a first-class path — so the count is printed either way, and the items
 * it counts are reported as needing a person, which is the truth.
 */
export function ConvertScreen({
  analysis,
  filename,
  probe,
  onConvert,
  onCancel,
}: {
  readonly analysis: Analysis;
  readonly filename: string;
  readonly probe: HealthProbe;
  readonly onConvert: (request: ConversionRequest) => void;
  readonly onCancel: () => void;
}) {
  const summary = summarise(analysis.compatibility);
  const aiOperations = analysis.compatibility?.ai_required ?? 0;
  const ready = probe.phase === "ready" ? probe.health : null;

  // Asked once, on mount. Null until it answers: an unanswered probe is not
  // the same as "no provider", and rendering the second while waiting for the
  // first is how a screen ends up asserting something nobody told it.
  const [provider, setProvider] = useState<ProviderSettings | null>(null);
  useEffect(() => {
    let live = true;
    getAiSettings()
      .then((settings) => {
        if (live) setProvider(settings);
      })
      .catch(() => {
        /* Leaves it null, which reads as "not known". */
      });
    return () => {
      live = false;
    };
  }, []);

  /**
   * The request, built from what is actually known.
   *
   * `ai_enabled: false` with `provider: "none"` is the only pair this screen
   * can honestly send today, and the privacy mode is the server's own — not a
   * default invented here, which would be a claim about where the workbook is
   * processed made on no evidence.
   */
  const request: ConversionRequest = {
    ai_enabled: false,
    provider: "none",
    ...(ready === null ? {} : { privacy_mode: ready.privacy_mode }),
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
      className="space-y-6"
    >
      <header>
        <p className="eyebrow">Step 5 — decide how this is converted</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          Convert this workbook
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          <span className="data break-all text-ink">{filename}</span> has been
          read and counted. Converting produces a Power BI project you can
          download. It changes nothing about the workbook you opened.
        </p>
      </header>

      <section aria-labelledby="found-heading" className="panel p-5 sm:p-6">
        <h2 id="found-heading" className="eyebrow">
          What the analysis found
        </h2>

        {/* Lead with the verdict and its denominator, before the decision. */}
        <p className="mt-3 text-lg leading-relaxed text-ink sm:text-xl">
          <span className="numeral font-semibold">
            {summary.converted.toLocaleString()}
          </span>{" "}
          of{" "}
          <span className="numeral font-semibold">
            {summary.total.toLocaleString()}
          </span>{" "}
          objects are expected to cross by deterministic rule
          {summary.needReview > 0 ? (
            <>
              {" · "}
              <span className="numeral font-semibold text-held">
                {summary.needReview.toLocaleString()}
              </span>{" "}
              need you
            </>
          ) : null}
          {summary.unsupported + summary.failed > 0 ? (
            <>
              {" · "}
              <span className="numeral font-semibold text-serious">
                {(summary.unsupported + summary.failed).toLocaleString()}
              </span>{" "}
              will not cross
            </>
          ) : null}
        </p>

        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          These are expectations from the parse, not results. Nothing has been
          converted yet.
        </p>
      </section>

      <AiDecision
        operations={aiOperations}
        available={provider?.available ?? ready?.ai_available ?? false}
        known={ready !== null || provider !== null}
        provider={provider}
      />

      <section aria-labelledby="convert-heading" className="panel p-5 sm:p-6">
        <h2 id="convert-heading" className="eyebrow">
          What happens when you convert
        </h2>
        <ul className="mt-3 max-w-prose space-y-2 text-sm leading-relaxed text-ink-muted">
          <Point Icon={ArrowRightIcon} ink="text-source">
            The engine runs its deterministic rules and writes a Power BI
            project. Anything it cannot do with certainty it refuses, and lists.
          </Point>
          <Point Icon={HandIcon} ink="text-held">
            Held items are reported with the reason they were held. Nothing is
            guessed to make a count look better.
          </Point>
          <Point Icon={InfoIcon} ink="text-ink-faint">
            The result is{" "}
            <strong className="text-ink">checked, not assumed</strong>. Producing
            a file is not evidence that it is correct, so the output is read back
            and compared against this workbook, and the results screen shows what
            that found.
          </Point>
          {ready !== null && ready.privacy_mode !== "standard" ? (
            <Point Icon={LockIcon} ink="text-good">
              {ready.privacy_mode === "local_only"
                ? "Everything happens on this machine. Nothing is sent anywhere."
                : "Everything happens inside your own infrastructure. Nothing reaches a public provider."}
            </Point>
          ) : null}
          {ready !== null && ready.privacy_mode === "standard" ? (
            <Point Icon={CloudIcon} ink="text-warning">
              The workbook is processed by the service you are connected to.
            </Point>
          ) : null}
        </ul>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          {/* The action keeps its name through the flow: Convert → Converted. */}
          <button
            type="button"
            className="btn"
            onClick={() => onConvert(request)}
          >
            Convert this workbook
          </button>
          <button type="button" className="btn btn-quiet" onClick={onCancel}>
            Back to the analysis
          </button>
        </div>
      </section>
    </motion.div>
  );
}

/**
 * One bullet: a mark, then a sentence.
 *
 * The sentence is wrapped in its own element rather than sitting loose in the
 * flex row. Loose text nodes and an inline `<strong>` become *separate flex
 * items*, and the browser lays them out as narrow columns — which is exactly
 * what "The result is **not validated**." did before validation existed.
 */
function Point({
  Icon,
  ink,
  children,
}: {
  readonly Icon: typeof InfoIcon;
  readonly ink: string;
  readonly children: ReactNode;
}) {
  return (
    <li className="flex items-start gap-2.5">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${ink}`} />
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/**
 * §24, stated rather than implied.
 *
 * Three cases, and they are genuinely different facts:
 *
 * * the probe has not resolved — nothing is known, so nothing is claimed;
 * * no model is configured — there is no AI here, and the held items are
 *   reported as needing a person;
 * * a model is configured — and the conversion path that would use it is Phase
 *   4 and not built, so this run is deterministic either way. Saying that is
 *   better than offering a button whose request the gateway refuses.
 */
const PROVIDER_COPY: Record<string, string> = {
  none: "none",
  ollama: "a local runtime",
  openai_compatible: "a remote service",
};

function AiDecision({
  operations,
  available,
  known,
  provider,
}: {
  readonly operations: number;
  readonly available: boolean;
  readonly known: boolean;
  /** From `/settings/ai`. Null until it answers; never a stand-in. */
  readonly provider: ProviderSettings | null;
}) {
  return (
    <section aria-labelledby="ai-heading" className="panel p-5 sm:p-6">
      <h2 id="ai-heading" className="eyebrow">
        Whether a model is involved
      </h2>

      <p className="mt-3 flex items-start gap-2.5 text-sm leading-relaxed text-ink">
        <SparkIcon className="mt-0.5 h-4 w-4 shrink-0 text-held" />
        <span className="max-w-prose">
          <span className="numeral font-semibold">
            {operations.toLocaleString()}
          </span>{" "}
          {operations === 1 ? "operation has" : "operations have"} no
          deterministic Power BI equivalent. A model could draft{" "}
          {operations === 1 ? "it" : "them"} for your review — it would see the
          expression and its schema, never the workbook.
        </span>
      </p>

      {!known ? (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          We have not been able to ask the service what it has available, so
          nothing is claimed about it here. The conversion below is
          deterministic.
        </p>
      ) : available ? (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          A model is configured on this machine
          {provider?.provider ? ` (${PROVIDER_COPY[provider.provider] ?? provider.provider})` : ""}. It
          can draft {operations === 1 ? "that expression" : "those expressions"}{" "}
          for your review after the conversion. Nothing it drafts is applied:
          every one arrives as a proposal with its reasoning, and you decide.
        </p>
      ) : (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          {/* Which "no" this is, not merely that it is one. "You have not set
              this up", "you set it up and it is not running" and "your privacy
              mode forbids it" send a person to three different places. */}
          {provider?.unavailable_because ??
            "No model is configured, so there is nothing to opt into here."}
        </p>
      )}

      <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
        <strong className="font-medium text-ink">
          Converting without AI is a first-class path, not a degraded one.
        </strong>{" "}
        A model would propose; a person would still have to read and accept
        every proposal. Without one, the same items arrive as work with the
        reason attached — which is what you would be checking either way.
      </p>
    </section>
  );
}
