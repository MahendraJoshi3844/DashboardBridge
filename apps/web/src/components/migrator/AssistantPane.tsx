"use client";

/**
 * AI Chat: the Run menu's jobs as a transcript, and a chat with the model.
 *
 * Every line is something that returned. A job's "Task 2/4" appears when the
 * second step's request came back; a model's words are labelled with the model
 * that wrote them; a proposed change sits in a card with an Apply button that
 * puts it into the person's draft changes, which is the only way anything here
 * reaches the project (ADR-007).
 */

import { useEffect, useRef, useState } from "react";

import { runAssistantStep, toApiError } from "@/lib/api/client";
import {
  RUN_JOBS,
  STEP_TITLES,
  itemsFor,
  severityRank,
  type TranscriptEntry,
} from "@/lib/migrator/assistant";
import type { AssistantProposal } from "@/types/contracts";

import { IconCheck, IconSigma, IconCode } from "./MgIcons";

export interface JobRequest {
  readonly jobId: string;
  readonly nonce: number;
}

interface Props {
  readonly projectId: string;
  readonly aiAvailable: boolean;
  readonly selection: { readonly kind: string; readonly table?: string; readonly name?: string } | null;
  readonly request: JobRequest | null;
  readonly isApplied: (proposal: AssistantProposal) => boolean;
  readonly onApply: (proposals: readonly AssistantProposal[]) => void;
  readonly onRunJob: (jobId: string) => void;
  readonly hidden: boolean;
}

const SUGGESTIONS = [
  { label: "Analyze the data model and suggest improvements", job: "optimize" },
  { label: "Check every measure's references and divisions", job: "validate_calculations" },
  { label: "Find potential relationship issues", job: "health" },
  { label: "Lay out the M-Query sources for review", job: "batch_mquery" },
] as const;

function time(at: Date): string {
  return at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function AssistantPane({ projectId, aiAvailable, selection, request, isApplied, onApply, onRunJob, hidden }: Props) {
  const [entries, setEntries] = useState<readonly TranscriptEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const next = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  const handled = useRef<number | null>(null);

  const push = (entry: Omit<TranscriptEntry, "id" | "at">) =>
    setEntries((current) => [...current, { ...entry, id: next.current++, at: new Date() }]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [entries.length]);

  async function run(jobId: string) {
    const job = RUN_JOBS.find((candidate) => candidate.id === jobId);
    if (!job || busy) return;
    setBusy(true);
    const scoped = job.steps.some((step) => step.scope === "selection");
    const target = scoped && selection?.table ? ` on ${selection.table}${selection.name && selection.kind !== "partition" ? `[${selection.name}]` : ""}` : scoped ? " on the whole model (nothing is selected)" : "";
    push({ speaker: "you", text: `Running: ${job.label.toLowerCase()}${target}` });
    push({ speaker: "system", text: `Starting ${job.label} (${job.steps.length} task${job.steps.length === 1 ? "" : "s"})` });
    let finished = 0;
    for (const [index, step] of job.steps.entries()) {
      push({ speaker: "system", text: `Task ${index + 1}/${job.steps.length}: ${STEP_TITLES[step.step]}` });
      try {
        const result = await runAssistantStep(projectId, step.step, { items: itemsFor(step.scope, step.step, selection) });
        const findings = [...(result.findings ?? [])].sort((a, b) => severityRank(a) - severityRank(b));
        (result.messages ?? []).forEach((m, position) =>
          push({
            speaker: m.role === "assistant" ? "assistant" : "system",
            text: m.text,
            model: m.model || undefined,
            // Findings and proposals ride on the step's first message.
            ...(position === 0 ? { findings, proposals: result.proposals ?? [] } : {}),
          }),
        );
        finished += 1;
      } catch (cause) {
        push({ speaker: "system", tone: "error", text: `Task ${index + 1} stopped: ${toApiError(cause).message}` });
        break;
      }
    }
    push({
      speaker: "system",
      tone: finished === job.steps.length ? "done" : "error",
      text:
        finished === job.steps.length
          ? `Job complete! ${finished}/${job.steps.length} tasks finished.`
          : `Job stopped after ${finished}/${job.steps.length} tasks.`,
    });
    setBusy(false);
  }

  useEffect(() => {
    if (request && handled.current !== request.nonce) {
      handled.current = request.nonce;
      void run(request.jobId);
    }
    // `run` reads the latest selection each time; re-running on its identity
    // would start a job twice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  async function send() {
    const question = message.trim();
    if (!question || busy) return;
    setMessage("");
    setBusy(true);
    push({ speaker: "you", text: question });
    try {
      const result = await runAssistantStep(projectId, "chat", { message: question });
      for (const m of result.messages ?? []) {
        push({ speaker: m.role === "assistant" ? "assistant" : "system", text: m.text, model: m.model || undefined });
      }
    } catch (cause) {
      push({ speaker: "system", tone: "error", text: toApiError(cause).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mg-chat" hidden={hidden}>
      <div className="mg-chat__log" ref={scroller} role="log" aria-live="polite">
        {entries.length === 0 ? (
          <div className="mg-chat__welcome">
            <span className="mg-chat__bolt" aria-hidden="true">⚡</span>
            <h2>AI Workspace</h2>
            <p className="mg-note">
              Run checks on the converted model, draft fixes, and ask questions. Checks run first; a model is asked only
              for drafts and summaries, and nothing is applied until you apply it.
            </p>
            <div className="mg-chat__suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button key={suggestion.label} type="button" className="mg-link" onClick={() => onRunJob(suggestion.job)} disabled={busy}>
                  {suggestion.label}
                </button>
              ))}
            </div>
            {!aiAvailable && (
              <p className="mg-note" style={{ marginTop: 14 }}>
                No model is configured on this deployment, so summaries, drafts and chat will say so; every check still runs.
              </p>
            )}
          </div>
        ) : (
          entries.map((entry) => <Entry key={entry.id} entry={entry} isApplied={isApplied} onApply={onApply} />)
        )}
        {busy && <div className="mg-note" style={{ padding: "4px 12px" }}>Working… a local model can take a minute to answer.</div>}
      </div>

      <form
        className="mg-chat__compose"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <textarea
          aria-label="Message the AI agent"
          placeholder={aiAvailable ? "Message the AI agent…" : "No model is configured — the Run menu's checks still work"}
          value={message}
          disabled={!aiAvailable || busy}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <div className="mg-chat__composebar">
          <span className="mg-note">Ctrl+↵ to send · answers are advice, never applied</span>
          <button type="submit" className="mg-btn mg-btn--primary mg-btn--sm" disabled={!aiAvailable || busy || !message.trim()}>
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

function Entry({
  entry,
  isApplied,
  onApply,
}: {
  readonly entry: TranscriptEntry;
  readonly isApplied: (proposal: AssistantProposal) => boolean;
  readonly onApply: (proposals: readonly AssistantProposal[]) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const who = entry.speaker === "you" ? "You" : entry.speaker === "assistant" ? "AI Assistant" : "System";
  const findings = entry.findings ?? [];
  const shown = showAll ? findings : findings.slice(0, 8);
  const proposals = entry.proposals ?? [];
  const pending = proposals.filter((proposal) => !isApplied(proposal));
  return (
    <div className={`mg-msg mg-msg--${entry.speaker}${entry.tone ? ` mg-msg--${entry.tone}` : ""}`}>
      <div className="mg-msg__head">
        <span className="mg-msg__who">
          {who}
          {entry.model && <span className="mg-pill mg-pill--soft" style={{ marginLeft: 6 }}>{entry.model}</span>}
        </span>
        <span className="mg-note">{time(entry.at)}</span>
      </div>
      <div className="mg-msg__text">{entry.text}</div>

      {findings.length > 0 && (
        <ul className="mg-findings">
          {shown.map((finding, index) => (
            <li key={`${finding.item}-${index}`}>
              <span className={`mg-pill ${finding.severity === "error" ? "mg-pill--bad" : finding.severity === "warning" ? "mg-pill--warn" : "mg-pill--soft"}`}>
                {finding.severity}
              </span>{" "}
              <strong>{finding.item}</strong> — {finding.message}
            </li>
          ))}
          {findings.length > 8 && (
            <li>
              <button type="button" className="mg-link" onClick={() => setShowAll(!showAll)}>
                {showAll ? "Show fewer" : `Show all ${findings.length} findings`}
              </button>
            </li>
          )}
        </ul>
      )}

      {proposals.length > 0 && (
        <div className="mg-proposals">
          <div className="mg-proposals__head">
            <span>{proposals.length} proposed change{proposals.length === 1 ? "" : "s"} — nothing is applied until you apply it</span>
            {pending.length > 1 && (
              <button type="button" className="mg-btn mg-btn--sm" onClick={() => onApply(pending)}>
                Apply all {pending.length} to draft
              </button>
            )}
          </div>
          {proposals.map((proposal) => (
            <div key={`${proposal.kind}-${proposal.table}-${proposal.name}`} className="mg-proposal">
              <div className="mg-proposal__head">
                <strong>
                  {proposal.kind === "partition" ? <IconCode size={13} /> : <IconSigma size={13} />} {proposal.table}[{proposal.name}]
                </strong>
                <span className={`mg-pill ${proposal.origin === "model" ? "mg-pill--warn" : "mg-pill--soft"}`}>
                  {proposal.origin === "model" ? `Model draft${proposal.model ? ` · ${proposal.model}` : ""}` : "Rule"}
                </span>
              </div>
              <div className="mg-note">{proposal.reason}</div>
              {proposal.current && (
                <pre className="mg-proposal__code mg-proposal__code--old">{proposal.current}</pre>
              )}
              <pre className="mg-proposal__code">{proposal.expression}</pre>
              <button
                type="button"
                className="mg-btn mg-btn--primary mg-btn--sm"
                disabled={isApplied(proposal)}
                onClick={() => onApply([proposal])}
              >
                {isApplied(proposal) ? (
                  <>
                    <IconCheck size={13} /> In draft changes
                  </>
                ) : (
                  "Apply to draft"
                )}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
