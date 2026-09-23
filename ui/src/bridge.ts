/** The seam between the UI and the Python engine.
 *
 * In the packaged app pywebview injects `window.pywebview.api`. In a browser it
 * is absent, so we fall back to a fixture recorded from a real Superstore run -
 * the UI is always developed against genuine engine output, never invented data.
 */

import type { RunResult } from "./types";

/** Recorded from a real Superstore run, so the UI is always developed against
 * genuine engine output. Loaded only in dev - the guard is statically false in a
 * production build, so the fixture never ships inside the product. */
async function devFixture(): Promise<RunResult> {
  const mod = await import("./fixture.json");
  return mod.default as unknown as RunResult;
}

interface PyApi {
  pick_workbook(): Promise<string | null>;
  pick_output(): Promise<string | null>;
  convert(inputPath: string, outDir: string): Promise<RunResult>;
  open_path(path: string): Promise<boolean>;
  assist_available(): Promise<boolean>;
  window_minimize(): Promise<void>;
  window_maximize(): Promise<void>;
  window_close(): Promise<void>;
  suggest_dax(ref: string): Promise<{ dax: string; note: string } | null>;
}

declare global {
  interface Window {
    pywebview?: { api: PyApi };
  }
}

export const isShell = (): boolean => Boolean(window.pywebview?.api);

/** pywebview injects its API asynchronously; wait briefly before deciding. */
export async function waitForShell(timeoutMs = 1500): Promise<boolean> {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    if (isShell()) return true;
    await new Promise((r) => setTimeout(r, 50));
  }
  return false;
}

export async function pickWorkbook(): Promise<string | null> {
  if (!isShell()) return "C:\\demo\\Superstore.twb";
  return window.pywebview!.api.pick_workbook();
}

export async function pickOutput(): Promise<string | null> {
  if (!isShell()) return "C:\\demo\\out";
  return window.pywebview!.api.pick_output();
}

export async function convert(
  inputPath: string,
  outDir: string,
): Promise<RunResult> {
  if (!isShell()) {
    if (!import.meta.env.DEV) {
      throw new Error("The conversion engine is not available.");
    }
    // Match the shape and rough latency of a real run.
    await new Promise((r) => setTimeout(r, 400));
    return devFixture();
  }
  return window.pywebview!.api.convert(inputPath, outDir);
}

export async function openPath(path: string): Promise<boolean> {
  if (!isShell()) return false;
  return window.pywebview!.api.open_path(path);
}

/** Window chrome. The frameless window has no native buttons, so the page
 * drives them; in a browser there is no window to control. */
export const windowMinimize = () => void window.pywebview?.api.window_minimize();
export const windowMaximize = () => void window.pywebview?.api.window_maximize();
export const windowClose = () => void window.pywebview?.api.window_close();

export async function assistAvailable(): Promise<boolean> {
  // Dev-only: lets the draft/accept states be built without a model runtime.
  // The guard is statically false in a production build.
  if (!isShell()) return import.meta.env.DEV;
  try {
    return await window.pywebview!.api.assist_available();
  } catch {
    return false;
  }
}

export async function suggestDax(
  ref: string,
): Promise<{ dax: string; note: string } | null> {
  if (!isShell()) {
    if (!import.meta.env.DEV) return null;
    await new Promise((r) => setTimeout(r, 900));
    return {
      dax: [
        "SUMX(",
        "    'Orders',",
        "    'Orders'[Sales] * (1 - [Churn Rate Value])",
        "        * (1 + [New Business Growth Value])",
        ")",
      ].join("\n"),
      note: "Drafted on this machine by llama3.1. Review before accepting.",
    };
  }
  try {
    return await window.pywebview!.api.suggest_dax(ref);
  } catch {
    return null;
  }
}
