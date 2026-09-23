import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { assistAvailable, suggestDax } from "../bridge";
import type { ConversionEvent } from "../types";
import "./proof.css";

/** The proof panel: the Seam turned horizontal.
 *
 * Tableau source above the rule, Power BI result below it. For a crossed item
 * the rule is solid and the DAX is really there. For a held item the rule is
 * broken and the space below is empty - the emptiness is the argument.
 *
 * A drafted suggestion is rendered in target ink but dashed and unfilled,
 * because it has not crossed either. Only accepting it makes it solid. That is
 * the one rule this panel exists to make visible: a person moves things across
 * the seam, never the model.
 */

interface Props {
  event: ConversionEvent | null;
  onClose(): void;
}

type Draft =
  | { state: "idle" }
  | { state: "working" }
  | { state: "ready"; dax: string; note: string }
  | { state: "accepted"; dax: string }
  | { state: "none" };

export function Proof({ event, onClose }: Props) {
  const [assist, setAssist] = useState(false);
  const [draft, setDraft] = useState<Draft>({ state: "idle" });

  useEffect(() => {
    void assistAvailable().then(setAssist);
  }, []);

  useEffect(() => {
    setDraft({ state: "idle" });
  }, [event?.seq]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const requestDraft = useCallback(async () => {
    if (!event) return;
    setDraft({ state: "working" });
    const result = await suggestDax(event.ref);
    setDraft(
      result
        ? { state: "ready", dax: result.dax, note: result.note }
        : { state: "none" },
    );
  }, [event]);

  if (!event) return null;

  const crossed = event.outcome === "crossed";
  const canDraft =
    !crossed && assist && event.kind === "calc" && !!event.source;

  return (
    <motion.aside
      className="proof"
      initial={{ x: 48, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 48, opacity: 0 }}
      transition={{ duration: 0.22, ease: [0.22, 0.61, 0.36, 1] }}
      aria-label={`${event.name}: conversion detail`}
    >
      <header className="proof__head">
        <div>
          <h2 className="proof__name mono">{event.name}</h2>
          <p className="proof__where">
            {event.kind} · {event.ref || event.stage}
          </p>
        </div>
        <button className="proof__close" onClick={onClose}>
          Close
        </button>
      </header>

      {event.source && (
        <section className="side">
          <h3 className="side__label side__label--source">Tableau</h3>
          <pre className="expr mono">{event.source}</pre>
        </section>
      )}

      {/* The seam. Solid when the item crossed, broken when it did not. */}
      <div className={`hseam ${crossed ? "hseam--solid" : "hseam--broken"}`}>
        <span className="hseam__tag">
          {crossed ? event.detail || "converted" : "held"}
        </span>
      </div>

      {crossed ? (
        <section className="side">
          <h3 className="side__label side__label--target">Power BI</h3>
          <pre className="expr expr--target mono">
            {event.result || event.detail}
          </pre>
        </section>
      ) : (
        <section className="side">
          <p className="why">{event.detail}</p>

          <AnimatePresence mode="wait">
            {draft.state === "ready" || draft.state === "accepted" ? (
              <motion.div
                key="draft"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <h3 className="side__label side__label--target">
                  {draft.state === "accepted" ? "Power BI" : "Drafted"}
                </h3>
                <pre
                  className={`expr expr--target mono ${
                    draft.state === "ready" ? "expr--draft" : ""
                  }`}
                >
                  {draft.dax}
                </pre>
                {draft.state === "ready" ? (
                  <>
                    <p className="draft__note">{draft.note}</p>
                    <div className="draft__actions">
                      <button
                        className="btn btn--accept"
                        onClick={() =>
                          setDraft({ state: "accepted", dax: draft.dax })
                        }
                      >
                        Accept
                      </button>
                      <button
                        className="btn"
                        onClick={() => setDraft({ state: "idle" })}
                      >
                        Discard
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="draft__note draft__note--ok">
                    Accepted. Copy it into the measure and re-check it in Power
                    BI Desktop.
                  </p>
                )}
              </motion.div>
            ) : null}
          </AnimatePresence>

          {draft.state === "none" && (
            <p className="draft__note">
              The local model could not draft this one. It needs a hand-written
              measure.
            </p>
          )}

          {canDraft &&
            (draft.state === "idle" || draft.state === "working") && (
              <button
                className="btn btn--draft"
                onClick={requestDraft}
                disabled={draft.state === "working"}
              >
                {draft.state === "working" ? "Drafting" : "Draft with local AI"}
              </button>
            )}

          {!crossed && !assist && event.kind === "calc" && (
            <p className="draft__note draft__note--quiet">
              Local AI assist is off. Start a model runtime on this machine to
              draft DAX here — nothing is ever sent anywhere.
            </p>
          )}
        </section>
      )}
    </motion.aside>
  );
}
