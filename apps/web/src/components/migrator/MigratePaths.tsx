"use client";

/**
 * Choose a migration path. Tableau → Power BI and MicroStrategy → Power BI have
 * an engine behind them; the rest are shown locked with the reason, so the
 * roadmap is visible without any card opening a screen that would claim otherwise.
 */

import { useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "./AppShell";
import { MigrateModal } from "./MigrateModal";
import { IconChart, IconDatabase, IconDoc, IconGlobe, IconLayers, IconLock, IconServer } from "./MgIcons";

interface Path {
  readonly id: string;
  readonly from: ReactNode;
  readonly to: ReactNode;
  readonly title: string;
  readonly description: string;
  /** Null when the path works; otherwise why it does not yet. */
  readonly locked: string | null;
}

const tableau = <IconLayers style={{ color: "var(--mg-tableau)" }} />;
const powerBi = <IconChart style={{ color: "var(--mg-powerbi)" }} />;

const PATHS: readonly Path[] = [
  {
    id: "tableau-powerbi",
    from: tableau,
    to: powerBi,
    title: "Tableau → Power BI",
    description: "Workbooks, calculated fields, data sources, dashboards",
    locked: null,
  },
  {
    id: "powerbi-tableau",
    from: powerBi,
    to: tableau,
    title: "Power BI → Tableau",
    description: "Semantic models, DAX measures, relationships",
    locked: "The engine exists; the screens for this direction are being finished.",
  },
  {
    id: "cognos-powerbi",
    from: <IconDatabase style={{ color: "#16a34a" }} />,
    to: powerBi,
    title: "Cognos → Power BI",
    description: "Framework Manager models, reports, packages",
    locked: "No Cognos reader exists yet.",
  },
  {
    id: "microstrategy-powerbi",
    from: <IconServer style={{ color: "#0891b2" }} />,
    to: powerBi,
    title: "MicroStrategy → Power BI",
    description: "Dossiers, reports, metrics, security filters — upload a .mstr package",
    locked: null,
  },
  {
    id: "looker-powerbi",
    from: <IconGlobe style={{ color: "#7c3aed" }} />,
    to: powerBi,
    title: "Looker → Power BI",
    description: "LookML models, explores, views, dimensions",
    locked: "No Looker reader exists yet.",
  },
  {
    id: "sapbo-powerbi",
    from: <IconDoc style={{ color: "#dc2626" }} />,
    to: powerBi,
    title: "SAP BO → Power BI",
    description: "Universes, reports, Crystal Reports, Web Intelligence",
    locked: "No SAP BusinessObjects reader exists yet.",
  },
];

export function MigratePaths() {
  const router = useRouter();
  const params = useSearchParams();
  const open = params.get("open");

  return (
    <AppShell crumbs={[{ label: "Migrate" }]}>
      <h1 className="mg-h1">Migrate</h1>
      <p className="mg-sub">Choose a migration path to convert your BI reports</p>

      <div className="mg-grid-2">
        {PATHS.map((path) => (
          <button
            key={path.id}
            type="button"
            className="mg-path"
            aria-disabled={path.locked !== null}
            title={path.locked ?? undefined}
            onClick={() => {
              if (path.locked === null) router.push(`/migrate?open=${path.id}`);
            }}
          >
            <span className="mg-path__icons">
              <span className="mg-chip">{path.from}</span>
              <span aria-hidden="true">→</span>
              <span className="mg-chip">{path.to}</span>
            </span>
            <span style={{ minWidth: 0 }}>
              <span className="mg-path__title">
                {path.title}
                {path.locked !== null && <IconLock size={13} aria-label="Not available yet" />}
              </span>
              <span className="mg-path__desc" style={{ display: "block" }}>
                {path.locked ?? path.description}
              </span>
            </span>
          </button>
        ))}
      </div>

      {open === "tableau-powerbi" && <MigrateModal source="tableau" onClose={() => router.push("/migrate")} />}
      {open === "microstrategy-powerbi" && (
        <MigrateModal key="microstrategy" source="microstrategy" onClose={() => router.push("/migrate")} />
      )}
    </AppShell>
  );
}
