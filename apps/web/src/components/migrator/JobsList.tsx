"use client";

/** Every migration on this deployment, newest first, with how far each got. */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getConversion, listProjects, toApiError } from "@/lib/api/client";
import type { ApiError, Compatibility, Project } from "@/types/contracts";

import { AppShell } from "./AppShell";

type Status = { readonly phase: "loading" } | { readonly phase: "converted"; readonly counts: Compatibility | undefined } | { readonly phase: "not-converted" };

const NAMES = { tableau: "Tableau", powerbi: "Power BI" } as const;

export function JobsList() {
  const query = (useSearchParams().get("q") ?? "").toLowerCase();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [statuses, setStatuses] = useState<Record<string, Status>>({});
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    listProjects()
      .then((found) => {
        const sorted = [...found].sort((a, b) => b.created_at.localeCompare(a.created_at));
        setProjects(sorted);
        for (const project of sorted.slice(0, 50)) {
          getConversion(project.project_id)
            .then((conversion) =>
              setStatuses((current) => ({ ...current, [project.project_id]: { phase: "converted", counts: conversion.compatibility } })),
            )
            .catch(() => setStatuses((current) => ({ ...current, [project.project_id]: { phase: "not-converted" } })));
        }
      })
      .catch((cause) => setError(toApiError(cause)));
  }, []);

  const shown = (projects ?? []).filter((project) => project.name.toLowerCase().includes(query));

  return (
    <AppShell crumbs={[{ label: "Migration Jobs" }]}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 className="mg-h1">Migration Jobs</h1>
          <p className="mg-sub">{query ? `Jobs matching “${query}”` : "Every migration run on this deployment"}</p>
        </div>
        <Link href="/migrate?open=tableau-powerbi" className="mg-btn mg-btn--primary">
          New migration
        </Link>
      </div>
      {error && <div className="mg-error" role="alert">{error.message}</div>}
      <div className="mg-card">
        {projects === null ? (
          <p className="mg-empty">Loading…</p>
        ) : shown.length === 0 ? (
          <p className="mg-empty">
            No migrations yet. <Link className="mg-link" href="/migrate?open=tableau-powerbi">Start one</Link>.
          </p>
        ) : (
          <table className="mg-table">
            <thead>
              <tr>
                <th>Workbook</th>
                <th>Path</th>
                <th>Status</th>
                <th>Started</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((project) => {
                const status = statuses[project.project_id] ?? { phase: "loading" };
                const canOpen = status.phase === "converted" && project.target_platform === "powerbi";
                return (
                  <tr key={project.project_id}>
                    <td>
                      <Link className="mg-link" href={`/jobs/${project.project_id}`}>{project.name}</Link>
                    </td>
                    <td>{NAMES[project.source_platform]} → {NAMES[project.target_platform]}</td>
                    <td>
                      {status.phase === "loading" ? (
                        <span className="mg-note">…</span>
                      ) : status.phase === "converted" ? (
                        <span className="mg-pill mg-pill--good">
                          Converted{status.counts ? ` · ${status.counts.converted}/${status.counts.total}` : ""}
                        </span>
                      ) : (
                        <span className="mg-pill mg-pill--soft">Not converted</span>
                      )}
                    </td>
                    <td className="mg-note">{new Date(project.created_at).toLocaleString()}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {status.phase === "not-converted" && (
                        <Link className="mg-btn mg-btn--sm" href={`/jobs/${project.project_id}?start=1`}>Resume</Link>
                      )}
                      {canOpen && (
                        <Link className="mg-btn mg-btn--sm" href={`/workspace/powerbi/${project.project_id}`}>Workspace</Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </AppShell>
  );
}
