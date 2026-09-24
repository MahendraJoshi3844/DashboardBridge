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

import type { ApiError, Platform } from "@/types/contracts";

/**
 * Mirrors `ALLOWED_EXTENSIONS` in the gateway, per source platform. A Power BI
 * project is a folder, so it arrives zipped; the gateway confirms from the
 * member list that the archive really is one.
 */
export const ACCEPTED_BY_SOURCE: Record<Platform, readonly string[]> = {
  tableau: [".twb", ".twbx"],
  powerbi: [".zip"],
};

/** Kept for callers that predate the second direction. */
export const ACCEPTED_EXTENSIONS = ACCEPTED_BY_SOURCE.tableau;

/**
 * Mirrors the gateway's `NOT_YET_SUPPORTED` and `MANIFEST_ONLY`. These get a
 * remedy rather than a shrug: "not that, and here is what to do" respects the
 * user's time in a way that "unsupported file type" does not.
 */
const REMEDIES: Record<string, string> = {
  ".pbix":
    "A .pbix file cannot be read here. In Power BI Desktop, save the report as a Power BI project (PBIP), then zip the project folder and open that.",
  ".pbit":
    "A .pbit template cannot be read here. Save it as a Power BI project (PBIP) in Power BI Desktop, then zip the project folder and open that.",
  ".pbip":
    "A .pbip file is only the project manifest — it points at the folders beside it and carries none of their contents. Zip the whole project folder and open that instead.",
  ".twbr": "Tableau .twbr files cannot be read here. Save the workbook as .twb or .twbx and open that.",
};

const NAMES: Record<Platform, string> = { tableau: "Tableau", powerbi: "Power BI" };

function other(source: Platform): Platform {
  return source === "tableau" ? "powerbi" : "tableau";
}

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
export function precheck(file: File, source: Platform = "tableau"): PrecheckResult {
  const extension = extensionOf(file.name);
  const accepted = ACCEPTED_BY_SOURCE[source];
  const thing = source === "tableau" ? "a Tableau workbook" : "a zipped Power BI project";

  const remedy = REMEDIES[extension];
  if (remedy !== undefined) {
    // A Power BI file opened for a Tableau migration also needs telling what
    // this migration does read, or the remedy sends them somewhere it cannot go.
    const also =
      source === "tableau" && extension.startsWith(".pb")
        ? ` This migration reads Tableau workbooks: ${accepted.join(" or ")}.`
        : "";
    return refuse(
      remedy + also,
      `client pre-check: extension ${extension} has a stated remedy`,
    );
  }

  // The other direction's file. Named as such, with the way out, because the
  // likeliest cause is a wrong card rather than a wrong file.
  const theirs = other(source);
  if (
    !accepted.includes(extension) &&
    ACCEPTED_BY_SOURCE[theirs].includes(extension)
  ) {
    return refuse(
      `That is ${theirs === "tableau" ? "a Tableau workbook" : "a Power BI project"}, and this migration reads ${NAMES[source]}. ` +
        `Go back and choose ${NAMES[theirs]} → ${NAMES[source]} to convert it.`,
      `client pre-check: extension ${extension} belongs to ${theirs}, source is ${source}`,
    );
  }

  if (!accepted.includes(extension)) {
    return refuse(
      `That is not ${thing}. Choose a ${accepted.join(" or ")} file.`,
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
export function precheckDrop(
  files: readonly File[],
  source: Platform = "tableau",
): PrecheckResult {
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
  return precheck(first, source);
}
