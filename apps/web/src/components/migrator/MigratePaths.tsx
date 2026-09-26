"use client";

/**
 * Choose a migration path.
 *
 * Engines are sold separately, so which cards open depends on the deployment:
 * `GET /directions` says which engines are installed and licensed, and a card
 * whose engine is missing or unlicensed is shown locked with the server's
 * reason. Paths with no engine at all (the roadmap) are always locked.
 */

import { useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { useDirections } from "@/lib/hooks/useDirections";
import { directionLock } from "@/lib/migrator/paths";
import type { Platform } from "@/types/contracts";

import { AppShell } from "./AppShell";
import { MigrateModal } from "./MigrateModal";
import { IconChart, IconDatabase, IconDoc, IconGlobe, IconLayers, IconLock, IconServer, IconSigma } from "./MgIcons";

interface Path {
  readonly id: string;
  readonly from: ReactNode;
  readonly to: ReactNode;
  readonly title: string;
  readonly description: string;
  /** A reason that locks the card whatever the deployment has (roadmap, unfinished screens). */
  readonly locked: string | null;
  /** The direction an engine runs - its availability comes from the server. */
  readonly direction?: readonly [Platform, Platform];
}

const tableau = <IconLayers style={{ color: "var(--mg-tableau)" }} />;
const powerBi = <IconChart style={{ color: "var(--mg-powerbi)" }} />;

const PATHS: readonly Path[] = [
  {
    id: "tableau-powerbi",
    direction: ["tableau", "powerbi"],
    from: tableau,
    to: powerBi,
    title: "Tableau → Power BI",
    description: "Workbooks, calculated fields, data sources, dashboards",
    locked: null,
  },
  {
    id: "powerbi-tableau",
    direction: ["powerbi", "tableau"],
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
    direction: ["microstrategy", "powerbi"],
    from: <IconServer style={{ color: "#0891b2" }} />,
    to: powerBi,
    title: "MicroStrategy → Power BI",
    description: "Dossiers, reports, metrics, security filters — upload a .mstr package",
    locked: null,
  },
  {
    id: "qlik-powerbi",
    direction: ["qlik", "powerbi"],
    from: <IconSigma style={{ color: "#009845" }} />,
    to: powerBi,
    title: "Qlik → Power BI",
    description: "Load scripts, set analysis, sheets — upload a .zip export or .qvs",
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
  const probe = useDirections();
  const lockOf = (path: Path): string | null =>
    path.locked ?? (path.direction ? directionLock(probe, path.direction[0], path.direction[1]) : null);
  const opens = (id: string) => {
    const path = PATHS.find((p) => p.id === id);
    return open === id && path !== undefined && lockOf(path) === null;
  };

  return (
    <AppShell crumbs={[{ label: "Migrate" }]}>
      <h1 className="mg-h1">Migrate</h1>
      <p className="mg-sub">Choose a migration path to convert your BI reports</p>

      <div className="mg-grid-2">
        {PATHS.map((path) => {
          const locked = lockOf(path);
          return (
          <button
            key={path.id}
            type="button"
            className="mg-path"
            aria-disabled={locked !== null}
            title={locked ?? undefined}
            onClick={() => {
              if (locked === null) router.push(`/migrate?open=${path.id}`);
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
                {locked !== null && <IconLock size={13} aria-label="Not available" />}
              </span>
              <span className="mg-path__desc" style={{ display: "block" }}>
                {locked ?? path.description}
              </span>
            </span>
          </button>
          );
        })}
      </div>

      {opens("tableau-powerbi") && <MigrateModal source="tableau" onClose={() => router.push("/migrate")} />}
      {opens("microstrategy-powerbi") && (
        <MigrateModal key="microstrategy" source="microstrategy" onClose={() => router.push("/migrate")} />
      )}
      {opens("qlik-powerbi") && <MigrateModal key="qlik" source="qlik" onClose={() => router.push("/migrate")} />}
    </AppShell>
  );
}
