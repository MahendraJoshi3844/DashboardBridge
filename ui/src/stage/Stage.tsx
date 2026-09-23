import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef } from "react";
import { SeamField } from "./SeamField";
import type { ConversionEvent, Kind, Timeline } from "../types";
import { KIND_LABEL, KIND_ORDER } from "../types";
import { useStream } from "./useStream";
import "./stage.css";

/** The Seam.
 *
 * One hairline down the middle, where translation happens. Items enter left in
 * Tableau ink, cross, and land right in Power BI ink. Items that cannot cross
 * stop at the seam and stack there.
 *
 * The held stack sits at eye level on purpose. Most tools bury what they could
 * not do; putting it on the seam is the argument this product is making.
 */

interface Props {
  timeline: Timeline | null;
  fileName: string;
  onHeldSelected(event: ConversionEvent): void;
}

/** Most-actionable first: a calc needs DAX written; a field well needs a click. */
const HELD_PRIORITY: Kind[] = [
  "calc",
  "relationship",
  "parameter",
  "table",
  "column",
  "visual",
];

function countByKind(events: ConversionEvent[]): Map<Kind, number> {
  const counts = new Map<Kind, number>();
  for (const e of events) counts.set(e.kind, (counts.get(e.kind) ?? 0) + 1);
  return counts;
}

export function Stage({ timeline, fileName, onHeldSelected }: Props) {
  const reduced = useReducedMotion() ?? false;
  const { revealed, playing, done, progress, play } = useStream(
    timeline,
    reduced,
  );

  // A finished conversion plays itself. Making the buyer press Play would put a
  // dead beat exactly where the demo needs its opening move.
  const runId = useRef(0);
  useEffect(() => {
    runId.current += 1;
    if (timeline) play(0);
    // Intentionally keyed on the timeline alone: re-running on a new `play`
    // identity would restart the stream on every render.
  }, [timeline]);

  const crossed = useMemo(
    () => revealed.filter((e) => e.outcome === "crossed"),
    [revealed],
  );
  const held = useMemo(
    () => revealed.filter((e) => e.outcome === "held"),
    [revealed],
  );

  // The ledger is ordered by what a person has to act on, not by when it
  // happened. Calculations need hand-written DAX (and are the only things local
  // assist can draft), so timeline order would bury them under field wells.
  const heldByUrgency = useMemo(
    () =>
      [...held].sort(
        (a, b) => HELD_PRIORITY.indexOf(a.kind) - HELD_PRIORITY.indexOf(b.kind),
      ),
    [held],
  );
  const crossedCounts = useMemo(() => countByKind(crossed), [crossed]);

  if (!timeline) {
    return (
      <div className="stage stage--empty">
        <div className="empty">
          <div className="empty__mark" aria-hidden="true" />
          <h1 className="empty__title">Drop a Tableau workbook to begin</h1>
          <p className="empty__note">Nothing leaves this machine.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="stage">
      <div className="stage__head">
        <span className="stage__file mono">{fileName}</span>
        <div className="stage__actions">
          <button
            className="replay"
            onClick={() => play(0)}
            disabled={playing}
            aria-label="Replay the recorded conversion"
          >
            {done ? "Replay" : playing ? "Running" : "Play"}
          </button>
        </div>
      </div>

      <div className="lanes">
        <SeamField
          revealed={revealed}
          runId={runId.current}
          reduced={reduced}
        />
        {/* -------- Tableau side -------- */}
        <section className="lane lane--source" aria-label="Tableau">
          <h2 className="lane__label">Tableau</h2>
          <ul className="tally">
            {KIND_ORDER.map((kind) => {
              const n = crossedCounts.get(kind) ?? 0;
              if (!n) return null;
              return (
                <li key={kind} className="tally__row">
                  <span className="tally__n mono">{n}</span>
                  <span className="tally__k">{KIND_LABEL[kind]}</span>
                </li>
              );
            })}
          </ul>
        </section>

        {/* -------- The seam -------- */}
        <div className="seam" aria-hidden="true">
          <motion.div
            className="seam__line"
            animate={{ opacity: playing ? 1 : 0.55 }}
            transition={{ duration: 0.4 }}
          />
          {held.length > 0 && (
            <motion.div
              className="held"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <span className="held__n mono">{held.length}</span>
              <span className="held__label">held</span>
            </motion.div>
          )}
        </div>

        {/* -------- Power BI side -------- */}
        <section className="lane lane--target" aria-label="Power BI">
          <h2 className="lane__label">Power BI</h2>
          <ul className="landed">
            <AnimatePresence initial={false}>
              {crossed
                .slice(-8)
                .reverse()
                .map((e) => (
                  <motion.li
                    key={e.seq}
                    className="landed__row"
                    initial={{ opacity: 0, x: 14 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.35 }}
                  >
                    <button
                      className="landed__open"
                      onClick={() => onHeldSelected(e)}
                    >
                      <span className="landed__name mono">{e.name}</span>
                      {e.detail && (
                        <span className="landed__detail">{e.detail}</span>
                      )}
                    </button>
                  </motion.li>
                ))}
            </AnimatePresence>
          </ul>
        </section>
      </div>

      {/* -------- Held ledger: the risk, at eye level -------- */}
      {held.length > 0 && (
        <div className="heldlist">
          <h3 className="heldlist__title">
            Held for you
            <span className="heldlist__n mono">{held.length}</span>
          </h3>
          <ul>
            {heldByUrgency.slice(0, 40).map((e) => (
              <li key={e.seq}>
                <button
                  className="helditem"
                  onClick={() => onHeldSelected(e)}
                  title={e.detail}
                >
                  <span className={`helditem__kind hk--${e.kind}`}>
                    {e.kind}
                  </span>
                  <span className="helditem__name mono">{e.ref || e.name}</span>
                  <span className="helditem__why">{e.detail}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="stage__foot">
        <div className="progress" aria-hidden="true">
          <motion.div className="progress__fill" style={{ scaleX: progress }} />
        </div>
        <div className="foot__stats">
          <span>
            <b className="mono">{crossed.length}</b> crossed
          </span>
          <span>
            <b className="mono held-ink">{held.length}</b> held
          </span>
          <span className="foot__time mono">
            {(timeline.durationMs / 1000).toFixed(2)}s
          </span>
        </div>
      </div>
    </div>
  );
}
