/**
 * Every word in the interface that depends on which way a migration runs.
 *
 * SPEC-powerbi-to-tableau-web.md FR2: no screen may name the wrong platform.
 * Kept in one table rather than scattered through components, so a test can
 * read all of it and a new screen cannot hard-code "Power BI project" by habit —
 * which is exactly how every screen came to say it while only one direction
 * existed.
 */

import type { Platform } from "@/types/contracts";

export interface DirectionLike {
  readonly source: Platform;
  readonly target: Platform;
}

export interface DirectionCopy {
  readonly sourceName: string;
  readonly targetName: string;
  /** What a person opens: "a Tableau workbook", "a Power BI project". */
  readonly sourceThing: string;
  /** What they get back, without an article: "Power BI project". */
  readonly targetThing: string;
  readonly dropPrompt: string;
  readonly browseLabel: string;
  readonly inputLabel: string;
  /** The `accept` attribute of the file input. A hint to the picker only. */
  readonly accept: string;
  /** What the source's calculations become in the target. */
  readonly targetLanguage: string;
  readonly sourceLanguage: string;
  readonly convertExplainer: string;
  readonly download: string;
  readonly deliverable: string;
  readonly desktopCaveat: string;
  readonly noEquivalent: string;
  readonly visualsMeaning: string;
  readonly calculationsMeaning: string;
}

const TABLEAU_TO_POWER_BI: DirectionCopy = {
  sourceName: "Tableau",
  targetName: "Power BI",
  sourceThing: "a Tableau workbook",
  targetThing: "Power BI project",
  dropPrompt: "Drop a Tableau workbook to begin",
  browseLabel: "Browse for a workbook",
  inputLabel: "Choose a Tableau workbook",
  accept: ".twb,.twbx",
  targetLanguage: "DAX",
  sourceLanguage: "Tableau calculation",
  convertExplainer:
    "Converting produces a Power BI project you can download. It changes nothing about the file you opened.",
  download: "Download the Power BI project",
  deliverable:
    "A Power BI project — TMDL semantic model and PBIR report — delivered as an archive, because a PBIP is a folder rather than a single file.",
  desktopCaveat:
    "No generated project has yet been opened in Power BI Desktop. The output satisfies what we know of the TMDL and PBIR formats by reasoning, not by observation, and until it has been opened that is all this can claim.",
  noEquivalent: "Power BI has no equivalent. Rebuilding it is a design decision.",
  visualsMeaning: "Worksheets to rebuild as Power BI visuals",
  calculationsMeaning: "Expressions needing DAX, or a person",
};

const POWER_BI_TO_TABLEAU: DirectionCopy = {
  sourceName: "Power BI",
  targetName: "Tableau",
  sourceThing: "a Power BI project",
  targetThing: "Tableau workbook",
  dropPrompt: "Drop a zipped Power BI project to begin",
  browseLabel: "Browse for a project",
  inputLabel: "Choose a zipped Power BI project folder",
  accept: ".zip",
  targetLanguage: "Tableau calculations",
  sourceLanguage: "DAX",
  convertExplainer:
    "Converting produces a Tableau workbook you can download. It changes nothing about the project you opened.",
  download: "Download the Tableau workbook",
  deliverable:
    "A Tableau workbook (.twb) — data sources, calculated fields, worksheets and dashboards. It holds the schema and no data, so point each data source at your copy.",
  desktopCaveat:
    "No generated workbook has yet been opened in Tableau Desktop. The output follows the structure of workbooks Tableau itself writes, by reasoning rather than observation, and until one has been opened that is all this can claim.",
  noEquivalent: "Tableau has no equivalent. Rebuilding it is a design decision.",
  visualsMeaning: "Visuals to rebuild as Tableau worksheets",
  calculationsMeaning: "Measures and calculated columns needing a Tableau formula, or a person",
};

const MICROSTRATEGY_TO_POWER_BI: DirectionCopy = {
  sourceName: "MicroStrategy",
  targetName: "Power BI",
  sourceThing: "a MicroStrategy package",
  targetThing: "Power BI project",
  dropPrompt: "Drop a MicroStrategy .mstr package or zipped metadata export to begin",
  browseLabel: "Browse for a package",
  inputLabel: "Choose a MicroStrategy .mstr package or zipped metadata export",
  accept: ".mstr,.zip",
  targetLanguage: "DAX",
  sourceLanguage: "MicroStrategy metric",
  convertExplainer:
    "Converting produces a Power BI project you can download: one shared semantic model for the MicroStrategy project, with a page per dossier page and report. It changes nothing about the file you opened.",
  download: "Download the Power BI project",
  deliverable:
    "A Power BI project — TMDL semantic model and PBIR report — delivered as an archive, with the migration report and data-parity DAX queries beside it.",
  desktopCaveat:
    "No project generated from MicroStrategy has yet been opened in Power BI Desktop, and the .mstr reader has only seen synthetic packages. Until a real package has been converted and opened, that is all this can claim.",
  noEquivalent: "Power BI has no equivalent. Rebuilding it is a design decision.",
  visualsMeaning: "Dossier visualizations and report grids to rebuild as Power BI visuals",
  calculationsMeaning: "Metrics needing DAX, or a person",
};

const QLIK_TO_POWER_BI: DirectionCopy = {
  sourceName: "Qlik",
  targetName: "Power BI",
  sourceThing: "a Qlik app export",
  targetThing: "Power BI project",
  dropPrompt: "Drop a zipped qlik app unbuild folder or a .qvs load script to begin",
  browseLabel: "Browse for an export",
  inputLabel: "Choose a zipped Qlik app export or a .qvs load script",
  accept: ".zip,.qvs",
  targetLanguage: "DAX",
  sourceLanguage: "Qlik expression",
  convertExplainer:
    "Converting produces a Power BI project you can download: the load script as Power Query, the associative model as a star schema, set analysis as DAX and each sheet as a page. It changes nothing about the file you opened.",
  download: "Download the Power BI project",
  deliverable:
    "A Power BI project — TMDL semantic model and PBIR report — delivered as an archive, with the migration report and data-parity DAX queries beside it.",
  desktopCaveat:
    "No project generated from Qlik has yet been opened in Power BI Desktop, and the reader has only seen a synthetic app. Until a real app has been converted and opened, that is all this can claim.",
  noEquivalent: "Power BI has no equivalent. Rebuilding it is a design decision.",
  visualsMeaning: "Sheet objects to rebuild as Power BI visuals",
  calculationsMeaning: "Master measures and chart expressions needing DAX, or a person",
};

/**
 * The words for a direction. `null` means none has been chosen yet, which only
 * happens on screens that existed before there was a second direction — they
 * get the words they have always had.
 */
export function copyFor(direction: DirectionLike | null | undefined): DirectionCopy {
  if (direction?.source === "powerbi") return POWER_BI_TO_TABLEAU;
  if (direction?.source === "microstrategy") return MICROSTRATEGY_TO_POWER_BI;
  if (direction?.source === "qlik") return QLIK_TO_POWER_BI;
  return TABLEAU_TO_POWER_BI;
}
