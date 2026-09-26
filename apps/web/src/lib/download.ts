/**
 * Handing a file to the browser.
 *
 * Two things live here and they are deliberately separate:
 *
 * * `producedName` is **pure** — it derives the name to save under from the
 *   name the user opened. It is used only when the server's own
 *   `content-disposition` is unreadable, which is the normal case across an
 *   origin: a browser cannot read a response header that is not listed in
 *   `Access-Control-Expose-Headers`, and the gateway lists two headers, neither
 *   of them this one.
 * * `saveBlob` is the DOM plumbing. It is here rather than in a component for
 *   the same reason transport is: a screen should ask for a thing to be saved,
 *   not know how a browser is persuaded to save it.
 */

/** Source extensions, longest first so `.twbx` is not left as `x`. */
const SOURCE_EXTENSIONS: readonly string[] = [".twbx", ".twb", ".mstr", ".qvs", ".zip"];

/**
 * The name to save the produced file under.
 *
 * A PBIP is a folder, so what arrives is an archive of one — the name says so
 * rather than implying a single Power BI file the user could double-click. A
 * Tableau workbook is one file, and is named as one.
 */
export function producedName(
  sourceFilename: string,
  target: "powerbi" | "tableau" = "powerbi",
): string {
  const suffix = target === "tableau" ? ".twb" : ".pbip.zip";
  const fallback = target === "tableau" ? "dashboardbridge-workbook" : "dashboardbridge-project";
  const trimmed = sourceFilename.trim();
  if (trimmed === "") return `${fallback}${suffix}`;
  const lower = trimmed.toLowerCase();
  const matched = SOURCE_EXTENSIONS.find((extension) =>
    lower.endsWith(extension),
  );
  const stem = matched ? trimmed.slice(0, -matched.length) : trimmed;
  return `${stem === "" ? fallback : stem}${suffix}`;
}

/**
 * Save a blob under a name, then release the object URL.
 *
 * The URL is revoked on the next frame rather than immediately: revoking in the
 * same task cancels the navigation the click just started in some browsers, and
 * the download silently does not happen.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
