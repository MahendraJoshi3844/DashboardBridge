import { useCallback, useEffect, useRef, useState } from "react";
import type { ConversionEvent, Timeline } from "../types";

/** Cadence of the stream, in ms per event.
 *
 * The conversion itself takes ~0.45s - far too fast to read. We do not pad it;
 * we play back the genuine recording at a legible rate. Every item shown is a
 * real item, and the true elapsed time is displayed alongside, so nothing here
 * misrepresents how fast the engine is.
 */
const MS_PER_EVENT = 38;

export interface StreamState {
  /** Events revealed so far, in recorded order. */
  revealed: ConversionEvent[];
  /** The most recent few, which are still animating across the seam. */
  inFlight: ConversionEvent[];
  playing: boolean;
  done: boolean;
  progress: number; // 0..1
}

const FLIGHT_WINDOW = 6;

export function useStream(timeline: Timeline | null, reduced: boolean) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const raf = useRef<number | null>(null);
  const startedAt = useRef(0);
  const startIndex = useRef(0);

  const total = timeline?.events.length ?? 0;

  const stop = useCallback(() => {
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    raf.current = null;
    setPlaying(false);
  }, []);

  const play = useCallback(
    (from = 0) => {
      if (!timeline) return;
      if (reduced) {
        // Motion is off: land on the finished state rather than animating.
        setIndex(timeline.events.length);
        setPlaying(false);
        return;
      }
      startedAt.current = performance.now();
      startIndex.current = from;
      setIndex(from);
      setPlaying(true);
    },
    [timeline, reduced],
  );

  useEffect(() => {
    if (!playing || !timeline) return;
    const tick = () => {
      const elapsed = performance.now() - startedAt.current;
      const next = Math.min(
        timeline.events.length,
        startIndex.current + Math.floor(elapsed / MS_PER_EVENT),
      );
      setIndex(next);
      if (next >= timeline.events.length) {
        setPlaying(false);
        raf.current = null;
        return;
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    };
  }, [playing, timeline]);

  const events = timeline?.events ?? [];
  const revealed = events.slice(0, index);

  const finished = total > 0 && index >= total;
  const state: StreamState = {
    revealed,
    // Chips clear when the run ends, so the final frame is the result, not debris.
    inFlight: finished ? [] : revealed.slice(-FLIGHT_WINDOW),
    playing,
    done: finished,
    progress: total === 0 ? 0 : index / total,
  };

  return { ...state, play, stop };
}
