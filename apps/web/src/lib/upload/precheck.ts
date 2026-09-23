/**
 * Client-side pre-checks for a chosen workbook.
 *
 * ⚠ THESE ARE A COURTESY, NOT A SECURITY BOUNDARY. ⚠
 *
 * Everything below runs in the browser, which is under the user's control and
 * therefore under an attacker's control. The gateway re-validates every one of
 * these — filename sanitisation, extension allow-list, declared size, streamed
 * size, sha256, archive-bomb limits, magic-byte detection, platform agreement —
 * before a byte reaches storage (`apps/api/app/services/upload_validation.py`,
 * 09-security-spec.md §15).
 *
 * The point of this file is to spare the user a 500 MB upload that was always
 * going to be refused, and to say why in the interface's voice. **Never delete
 * a check on the server because one exists here.** If these two ever disagree,
 * the server is right and this file is the bug.
 *
 * The failures are returned as the contract error shape, so a pre-check refusal
 * and a server refusal render through exactly the same component — there is no
 * second, weaker error path in the UI.
 */

import type { ApiError } from "@/types/contracts";

/**
 * Mirrors `ALLOWED_EXTENSIONS` in the gateway. Tableau only: reading Power BI
 * does not exist yet (ADR-005), and offering it here would be a promise the
 * engine cannot keep.
 */
export const ACCEPTED_EXTENSIONS = [".twb", ".twbx"] as const;

/**
 * Mirrors the gateway's `NOT_YET_SUPPORTED`. These get a reason rather than a
 * shrug: "not yet, and here is what is" respects the user's time in a way that
 * "unsupported file type" does not.
 */
const NOT_YET_SUPPORTED: Record<string, string> = {
  ".pbix": "Power BI",
  ".pbip": "Power BI",
  ".pbit": "Power BI",
  ".twbr": "Tableau",
};

/** Mirrors `MAX_UPLOAD_SIZE_MB` on the gateway (default 500). */
export const MAX_UPLOAD_MB: number = Number(
  process.env.NEXT_PUBLIC_MAX_UPLOAD_MB ?? "500",
);

const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

export type PrecheckResult =
  | { readonly ok: true; readonly file: File }
  | { readonly ok: false; readonly error: ApiError };

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
}

/** Sizes as a person reads them, not as a machine stores them. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

function refuse(message: string, detail: string): PrecheckResult {
  return {
    ok: false,
    error: {
      category: "UPLOAD_ERROR",
      message,
      detail,
      request_id: "",
      project_id: null,
    },
  };
}

/**
 * Check one file before it is sent. Order mirrors the server's: the cheap
 * name-based check first, then the size, because refusing on a name costs
 * nothing and refusing on a size costs nothing *if it happens before the
 * upload starts*.
 */
export function precheck(file: File): PrecheckResult {
  const extension = extensionOf(file.name);

  const notYet = NOT_YET_SUPPORTED[extension];
  if (notYet !== undefined) {
    return refuse(
      `Reading ${notYet} files is not something this version can do yet. ` +
        `Open a Tableau workbook — ${ACCEPTED_EXTENSIONS.join(" or ")} — to begin.`,
      `client pre-check: extension ${extension} is on the not-yet-supported list`,
    );
  }

  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(extension)) {
    return refuse(
      `That is not a Tableau workbook. Choose a ${ACCEPTED_EXTENSIONS.join(" or ")} file.`,
      `client pre-check: extension ${extension === "" ? "(none)" : extension} is not in the allow-list`,
    );
  }

  if (file.size === 0) {
    return refuse(
      "That file is empty, so there is nothing to read. Choose the workbook you want to migrate.",
      "client pre-check: file.size === 0",
    );
  }

  if (file.size > MAX_UPLOAD_BYTES) {
    return refuse(
      `That workbook is ${formatBytes(file.size)}, and this service accepts up to ` +
        `${MAX_UPLOAD_MB} MB. Remove the packaged data extract and open the ` +
        `.twb, or raise the limit on the service.`,
      `client pre-check: ${file.size} bytes exceeds the ${MAX_UPLOAD_BYTES} byte limit`,
    );
  }

  return { ok: true, file };
}

/**
 * Refuse a multi-file drop explicitly. One artifact per project: a silent
 * "we took the first one" is a guess about which file the user meant.
 */
export function precheckDrop(files: readonly File[]): PrecheckResult {
  const first = files[0];
  if (first === undefined) {
    return refuse(
      "Nothing came through with that drop. Try again, or use Browse.",
      "client pre-check: drop contained no files",
    );
  }
  if (files.length > 1) {
    return refuse(
      "Drop one workbook at a time. A migration runs against a single workbook, " +
        "and we will not choose one of several for you.",
      `client pre-check: drop contained ${files.length} files`,
    );
  }
  return precheck(first);
}
