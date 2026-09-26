"use client";

/**
 * Choose a source file, then start the migration: Tableau → Power BI, or
 * MicroStrategy → Power BI. Which one is the `source` prop; every word and
 * check that depends on it comes from `copyFor`, `precheck` and `platforms`.
 *
 * Starting creates the project and uploads the file, then hands over to the job
 * screen, which runs analysis and conversion and shows the log as each step
 * actually returns. Nothing here pretends to progress.
 */

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { createProject, listProjects, toApiError, uploadArtifact } from "@/lib/api/client";
import { copyFor } from "@/lib/direction/copy";
import { TARGET_OF, directionLabel } from "@/lib/platforms";
import { ACCEPTED_BY_SOURCE, formatBytes, precheck, precheckDrop } from "@/lib/upload/precheck";
import type { ApiError, Platform, Project } from "@/types/contracts";

import {
  IconArrow,
  IconChart,
  IconClose,
  IconDoc,
  IconLayers,
  IconServer,
  IconUpload,
} from "./MgIcons";

type Tab = "upload" | "analyzed" | "server";

function stem(filename: string, source: Platform): string {
  const lower = filename.toLowerCase();
  const extension = ACCEPTED_BY_SOURCE[source].find((candidate) => lower.endsWith(candidate));
  const trimmed = extension ? filename.slice(0, -extension.length) : filename;
  return trimmed || (source === "microstrategy" ? "MicroStrategy project" : "Workbook");
}

/** Where a server-hosted source would come from, and what to do instead today. */
const SERVER_NOTE: Record<Platform, readonly [string, string]> = {
  tableau: [
    "Reading from Tableau Server or Cloud is not connected yet.",
    "Download the workbook from the server and upload the .twb or .twbx instead.",
  ],
  powerbi: [
    "Reading from the Power BI service is not connected yet.",
    "Save the report as a Power BI project, zip the folder and upload that instead.",
  ],
  microstrategy: [
    "Reading from a MicroStrategy Library server is not connected here yet.",
    "Download the dossier as a .mstr file, or run `mstr2pbi extract` inside your network and upload the zipped bundle.",
  ],
};

export function MigrateModal({
  onClose,
  source = "tableau",
}: {
  readonly onClose: () => void;
  readonly source?: Platform;
}) {
  const target = TARGET_OF[source];
  const copy = copyFor({ source, target });
  const accepted = ACCEPTED_BY_SOURCE[source];
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [previous, setPrevious] = useState<Project[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && busy === null) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  useEffect(() => {
    if (tab !== "analyzed" || previous !== null) return;
    listProjects()
      .then((projects) =>
        setPrevious(
          projects.filter(
            (project) => project.source_platform === source && project.target_platform === target,
          ),
        ),
      )
      .catch((cause) => setError(toApiError(cause)));
  }, [tab, previous, source, target]);

  function accept(result: ReturnType<typeof precheck>) {
    if (result.ok) {
      setFile(result.file);
      setError(null);
    } else {
      setFile(null);
      setError(result.error);
    }
  }

  async function start() {
    setError(null);
    try {
      if (tab === "analyzed" && picked) {
        router.push(`/jobs/${picked}?start=1`);
        return;
      }
      if (!file) return;
      setBusy("Creating the migration…");
      const project = await createProject({
        source_platform: source,
        target_platform: target,
        name: stem(file.name, source),
      });
      setBusy(`Sending ${file.name}…`);
      await uploadArtifact(project.project_id, file);
      router.push(`/jobs/${project.project_id}?start=1`);
    } catch (cause) {
      setError(toApiError(cause));
      setBusy(null);
    }
  }

  const ready = tab === "upload" ? file !== null : tab === "analyzed" ? picked !== null : false;

  return (
    <div
      className="mg-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && busy === null) onClose();
      }}
    >
      <div
        ref={dialog}
        className="mg-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="migrate-title"
        tabIndex={-1}
      >
        <div className="mg-modal__head">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="mg-chip" style={{ color: source === "microstrategy" ? "#0891b2" : "var(--mg-tableau)" }}>
              {source === "microstrategy" ? <IconServer /> : <IconLayers />}
            </span>
            <span style={{ color: "var(--mg-ink-3)" }}>→</span>
            <span className="mg-chip" style={{ color: "var(--mg-powerbi)" }}>
              <IconChart />
            </span>
            <h2 id="migrate-title" style={{ margin: 0, fontSize: 17 }}>
              {directionLabel(source, target)}
            </h2>
          </div>
          <button type="button" className="mg-iconbtn" onClick={onClose} aria-label="Close" disabled={busy !== null}>
            <IconClose />
          </button>
        </div>

        <div className="mg-tabs" role="tablist" aria-label="Where the source file comes from">
          <button type="button" role="tab" className="mg-tab" aria-selected={tab === "upload"} onClick={() => setTab("upload")}>
            <IconUpload size={14} /> Upload File
          </button>
          <button type="button" role="tab" className="mg-tab" aria-selected={tab === "analyzed"} onClick={() => setTab("analyzed")}>
            <IconDoc size={14} /> Analyzed
          </button>
          <button
            type="button"
            role="tab"
            className="mg-tab"
            aria-selected={tab === "server"}
            onClick={() => setTab("server")}
          >
            <IconServer size={14} /> From Server
          </button>
        </div>

        {tab === "upload" && (
          <>
            <button
              type="button"
              className="mg-drop"
              data-dragging={dragging}
              onClick={() => input.current?.click()}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                accept(precheckDrop(Array.from(event.dataTransfer.files), source));
              }}
            >
              <IconUpload size={26} />
              {file ? (
                <>
                  <div style={{ marginTop: 10, fontWeight: 600 }}>{file.name}</div>
                  <div className="mg-drop__hint">{formatBytes(file.size)} · click to choose another</div>
                </>
              ) : (
                <>
                  <div style={{ marginTop: 10 }}>Drop {accepted.join(" or ")} file here</div>
                  <div className="mg-drop__hint">or click to browse</div>
                </>
              )}
            </button>
            <input
              ref={input}
              type="file"
              accept={copy.accept}
              hidden
              aria-label={copy.inputLabel}
              onChange={(event) => {
                const chosen = event.target.files?.[0];
                if (chosen) accept(precheck(chosen, source));
                event.target.value = "";
              }}
            />
          </>
        )}

        {tab === "analyzed" && (
          <div style={{ marginTop: 14, maxHeight: 220, overflowY: "auto" }} role="radiogroup" aria-label="Previous migrations">
            {previous === null ? (
              <p className="mg-note">Loading previous migrations…</p>
            ) : previous.length === 0 ? (
              <p className="mg-note">No {copy.sourceName} file has been opened here yet. Upload one to begin.</p>
            ) : (
              previous.map((project) => (
                <button
                  key={project.project_id}
                  type="button"
                  role="radio"
                  aria-checked={picked === project.project_id}
                  className="mg-option"
                  onClick={() => setPicked(project.project_id)}
                >
                  <IconDoc size={14} />
                  <strong>{project.name}</strong>
                  <span className="mg-note" style={{ marginLeft: "auto" }}>
                    {new Date(project.created_at).toLocaleString()}
                  </span>
                </button>
              ))
            )}
          </div>
        )}

        {tab === "server" && (
          <div className="mg-empty" style={{ padding: "28px 8px" }}>
            <IconServer size={24} />
            <p style={{ margin: "8px 0 0" }}>{SERVER_NOTE[source][0]}</p>
            <p className="mg-note">{SERVER_NOTE[source][1]}</p>
          </div>
        )}

        <span className="mg-field-label" id="db-label">
          Database Connection (optional)
        </span>
        <div role="radiogroup" aria-labelledby="db-label">
          <button type="button" role="radio" aria-checked="true" className="mg-option">
            None — use defaults
          </button>
          <button type="button" role="radio" aria-checked="false" aria-disabled="true" className="mg-option" title="Database connections are configured by an administrator; none is set up yet">
            <span className="mg-note">No database connections are configured on this deployment</span>
          </button>
        </div>

        {error && (
          <div className="mg-error" role="alert">
            {error.message}
          </div>
        )}

        <button
          type="button"
          className="mg-btn mg-btn--primary mg-btn--block"
          style={{ marginTop: 16 }}
          disabled={!ready || busy !== null}
          onClick={() => void start()}
        >
          <IconArrow size={15} /> {busy ?? "Start Migration"}
        </button>
      </div>
    </div>
  );
}
