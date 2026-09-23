"use client";

import { motion } from "motion/react";
import { useCallback, useId, useRef, useState } from "react";

import {
  ACCEPTED_EXTENSIONS,
  MAX_UPLOAD_MB,
  formatBytes,
  precheck,
  precheckDrop,
} from "@/lib/upload/precheck";
import type { ApiError } from "@/types/contracts";

import { FileIcon, UploadIcon } from "./Icons";

/**
 * Choose one workbook, by dropping it or by browsing for it.
 *
 * Hand-rolled rather than react-dropzone: the whole behaviour is four drag
 * events and a file input, and the product ships air-gapped, where every
 * dependency is a thing that has to be vendored, audited and updated.
 *
 * Keyboard first. The drop surface is decoration for people who use a mouse;
 * the *control* is a real `<button>` that opens the file picker, so the flow is
 * completable with Tab and Enter alone and the focus ring is the browser's own.
 * A `<div>` with a drop handler is invisible to a keyboard, so it is never the
 * only way in.
 */
export function Dropzone({
  onAccepted,
  onRefused,
  disabled = false,
}: {
  readonly onAccepted: (file: File) => void;
  /** A pre-check refusal, in the contract error shape the screens already render. */
  readonly onRefused: (error: ApiError) => void;
  readonly disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const hintId = useId();

  const handle = useCallback(
    (files: readonly File[]) => {
      const result = precheckDrop(files);
      if (result.ok) onAccepted(result.file);
      else onRefused(result.error);
    },
    [onAccepted, onRefused],
  );

  return (
    <div
      // Not a tab stop and not labelled as a control: the button inside is the
      // control. Two tab stops for one action is noise for keyboard users.
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={(event) => {
        // Only when the pointer leaves the zone itself, not a child of it.
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (disabled) return;
        handle(Array.from(event.dataTransfer.files));
      }}
      className={[
        "panel flex flex-col items-center justify-center px-6 py-12 text-center transition-colors sm:py-16",
        dragging ? "border-line-strong bg-surface-strong" : "",
        disabled ? "opacity-60" : "",
      ].join(" ")}
    >
      <motion.span
        animate={dragging ? { y: -4, scale: 1.04 } : { y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 26 }}
        className="flex h-12 w-12 items-center justify-center rounded-control border border-line text-source"
      >
        {dragging ? (
          <FileIcon className="h-6 w-6" />
        ) : (
          <UploadIcon className="h-6 w-6" />
        )}
      </motion.span>

      <p className="mt-5 text-lg font-semibold tracking-tight text-ink">
        {dragging ? "Let go to open it" : "Drop a Tableau workbook to begin"}
      </p>

      <p className="mt-2 max-w-md text-sm leading-relaxed text-ink-muted">
        It is read on this machine. Nothing is sent anywhere you have not chosen.
      </p>

      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        aria-describedby={hintId}
        aria-label="Choose a Tableau workbook"
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0];
          // The picker is reset so choosing the same file twice still fires.
          event.target.value = "";
          if (file === undefined) return;
          const result = precheck(file);
          if (result.ok) onAccepted(result.file);
          else onRefused(result.error);
        }}
      />

      <button
        type="button"
        className="btn mt-6"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        <UploadIcon className="h-4 w-4" />
        Browse for a workbook
      </button>

      <p id={hintId} className="data mt-4 text-xs text-ink-faint">
        {ACCEPTED_EXTENSIONS.join(" or ")} · up to {MAX_UPLOAD_MB} MB
      </p>
    </div>
  );
}

/** What was chosen, stated in the terms the user gave it. */
export function ChosenFile({ file }: { readonly file: File }) {
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink">
      <FileIcon className="h-4 w-4 shrink-0 text-source" />
      <span className="data break-all">{file.name}</span>
      <span className="data text-xs text-ink-faint">{formatBytes(file.size)}</span>
    </p>
  );
}
