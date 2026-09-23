import { AnimatePresence, MotionConfig } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { convert, pickWorkbook, waitForShell, windowClose, windowMaximize, windowMinimize } from "./bridge";
import { Proof } from "./stage/Proof";
import { Stage } from "./stage/Stage";
import type { ConversionEvent, RunResult } from "./types";
import "./styles/tokens.css";
import "./App.css";

function baseName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export default function App() {
  const [result, setResult] = useState<RunResult | null>(null);
  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const [selected, setSelected] = useState<ConversionEvent | null>(null);

  useEffect(() => {
    void waitForShell();
  }, []);

  const run = useCallback(async (path: string) => {
    setBusy(true);
    setError("");
    try {
      const out = await convert(path, "");
      setResult(out);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The workbook could not be read.",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  const choose = useCallback(async () => {
    const path = await pickWorkbook();
    if (!path) return;
    setInput(path);
    await run(path);
  }, [run]);

  return (
    <MotionConfig reducedMotion="user">
      <div className="app">
        {/* The window is frameless, so this bar is the title bar: the drag
            region moves the window and the page draws its own controls. */}
        <header className="app__bar pywebview-drag-region">
          <span className="brand">
            t2pbi
            <span className="brand__sub">Tableau to Power BI</span>
          </span>
          <div className="app__right">
            <button className="open" onClick={choose} disabled={busy}>
              {busy ? "Converting" : result ? "Open another" : "Open workbook"}
            </button>
            <div className="chrome">
              <button
                className="chrome__btn"
                onClick={windowMinimize}
                aria-label="Minimise"
              >
                <svg width="10" height="10" viewBox="0 0 10 10">
                  <path d="M0 5h10" stroke="currentColor" strokeWidth="1" />
                </svg>
              </button>
              <button
                className="chrome__btn"
                onClick={windowMaximize}
                aria-label="Maximise"
              >
                <svg width="10" height="10" viewBox="0 0 10 10">
                  <rect
                    x="0.5"
                    y="0.5"
                    width="9"
                    height="9"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1"
                  />
                </svg>
              </button>
              <button
                className="chrome__btn chrome__btn--close"
                onClick={windowClose}
                aria-label="Close"
              >
                <svg width="10" height="10" viewBox="0 0 10 10">
                  <path
                    d="M0 0l10 10M10 0L0 10"
                    stroke="currentColor"
                    strokeWidth="1"
                  />
                </svg>
              </button>
            </div>
          </div>
        </header>

        {error && (
          <div className="banner" role="alert">
            {error}
          </div>
        )}

        <main className="app__body">
          <Stage
            timeline={result?.timeline ?? null}
            fileName={input ? baseName(input) : ""}
            onHeldSelected={setSelected}
          />
        </main>

        <AnimatePresence>
          {selected && (
            <Proof event={selected} onClose={() => setSelected(null)} />
          )}
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}
