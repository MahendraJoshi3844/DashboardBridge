/**
 * The workspace's own logic, kept out of the component: draft edits, and a
 * reference check for DAX.
 *
 * The reference check is exactly that and is named so. It finds `Table[Column]`
 * and `[Measure]` references and says which ones name nothing in this model. It
 * does not parse DAX, check types or evaluate anything, and the screen never
 * calls it validation.
 */

import type { WorkspaceEdit, WorkspaceModel } from "@/types/contracts";

export type EditKind = WorkspaceEdit["kind"];

export function draftKey(kind: EditKind, table: string, name: string): string {
  return `${kind}\u0000${table}\u0000${name}`;
}

export type Drafts = ReadonlyMap<string, WorkspaceEdit>;

export function withDraft(drafts: Drafts, edit: WorkspaceEdit): Map<string, WorkspaceEdit> {
  const next = new Map(drafts);
  next.set(draftKey(edit.kind, edit.table, edit.name), edit);
  return next;
}

export function withoutDraft(drafts: Drafts, key: string): Map<string, WorkspaceEdit> {
  const next = new Map(drafts);
  next.delete(key);
  return next;
}

/** `'Table Name'[Column]`, `Table[Column]`, or a bare `[Measure]`. */
const REFERENCE = /(?:'((?:[^']|'')+)'|([A-Za-z_][\w.]*))?\[([^\]]+)\]/g;

/** Text a reference cannot appear in: string literals and comments. */
function visible(expression: string): string {
  return expression
    .replace(/"(?:[^"]|"")*"/g, (match) => " ".repeat(match.length))
    .replace(/\/\/[^\n]*|--[^\n]*/g, (match) => " ".repeat(match.length))
    .replace(/\/\*[\s\S]*?\*\//g, (match) => " ".repeat(match.length));
}

export interface ReferenceProblem {
  readonly reference: string;
  readonly reason: string;
}

export function checkReferences(expression: string, model: WorkspaceModel): ReferenceProblem[] {
  const tables = new Map(
    (model.tables ?? []).map((table) => [
      table.name.toLowerCase(),
      new Set([
        ...(table.columns ?? []).map((column) => column.name.toLowerCase()),
        ...(table.measures ?? []).map((measure) => measure.name.toLowerCase()),
      ]),
    ]),
  );
  const measures = new Set(
    (model.tables ?? []).flatMap((table) => (table.measures ?? []).map((measure) => measure.name.toLowerCase())),
  );
  const columns = new Set(
    (model.tables ?? []).flatMap((table) => (table.columns ?? []).map((column) => column.name.toLowerCase())),
  );

  const problems: ReferenceProblem[] = [];
  const seen = new Set<string>();
  for (const match of visible(expression).matchAll(REFERENCE)) {
    const table = (match[1] ?? match[2])?.replace(/''/g, "'");
    const field = match[3] ?? "";
    const reference = match[0];
    if (!field || seen.has(reference)) continue;
    seen.add(reference);
    if (table) {
      const fields = tables.get(table.toLowerCase());
      if (!fields) {
        problems.push({ reference, reason: `There is no table called ${table} in this model.` });
      } else if (!fields.has(field.toLowerCase())) {
        problems.push({ reference, reason: `${table} has no column or measure called ${field}.` });
      }
    } else if (!measures.has(field.toLowerCase()) && !columns.has(field.toLowerCase())) {
      problems.push({ reference, reason: `No measure or column is called ${field}.` });
    }
  }
  return problems;
}

export interface ModelStats {
  readonly tables: number;
  readonly columns: number;
  readonly measures: number;
  readonly held: number;
}

export function statsOf(model: WorkspaceModel): ModelStats {
  const tables = model.tables ?? [];
  return {
    tables: tables.length,
    columns: tables.reduce((sum, table) => sum + (table.columns?.length ?? 0), 0),
    measures: tables.reduce((sum, table) => sum + (table.measures?.length ?? 0), 0),
    held: model.held?.length ?? 0,
  };
}
