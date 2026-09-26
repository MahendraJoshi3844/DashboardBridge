"use client";

/**
 * One migration job: what it is, how far it got, and its log, files and model.
 *
 * Opened with `?start=1` it runs whatever steps are left; otherwise it reads
 * back what already happened. `lib/migrator/job.ts` owns the order of the steps
 * and every word of the log; this renders.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  downloadArtifact,
  getProject,
  getWorkspace,
  getWorkspaceFile,
  reportUrl,
  toApiError,
} from "@/lib/api/client";
import { saveBlob } from "@/lib/download";
import { directionLabel } from "@/lib/platforms";
import { STEPS, emptySnapshot, formatLine, readJob, runJob, type JobSnapshot } from "@/lib/migrator/job";
import type { ApiError, Project, WorkspaceModel } from "@/types/contracts";

import { AppShell } from "./AppShell";
import { IconDoc, IconDownload, IconEye, IconSigma, IconTable } from "./MgIcons";

type Tab = "logs" | "files" | "model";

export function JobDetail({ projectId }: { readonly projectId: string }) {
  const params = useSearchParams();
  const start = params.get("start") === "1";
  const [project, setProject] = useState<Project | null>(null);
  const direction = project ? directionLabel(project.source_platform, project.target_platform) : "…";
  const [snapshot, setSnapshot] = useState<JobSnapshot>(emptySnapshot);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<Tab>("logs");
  const [autoScroll, setAutoScroll] = useState(true);
  const [workspace, setWorkspace] = useState<WorkspaceModel | null>(null);
  const [openFile, setOpenFile] = useState<{ path: string; text: string } | null>(null);
  const consoleRef = useRef<HTMLDivElement>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const controller = new AbortController();
    getProject(projectId, { signal: controller.signal })
      .then(async (found) => {
        setProject(found);
        if (start) {
          await runJob(found, setSnapshot, controller.signal);
        } else {
          setSnapshot(await readJob(found));
        }
      })
      .catch((cause) => setFailure(toApiError(cause)));
  }, [projectId, start]);

  const complete = snapshot.done.size === STEPS.length && !snapshot.running;
  const percent = Math.round((snapshot.done.size / STEPS.length) * 100);

  useEffect(() => {
    if (!snapshot.done.has("Converted") || workspace !== null) return;
    getWorkspace(projectId)
      .then(setWorkspace)
      .catch(() => {
        // The job screen works without it; the Files and Model tabs say so.
      });
  }, [projectId, snapshot.done, workspace]);

  useEffect(() => {
    if (autoScroll && consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [snapshot.lines.length, autoScroll]);

  const logText = useMemo(() => snapshot.lines.map(formatLine).join("\n"), [snapshot.lines]);

  async function download() {
    try {
      const { blob, filename } = await downloadArtifact(projectId, `${project?.name ?? "project"}.pbip.zip`);
      saveBlob(blob, filename);
    } catch (cause) {
      setFailure(toApiError(cause));
    }
  }

  async function view(path: string) {
    try {
      setOpenFile({ path, text: await getWorkspaceFile(projectId, path) });
    } catch (cause) {
      setFailure(toApiError(cause));
    }
  }

  const status = snapshot.error
    ? "Stopped"
    : complete
      ? "Complete"
      : snapshot.running
        ? `${percent}% Complete`
        : snapshot.done.size === 0
          ? "Loading…"
          : `${percent}% — not finished`;

  return (
    <AppShell
      crumbs={[
        { label: "Migration Jobs", href: "/jobs" },
        { label: project?.name ?? "Job Detail" },
      ]}
    >
      {failure && (
        <div className="mg-error" role="alert" style={{ marginTop: 0, marginBottom: 14 }}>
          {failure.message}
        </div>
      )}

      <div className="mg-grid-3">
        <div className="mg-card mg-stat">
          <div className="mg-stat__label">Migration Type</div>
          <div className="mg-stat__value">{project?.source_platform === "microstrategy" ? "Migrate MicroStrategy Project" : project?.source_platform === "qlik" ? "Migrate Qlik App" : "Migrate Single Workbook"}</div>
          <div className="mg-note">{direction} · {project?.name ?? "…"}</div>
        </div>
        <div className="mg-card mg-stat">
          <div className="mg-stat__label">Load Mode</div>
          <div className="mg-stat__value">Import</div>
          <div className="mg-note">Schema only — no data is read from the {project?.source_platform === "microstrategy" || project?.source_platform === "qlik" ? "export" : "workbook"}</div>
        </div>
        <div className="mg-card mg-stat" aria-live="polite">
          <div className="mg-stat__label">Status</div>
          <div className="mg-stat__value">{status}</div>
          <div
            className="mg-progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={STEPS.length}
            aria-valuenow={snapshot.done.size}
            aria-valuetext={`${snapshot.done.size} of ${STEPS.length} steps done`}
          >
            <span style={{ width: `${percent}%` }} />
          </div>
          <div className="mg-note" style={{ marginTop: 6 }}>
            {snapshot.done.size} of {STEPS.length} steps: {STEPS.filter((step) => snapshot.done.has(step)).join(" · ") || "none yet"}
          </div>
        </div>
      </div>

      <details className="mg-card mg-details">
        <summary>Migration Settings</summary>
        <dl className="mg-kv">
          <dt>Direction</dt>
          <dd>{direction} (PBIP: TMDL semantic model + PBIR report)</dd>
          <dt>Conversion</dt>
          <dd>Deterministic rules only. Anything without a safe DAX equivalent is held for a person, never guessed.</dd>
          <dt>AI assistance</dt>
          <dd>Off</dd>
          <dt>Data</dt>
          <dd>Schema only. Tables are written with empty Power Query sources for you to point at your data.</dd>
          <dt>Privacy</dt>
          <dd>Processed on this machine; nothing is sent elsewhere.</dd>
        </dl>
      </details>

      {complete && (
        <div className="mg-card" style={{ marginTop: 14, padding: "14px 16px", display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <strong style={{ marginRight: "auto" }}>Your Power BI project is ready.</strong>
          <Link className="mg-btn mg-btn--primary" href={`/workspace/powerbi/${projectId}`}>
            Open in Workspace
          </Link>
          <button type="button" className="mg-btn" onClick={() => void download()}>
            <IconDownload size={14} /> Download .pbip
          </button>
          <a className="mg-btn" href={reportUrl(projectId)} target="_blank" rel="noreferrer">
            <IconDoc size={14} /> Migration report
          </a>
        </div>
      )}

      <div className="mg-tabs mg-tabs--line" role="tablist" style={{ marginTop: 18 }}>
        {(
          [
            ["logs", "Logs"],
            ["files", "Files"],
            ["model", "Power BI Model"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} type="button" role="tab" className="mg-tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "logs" && (
        <section className="mg-card" style={{ marginTop: 12 }} aria-labelledby="logs-title">
          <div className="mg-panelhead">
            <strong id="logs-title">Migration Logs</strong>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <label className="mg-note" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={autoScroll} onChange={(event) => setAutoScroll(event.target.checked)} />
                Auto-scroll
              </label>
              <button
                type="button"
                className="mg-btn mg-btn--sm"
                disabled={snapshot.lines.length === 0}
                onClick={() => saveBlob(new Blob([logText + "\n"], { type: "text/plain" }), `${project?.name ?? "migration"}-log.txt`)}
              >
                <IconDownload size={13} /> Download Logs
              </button>
            </div>
          </div>
          <div ref={consoleRef} className="mg-console" role="log" aria-live="polite" tabIndex={0}>
            {snapshot.lines.length === 0 ? (
              <span className="mg-log__time">Waiting for the first step…</span>
            ) : (
              snapshot.lines.map((entry, index) => {
                const [time, ...rest] = formatLine(entry).split(" [");
                return (
                  <div key={index}>
                    <span className="mg-log__time">{time}</span>{" "}
                    <span className={`mg-log__${entry.level}`}>[{entry.level}]</span>{" "}
                    {rest.join(" [").replace(/^[A-Z]+\] /, "")}
                  </div>
                );
              })
            )}
          </div>
        </section>
      )}

      {tab === "files" && (
        <section className="mg-card" style={{ marginTop: 12 }}>
          {workspace === null ? (
            <p className="mg-empty">The project's files appear here once it has been converted.</p>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: openFile ? "minmax(0,1fr) minmax(0,1.3fr)" : "minmax(0,1fr)" }}>
              <table className="mg-table mg-table--fixed">
                <thead>
                  <tr>
                    <th>File</th>
                    <th style={{ textAlign: "right", width: 90 }}>Size</th>
                    <th style={{ width: 44 }} />
                  </tr>
                </thead>
                <tbody>
                  {workspace.files?.map((file) => (
                    <tr key={file.path}>
                      <td className="mg-mono" style={{ fontSize: 12 }}>{file.path}</td>
                      <td style={{ textAlign: "right" }}>{file.size_bytes.toLocaleString()} B</td>
                      <td>
                        <button type="button" className="mg-link" onClick={() => void view(file.path)} aria-label={`View ${file.path}`}>
                          <IconEye size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {openFile && (
                <div style={{ borderLeft: "1px solid var(--mg-line)", minWidth: 0 }}>
                  <div className="mg-panelhead">
                    <span className="mg-mono" style={{ fontSize: 12 }}>{openFile.path}</span>
                    <button type="button" className="mg-btn mg-btn--sm" onClick={() => setOpenFile(null)}>
                      Close
                    </button>
                  </div>
                  <pre className="mg-console" style={{ margin: 0, borderRadius: 0 }}>{openFile.text}</pre>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {tab === "model" && (
        <section className="mg-card" style={{ marginTop: 12 }}>
          {workspace === null ? (
            <p className="mg-empty">The Power BI model appears here once the source has been converted.</p>
          ) : (
            <>
              <div className="mg-panelhead">
                <span>
                  {workspace.tables?.length ?? 0} tables · v{workspace.version} ·{" "}
                  {workspace.held?.length ?? 0} calculations held for you
                </span>
                <Link className="mg-btn mg-btn--primary mg-btn--sm" href={`/workspace/powerbi/${projectId}`}>
                  Open in Workspace
                </Link>
              </div>
              <table className="mg-table">
                <thead>
                  <tr>
                    <th>Table</th>
                    <th>Columns</th>
                    <th>Measures</th>
                    <th>Power Query</th>
                  </tr>
                </thead>
                <tbody>
                  {workspace.tables?.map((table) => (
                    <tr key={table.name}>
                      <td>
                        <IconTable size={13} /> {table.name}
                      </td>
                      <td>{table.columns?.length ?? 0}</td>
                      <td>
                        <IconSigma size={13} /> {table.measures?.length ?? 0}
                      </td>
                      <td>{table.partitions?.map((partition) => partition.mode || "m").join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}
    </AppShell>
  );
}
