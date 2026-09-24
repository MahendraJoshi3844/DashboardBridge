"use client";

/**
 * The Power BI workspace: the converted model, open for a person to finish.
 *
 * Measures (DAX) and table sources (Power Query) can be edited. Edits collect
 * as draft changes and are saved together as a new version of the project;
 * the download always serves the newest version. Calculations the converter
 * refused are listed as "held for you" with their Tableau source, so writing
 * the DAX for them happens here rather than in a text editor.
 *
 * What is not here is shown as unavailable with the reason - publishing, a
 * .pbit, server connections - rather than as a button that does nothing.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  getValidation,
  getWorkspace,
  getReportExplorer,
  getWorkspaceFile,
  publishSelection,
  reportUrl,
  saveWorkspaceVersion,
  startValidation,
  toApiError,
} from "@/lib/api/client";
import { saveBlob } from "@/lib/download";
import { useHealth } from "@/lib/hooks/useHealth";
import {
  checkReferences,
  draftKey,
  statsOf,
  withDraft,
  withoutDraft,
  type Drafts,
  type ReferenceProblem,
} from "@/lib/migrator/workspace";
import type { ApiError, ReportExplorer, Validation, WorkspaceCommit, WorkspaceEdit, WorkspaceModel } from "@/types/contracts";

import {
  IconChart,
  IconCheck,
  IconChevron,
  IconClose,
  IconCode,
  IconCopy,
  IconDatabase,
  IconDoc,
  IconDownload,
  IconGrid,
  IconHand,
  IconHistory,
  IconLayers,
  IconPlay,
  IconPlug,
  IconRefresh,
  IconReport,
  IconSearch,
  IconSigma,
  IconTable,
  IconUpload,
  IconWifi,
} from "./MgIcons";

type LeftMode = "tables" | "measures" | "held" | "mquery" | "report" | "files";
type CenterTab = "tree" | "validation" | "dax" | "mquery" | "report";

type Selection =
  | { readonly kind: "measure"; readonly table: string; readonly name: string }
  | { readonly kind: "held"; readonly table: string; readonly name: string; readonly item: string }
  | { readonly kind: "partition"; readonly table: string; readonly name: string }
  | { readonly kind: "file"; readonly path: string }
  | { readonly kind: "page"; readonly pageId: string }
  | { readonly kind: "visual"; readonly pageId: string; readonly visualId: string };

type ExpressionSelection = Extract<Selection, { kind: "measure" | "held" | "partition" }>;

function isExpression(selection: Selection | null): selection is ExpressionSelection {
  return selection !== null && (selection.kind === "measure" || selection.kind === "held" || selection.kind === "partition");
}

const UNAVAILABLE = {
  connections: "Server and warehouse connections are not configured on this deployment yet.",
  mcp: "No MCP tools are configured.",
  preview: "The converted model carries no data, so there is nothing to preview. Point the Power Query sources at your data in Power BI Desktop.",
  daxQuery: "Running DAX queries needs a live Power BI model; open the .pbip in Power BI Desktop for that.",
  pbit: "Template export is not built yet. Download the .pbip and save it as a .pbit from Power BI Desktop.",
  publish: "Publishing needs a Power BI service connection, which is not configured. Download the .pbip and publish from Power BI Desktop.",
};

/* --- small pieces ------------------------------------------------------------- */

function Menu({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div className="mg-menu" ref={ref} onKeyDown={(event) => event.key === "Escape" && setOpen(false)}>
      <button type="button" className="mg-menu__button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}
      </button>
      {open && (
        <div className="mg-menu__list" role="menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  );
}

function MenuItem({ onClick, disabled, title, children }: { readonly onClick?: () => void; readonly disabled?: boolean; readonly title?: string; readonly children: ReactNode }) {
  return (
    <button type="button" role="menuitem" className="mg-menu__item" onClick={onClick} disabled={disabled} title={title}>
      {children}
    </button>
  );
}

function Tool({ icon, label, onClick, disabled, title }: { readonly icon: ReactNode; readonly label: string; readonly onClick?: () => void; readonly disabled?: boolean; readonly title?: string }) {
  return (
    <button type="button" className="mg-tool" onClick={onClick} disabled={disabled} title={title ?? label} aria-label={title ? `${label} — ${title}` : label}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function ToolGroup({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <div className="mg-toolgroup" role="group" aria-label={label}>
      <div className="mg-toolgroup__items">{children}</div>
      <div className="mg-toolgroup__label">{label}</div>
    </div>
  );
}

function Editor({ value, onChange, readOnly, label }: { readonly value: string; readonly onChange?: (next: string) => void; readonly readOnly?: boolean; readonly label: string }) {
  const lines = Math.max(value.split("\n").length, 1);
  const gutter = useRef<HTMLDivElement>(null);
  return (
    <div className="mg-editor">
      <div className="mg-editor__gutter" ref={gutter} aria-hidden="true">
        {Array.from({ length: lines }, (_, index) => (
          <div key={index}>{index + 1}</div>
        ))}
      </div>
      <textarea
        aria-label={label}
        spellCheck={false}
        value={value}
        readOnly={readOnly}
        onChange={(event) => onChange?.(event.target.value)}
        onScroll={(event) => {
          if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop;
        }}
      />
    </div>
  );
}

/* --- the workspace -------------------------------------------------------------- */

export function PowerBiWorkspace({ projectId }: { readonly projectId: string }) {
  const health = useHealth();
  const [model, setModel] = useState<WorkspaceModel | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [left, setLeft] = useState<LeftMode>("measures");
  const [center, setCenter] = useState<CenterTab>("dax");
  const [search, setSearch] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [text, setText] = useState("");
  const [fileText, setFileText] = useState("");
  const [drafts, setDrafts] = useState<Drafts>(new Map());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [problems, setProblems] = useState<readonly ReferenceProblem[] | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [validating, setValidating] = useState(false);
  const [rightTab, setRightTab] = useState<"versions" | "changes">("versions");
  const [showRight, setShowRight] = useState(true);
  const [report, setReport] = useState<ReportExplorer | null>(null);
  // Nothing is chosen until a person chooses it: the .pbip carries no visual
  // that was not ticked.
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  const load = useCallback(async () => {
    try {
      setModel(await getWorkspace(projectId));
      const explorer = await getReportExplorer(projectId);
      setReport(explorer);
      // A reload can remove a visual; a tick on something gone is dropped
      // rather than sent and refused.
      const present = new Set(explorer.pages?.flatMap((page) => page.visuals?.map((visual) => visual.id) ?? []) ?? []);
      setChosen((current) => new Set([...current].filter((id) => present.has(id))));
      setError(null);
    } catch (cause) {
      setError(toApiError(cause));
    }
  }, [projectId]);

  useEffect(() => {
    void load();
    getValidation(projectId).then(setValidation).catch(() => undefined);
  }, [load, projectId]);

  const stats = model ? statsOf(model) : null;
  const sourceKindOf = (table: string, name: string) =>
    model?.tables?.find((candidate) => candidate.name === table)?.partitions?.find((partition) => partition.name === name)?.source_kind;
  const heldByItem = useMemo(() => new Map((model?.held ?? []).map((held) => [held.item, held])), [model]);

  /** What the selected object says now: its draft if there is one, else the model. */
  const currentExpression = useCallback(
    (target: Selection): string => {
      if (!model || !isExpression(target)) return "";
      const kind = target.kind === "partition" ? "partition" : "measure";
      const draft = drafts.get(draftKey(kind, target.table, target.name));
      if (draft) return draft.expression;
      const table = model.tables?.find((candidate) => candidate.name === target.table);
      if (target.kind === "partition") {
        return table?.partitions?.find((partition) => partition.name === target.name)?.expression ?? "";
      }
      return table?.measures?.find((measure) => measure.name === target.name)?.expression ?? "";
    },
    [model, drafts],
  );

  function select(next: Selection) {
    setSelection(next);
    setProblems(null);
    if (next.kind === "page" || next.kind === "visual") {
      setCenter("report");
      return;
    }
    if (next.kind === "file") {
      setCenter("tree");
      setFileText("Loading…");
      getWorkspaceFile(projectId, next.path)
        .then(setFileText)
        .catch((cause) => setFileText(toApiError(cause).message));
      return;
    }
    setCenter(next.kind === "partition" ? "mquery" : "dax");
    setText(currentExpression(next));
  }

  const editable = isExpression(selection);
  const original = isExpression(selection) ? currentExpression(selection) : "";
  const dirty = editable && text.trim() !== original.trim() && text.trim() !== "";

  function stage() {
    if (!isExpression(selection) || !text.trim()) return;
    const edit: WorkspaceEdit = {
      kind: selection.kind === "partition" ? "partition" : "measure",
      table: selection.table,
      name: selection.name,
      expression: text,
    };
    setDrafts(withDraft(drafts, edit));
    setRightTab("changes");
    setNotice(`Staged a change to ${selection.table}[${selection.name}]. Save a version to keep it.`);
  }

  async function save() {
    if (!model || drafts.size === 0) return;
    setSaving(true);
    try {
      const next = await saveWorkspaceVersion(projectId, {
        base_version: model.version,
        note,
        // Non-empty: the button is only offered while there are drafts.
        edits: [...drafts.values()] as WorkspaceCommit["edits"],
      });
      setModel(next);
      setDrafts(new Map());
      setNote("");
      setRightTab("versions");
      setNotice(`Saved v${next.version}. The download now serves this version.`);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setSaving(false);
    }
  }

  async function validate() {
    setValidating(true);
    setCenter("validation");
    try {
      await startValidation(projectId);
      setValidation(await getValidation(projectId));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setValidating(false);
    }
  }

  function referenceCheck() {
    if (!model) return;
    const targets = editable ? [text] : [...drafts.values()].filter((edit) => edit.kind === "measure").map((edit) => edit.expression);
    setProblems(targets.flatMap((expression) => checkReferences(expression, model)));
    setCenter("dax");
  }

  async function download() {
    try {
      const { blob, filename } = await publishSelection(projectId, [...chosen], `${model?.name ?? "project"}.pbip.zip`);
      saveBlob(blob, filename);
      setNotice(
        chosen.size === 0
          ? "Exported the .pbip with the semantic model and no visuals. Tick visuals in the Report Explorer to carry them."
          : `Exported the .pbip with ${chosen.size} of ${visualCount} visuals.`,
      );
    } catch (cause) {
      setError(toApiError(cause));
    }
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (dirty) stage();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const query = search.toLowerCase();
  const matches = (value: string) => value.toLowerCase().includes(query);

  /* --- report explorer ------------------------------------------------------ */

  const pages = report?.pages ?? [];
  const visualCount = pages.reduce((sum, page) => sum + (page.visuals?.length ?? 0), 0);

  function toggleVisual(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  }

  function togglePage(ids: readonly string[]) {
    const next = new Set(chosen);
    const all = ids.every((id) => next.has(id));
    for (const id of ids) {
      if (all) next.delete(id);
      else next.add(id);
    }
    setChosen(next);
  }

  function toggleExpanded(id: string) {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  }

  function reportPanel(): ReactNode {
    return (
      <>
        <div className="mg-panelhead" style={{ padding: "8px 12px" }}>
          <span>
            <strong style={{ fontSize: 12, letterSpacing: "0.05em", textTransform: "uppercase", display: "block" }}>Report Explorer</strong>
            <span className="mg-note">
              {pages.length} pages, {visualCount} visuals
            </span>
          </span>
          <button type="button" className="mg-iconbtn" aria-label="Reload the report" title="Reload" onClick={() => void load()}>
            <IconRefresh size={14} />
          </button>
        </div>
        <div className="mg-list" style={{ paddingTop: 6 }}>
          {report === null && <p className="mg-empty">Loading the report…</p>}
          {pages.map((page) => {
            const ids = (page.visuals ?? []).map((visual) => visual.id);
            const picked = ids.filter((id) => chosen.has(id)).length;
            const open = expanded.has(page.id);
            return (
              <div key={page.id} className="mg-page">
                <div className="mg-page__row" aria-current={selection?.kind === "page" && selection.pageId === page.id}>
                  <input
                    type="checkbox"
                    aria-label={`Include every visual on ${page.name}`}
                    disabled={ids.length === 0}
                    checked={ids.length > 0 && picked === ids.length}
                    ref={(box) => {
                      if (box) box.indeterminate = picked > 0 && picked < ids.length;
                    }}
                    onChange={() => togglePage(ids)}
                  />
                  <button
                    type="button"
                    className="mg-iconbtn mg-page__chevron"
                    aria-expanded={open}
                    aria-label={open ? `Collapse ${page.name}` : `Expand ${page.name}`}
                    onClick={() => toggleExpanded(page.id)}
                  >
                    <IconChevron size={13} style={{ transform: open ? "rotate(90deg)" : undefined }} />
                  </button>
                  <button type="button" className="mg-page__name" onClick={() => { select({ kind: "page", pageId: page.id }); toggleExpanded(page.id); }}>
                    <IconReport size={14} style={{ color: "var(--mg-accent)" }} />
                    <span>
                      <span className="mg-listitem__name">{page.name}</span>
                      <span className="mg-listitem__meta" style={{ display: "block" }}>
                        {page.width}×{page.height} · {page.visuals?.length ?? 0} visual{(page.visuals?.length ?? 0) === 1 ? "" : "s"}
                      </span>
                    </span>
                  </button>
                </div>
                {open && (
                  <div className="mg-page__visuals">
                    {(page.visuals ?? []).length === 0 && (
                      <p className="mg-note" style={{ margin: "4px 0 8px 30px" }}>
                        No visual was written for this worksheet{page.notes?.length ? `: ${page.notes[0]}` : "."}
                      </p>
                    )}
                    {(page.visuals ?? []).map((visual) => (
                      <div key={visual.id} className="mg-page__row mg-page__row--visual" aria-current={selection?.kind === "visual" && selection.visualId === visual.id}>
                        <input
                          type="checkbox"
                          aria-label={`Include ${visual.visual_type} from ${visual.source_name || page.name}`}
                          checked={chosen.has(visual.id)}
                          onChange={() => toggleVisual(visual.id)}
                        />
                        <button type="button" className="mg-page__name" onClick={() => select({ kind: "visual", pageId: page.id, visualId: visual.id })}>
                          <IconChart size={14} style={{ color: "var(--mg-powerbi)" }} />
                          <span>
                            <span className="mg-listitem__name">{visual.visual_type}</span>
                            <span className="mg-listitem__meta" style={{ display: "block" }}>
                              {visual.fields?.length ?? 0} field{(visual.fields?.length ?? 0) === 1 ? "" : "s"}
                              {visual.status === "partial" && <span style={{ color: "var(--mg-warn)" }}> · needs a look</span>}
                            </span>
                          </span>
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div className="mg-section" style={{ borderTop: "1px solid var(--mg-line)", borderBottom: 0 }}>
          <div className="mg-note">
            {chosen.size} of {visualCount} visuals selected. The .pbip carries only the selected visuals, with the full semantic model.
          </div>
          <button type="button" className="mg-btn mg-btn--primary mg-btn--block mg-btn--sm" style={{ marginTop: 8 }} onClick={() => void download()}>
            <IconDownload size={13} /> Export .pbip with {chosen.size} visual{chosen.size === 1 ? "" : "s"}
          </button>
        </div>
      </>
    );
  }

  function reportPane(): ReactNode {
    const page = selection && (selection.kind === "page" || selection.kind === "visual")
      ? pages.find((candidate) => candidate.id === selection.pageId)
      : undefined;
    if (!page) {
      return (
        <div className="mg-placeholder">
          <div>
            <IconReport size={28} />
            <p>Open the Report Explorer and select a page or visual to see what came across from Tableau.</p>
          </div>
        </div>
      );
    }
    const visuals = selection?.kind === "visual"
      ? (page.visuals ?? []).filter((visual) => visual.id === selection.visualId)
      : page.visuals ?? [];
    return (
      <div style={{ overflowY: "auto", padding: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <IconReport size={16} style={{ color: "var(--mg-accent)" }} />
          <strong>{page.name}</strong>
          <span className="mg-note">
            {page.width}×{page.height} · {page.visuals?.length ?? 0} visual{(page.visuals?.length ?? 0) === 1 ? "" : "s"}
          </span>
        </div>
        {visuals.length === 0 && (
          <p className="mg-note">
            No visual was written for this worksheet.{page.notes?.length ? ` ${page.notes.join(" ")}` : ""}
          </p>
        )}
        {visuals.map((visual) => (
          <div key={visual.id} className="mg-card" style={{ padding: 14, marginBottom: 12 }}>
            <div className="mg-map">
              <div>
                <div className="mg-stat__label">Tableau</div>
                <div className="mg-stat__value">
                  <IconLayers size={14} style={{ color: "var(--mg-tableau)" }} /> {visual.source_name || page.name}
                </div>
                <div className="mg-note">Mark: {visual.source_mark || "not recorded"}</div>
              </div>
              <span aria-hidden="true" style={{ color: "var(--mg-ink-3)" }}>→</span>
              <div>
                <div className="mg-stat__label">Power BI</div>
                <div className="mg-stat__value">
                  <IconChart size={14} style={{ color: "var(--mg-powerbi)" }} /> {visual.visual_type}
                </div>
                <div className="mg-note">
                  {visual.status === "partial" ? <span style={{ color: "var(--mg-warn)" }}>Converted with notes</span> : "Converted"}
                </div>
              </div>
              <label className="mg-btn mg-btn--sm" style={{ marginLeft: "auto" }}>
                <input type="checkbox" checked={chosen.has(visual.id)} onChange={() => toggleVisual(visual.id)} /> Include in .pbip
              </label>
            </div>
            <table className="mg-table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Well</th>
                  <th>Field</th>
                </tr>
              </thead>
              <tbody>
                {(visual.fields ?? []).map((field) => {
                  const [well, ...rest] = field.split(": ");
                  return (
                    <tr key={field}>
                      <td>{well}</td>
                      <td className="mg-mono" style={{ fontSize: 12 }}>{rest.join(": ")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {(visual.notes?.length ?? 0) > 0 && (
              <div className="mg-section" style={{ background: "var(--mg-warn-soft)", marginTop: 10, borderRadius: 8, borderBottom: 0 }}>
                {visual.notes?.map((note) => (
                  <div key={note} className="mg-note" style={{ color: "var(--mg-ink-2)" }}>{note}</div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  /* --- left panel ---------------------------------------------------------- */

  function leftPanel(): ReactNode {
    if (!model) return <p className="mg-empty">Loading the model…</p>;
    const tables = model.tables ?? [];
    if (left === "measures") {
      const count = tables.reduce((sum, table) => sum + (table.measures?.length ?? 0), 0);
      return (
        <>
          <PanelHead title="Measures" count={count} />
          <SearchBox value={search} onChange={setSearch} placeholder="Search measures…" />
          <div className="mg-list">
            {(model.held?.length ?? 0) > 0 && (
              <>
                <div className="mg-group">
                  <span>Held for you</span>
                  <span>{model.held?.length}</span>
                </div>
                {model.held?.filter((held) => matches(held.item)).map((held) => (
                  <ListItem
                    key={held.item}
                    icon={<IconHand size={14} style={{ color: "var(--mg-warn)" }} />}
                    name={held.name}
                    meta={held.table}
                    code={held.source || held.reason}
                    current={selection?.kind === "held" && selection.item === held.item}
                    staged={drafts.has(draftKey("measure", held.table, held.name))}
                    onClick={() => select({ kind: "held", table: held.table, name: held.name, item: held.item })}
                  />
                ))}
              </>
            )}
            {tables.map((table) => {
              const measures = (table.measures ?? []).filter((measure) => matches(measure.name));
              if (measures.length === 0) return null;
              return (
                <div key={table.name}>
                  <div className="mg-group">
                    <span>{table.name}</span>
                    <span>{measures.length}</span>
                  </div>
                  {measures.map((measure) => (
                    <ListItem
                      key={measure.name}
                      icon={<IconSigma size={14} />}
                      name={measure.name}
                      meta={table.name}
                      code={drafts.get(draftKey("measure", table.name, measure.name))?.expression ?? measure.expression}
                      current={selection?.kind === "measure" && selection.table === table.name && selection.name === measure.name}
                      staged={drafts.has(draftKey("measure", table.name, measure.name))}
                      onClick={() => select({ kind: "measure", table: table.name, name: measure.name })}
                    />
                  ))}
                </div>
              );
            })}
            {count === 0 && (model.held?.length ?? 0) === 0 && <p className="mg-empty">No measures in this model.</p>}
          </div>
        </>
      );
    }
    if (left === "held") {
      return (
        <>
          <PanelHead title="Held for you" count={model.held?.length ?? 0} />
          <p className="mg-note" style={{ padding: "0 12px" }}>
            The converter found no safe DAX for these, so it wrote nothing. Select one to write it yourself.
          </p>
          <div className="mg-list">
            {(model.held ?? []).map((held) => (
              <ListItem
                key={held.item}
                icon={<IconHand size={14} style={{ color: "var(--mg-warn)" }} />}
                name={held.name}
                meta={held.reason}
                code={held.source}
                current={selection?.kind === "held" && selection.item === held.item}
                staged={drafts.has(draftKey("measure", held.table, held.name))}
                onClick={() => select({ kind: "held", table: held.table, name: held.name, item: held.item })}
              />
            ))}
            {(model.held?.length ?? 0) === 0 && <p className="mg-empty">Nothing was held. Every calculation converted.</p>}
          </div>
        </>
      );
    }
    if (left === "mquery") {
      const partitions = tables.flatMap((table) => (table.partitions ?? []).map((partition) => ({ table: table.name, partition })));
      return (
        <>
          <PanelHead title="M-Query" count={partitions.length} />
          <SearchBox value={search} onChange={setSearch} placeholder="Search M-Query…" />
          <div className="mg-list">
            {partitions
              .filter(({ table }) => matches(table))
              .map(({ table, partition }) => {
                const expression = drafts.get(draftKey("partition", table, partition.name))?.expression ?? partition.expression;
                return (
                  <ListItem
                    key={`${table}/${partition.name}`}
                    icon={<IconCode size={14} />}
                    name={table}
                    meta={`${partition.source_kind === "calculated" ? "calculated table · DAX" : partition.mode || "import"} · ${expression.length} chars`}
                    current={selection?.kind === "partition" && selection.table === table && selection.name === partition.name}
                    staged={drafts.has(draftKey("partition", table, partition.name))}
                    onClick={() => select({ kind: "partition", table, name: partition.name })}
                  />
                );
              })}
          </div>
          <div className="mg-note" style={{ padding: "6px 12px", borderTop: "1px solid var(--mg-line)" }}>
            {partitions.length} sources
          </div>
        </>
      );
    }
    if (left === "report") return reportPanel();
    if (left === "files") {
      return (
        <>
          <PanelHead title="Project files" count={model.files?.length ?? 0} />
          <SearchBox value={search} onChange={setSearch} placeholder="Search files…" />
          <div className="mg-list">
            {(model.files ?? [])
              .filter((file) => matches(file.path))
              .map((file) => (
                <ListItem
                  key={file.path}
                  icon={<IconDoc size={14} />}
                  name={file.path.split("/").pop() ?? file.path}
                  meta={file.path}
                  current={selection?.kind === "file" && selection.path === file.path}
                  onClick={() => select({ kind: "file", path: file.path })}
                />
              ))}
          </div>
        </>
      );
    }
    return (
      <>
        <PanelHead title="Tables" count={tables.length} />
        <SearchBox value={search} onChange={setSearch} placeholder="Search tables…" />
        <div className="mg-list">
          {tables
            .filter((table) => matches(table.name))
            .map((table) => (
              <details key={table.name} open={tables.length <= 3}>
                <summary className="mg-listitem" style={{ listStyle: "none" }}>
                  <IconTable size={14} />
                  <span>
                    <span className="mg-listitem__name">{table.name}</span>
                    <span className="mg-listitem__meta" style={{ display: "block" }}>
                      {table.columns?.length ?? 0} columns · {table.measures?.length ?? 0} measures
                    </span>
                  </span>
                </summary>
                <div style={{ paddingLeft: 22 }}>
                  {(table.columns ?? []).map((column) => (
                    <div key={column.name} className="mg-listitem__meta" style={{ padding: "3px 8px" }}>
                      {column.name} <span style={{ opacity: 0.7 }}>· {column.data_type || "?"}</span>
                    </div>
                  ))}
                  {(table.measures ?? []).map((measure) => (
                    <button
                      key={measure.name}
                      type="button"
                      className="mg-listitem"
                      onClick={() => select({ kind: "measure", table: table.name, name: measure.name })}
                    >
                      <IconSigma size={12} /> <span className="mg-listitem__meta">{measure.name}</span>
                    </button>
                  ))}
                </div>
              </details>
            ))}
        </div>
      </>
    );
  }

  /* --- centre ------------------------------------------------------------------ */

  function editorPane(kind: "dax" | "mquery"): ReactNode {
    const target = isExpression(selection) ? selection : null;
    const matchesKind = target !== null && (kind === "mquery") === (target.kind === "partition");
    if (!matchesKind || target === null) {
      return (
        <div className="mg-placeholder">
          <div>
            <IconCode size={28} />
            <p>{kind === "mquery" ? "Select a table to view its M-Query." : "Select a measure to view and edit its DAX."}</p>
          </div>
        </div>
      );
    }
    const held = target.kind === "held" ? heldByItem.get(target.item) : undefined;
    return (
      <>
        <div className="mg-editorbar">
          <strong>
            {kind === "mquery" ? <IconCode size={14} /> : <IconSigma size={14} />} {target.table}[{target.name}]
            {kind === "mquery" && sourceKindOf(target.table, target.name) === "calculated" && (
              <span className="mg-pill mg-pill--soft" style={{ marginLeft: 8 }} title="A calculated table: its source is a DAX expression, not Power Query">
                calculated table · DAX
              </span>
            )}
            {drafts.has(draftKey(kind === "mquery" ? "partition" : "measure", target.table, target.name)) && (
              <span className="mg-pill mg-pill--warn" style={{ marginLeft: 8 }}>staged</span>
            )}
          </strong>
          <span style={{ display: "flex", gap: 6 }}>
            <button type="button" className="mg-btn mg-btn--sm" onClick={() => void navigator.clipboard?.writeText(text)} title="Copy">
              <IconCopy size={13} /> Copy
            </button>
            {kind === "dax" && (
              <button type="button" className="mg-btn mg-btn--sm" onClick={referenceCheck} disabled={!text.trim()}>
                <IconCheck size={13} /> Check references
              </button>
            )}
            <button type="button" className="mg-btn mg-btn--sm" onClick={() => setText(original)} disabled={!dirty}>
              Revert
            </button>
            <button type="button" className="mg-btn mg-btn--primary mg-btn--sm" onClick={stage} disabled={!dirty} title="Ctrl+S">
              Stage change
            </button>
          </span>
        </div>
        {held && (
          <div className="mg-section" style={{ background: "var(--mg-warn-soft)" }}>
            <div className="mg-note" style={{ color: "var(--mg-ink-2)" }}>
              <strong>Held for you:</strong> {held.reason}
            </div>
            {held.source && (
              <pre className="mg-mono" style={{ margin: "6px 0 0", fontSize: 12, whiteSpace: "pre-wrap" }}>
                Tableau: {held.source}
              </pre>
            )}
            <div className="mg-note" style={{ marginTop: 4 }}>Write the DAX below. It is saved as your measure, not as a conversion.</div>
          </div>
        )}
        {problems !== null && kind === "dax" && (
          <div className="mg-section" role="status">
            {problems.length === 0 ? (
              <span className="mg-pill mg-pill--good">Every reference names something in this model</span>
            ) : (
              problems.map((problem) => (
                <div key={problem.reference} className="mg-note" style={{ color: "var(--mg-bad)" }}>
                  <span className="mg-mono">{problem.reference}</span> — {problem.reason}
                </div>
              ))
            )}
            <div className="mg-note">A reference check only: it does not parse or run the DAX.</div>
          </div>
        )}
        <Editor label={kind === "mquery" ? "Power Query M" : "DAX expression"} value={text} onChange={(next) => { setText(next); setProblems(null); }} />
      </>
    );
  }

  function validationPane(): ReactNode {
    if (validating) return <div className="mg-placeholder">Running the checks…</div>;
    if (!validation) {
      return (
        <div className="mg-placeholder">
          <div>
            <p>No validation has run for this project yet.</p>
            <button type="button" className="mg-btn mg-btn--primary" onClick={() => void validate()}>
              <IconPlay size={13} /> Validate
            </button>
          </div>
        </div>
      );
    }
    const verdict = validation.verdict ?? "unverified";
    return (
      <div style={{ overflowY: "auto", padding: 16 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
          <span className={`mg-pill ${verdict === "verified" ? "mg-pill--good" : verdict === "failed" ? "mg-pill--bad" : "mg-pill--warn"}`}>
            {verdict.replace("_", " ")}
          </span>
          {typeof validation.score === "number" && <span>{Math.round(validation.score * 100)}% of applicable checks passed</span>}
          <span className="mg-note" style={{ marginLeft: "auto" }}>Checks the newest version against the source workbook</span>
        </div>
        <table className="mg-table">
          <thead>
            <tr>
              <th>Check</th>
              <th>Result</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {(validation.rules ?? []).map((rule, index) => (
              <tr key={`${rule.rule_id}-${index}`}>
                <td className="mg-mono" style={{ fontSize: 12 }}>{rule.rule_id}</td>
                <td>
                  <span className={`mg-pill ${rule.status === "PASS" ? "mg-pill--good" : rule.status === "FAIL" ? "mg-pill--bad" : rule.status === "WARNING" ? "mg-pill--warn" : "mg-pill--soft"}`}>
                    {rule.status}
                  </span>
                </td>
                <td className="mg-note">{rule.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function treePane(): ReactNode {
    if (selection?.kind === "file") {
      return (
        <>
          <div className="mg-editorbar">
            <span className="mg-mono" style={{ fontSize: 12 }}>{selection.path}</span>
            <span className="mg-note">Read only</span>
          </div>
          <Editor label={selection.path} value={fileText} readOnly />
        </>
      );
    }
    if (!model) return <div className="mg-placeholder">Loading…</div>;
    return (
      <div style={{ overflowY: "auto", padding: 16 }}>
        <div className="mg-grid-3" style={{ marginBottom: 14 }}>
          {model.tables?.map((table) => (
            <div key={table.name} className="mg-card" style={{ padding: 12 }}>
              <div style={{ fontWeight: 600, display: "flex", gap: 6, alignItems: "center" }}>
                <IconTable size={14} /> {table.name}
              </div>
              <div className="mg-note">
                {table.columns?.length ?? 0} columns · {table.measures?.length ?? 0} measures · {table.partitions?.[0]?.mode || "import"}
              </div>
              <ul style={{ margin: "8px 0 0", paddingLeft: 16, fontSize: 12.5 }}>
                {(table.columns ?? []).slice(0, 8).map((column) => (
                  <li key={column.name}>
                    {column.name} <span className="mg-note">{column.data_type}</span>
                  </li>
                ))}
                {(table.columns?.length ?? 0) > 8 && <li className="mg-note">and {(table.columns?.length ?? 0) - 8} more</li>}
              </ul>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const aiAvailable = health.phase === "ready" && health.health.ai_available === true;
  const connected = health.phase === "ready";
  const railButton = (mode: LeftMode, label: string, icon: ReactNode) => (
    <button type="button" className="mg-iconbtn" aria-pressed={left === mode} aria-label={label} title={label} onClick={() => { setLeft(mode); setSearch(""); }}>
      {icon}
    </button>
  );

  return (
    <div className="mg mg-ide">
      <div className="mg-ide__menu">
        <Link href="/jobs" className="mg-iconbtn" aria-label="All migration jobs" title="All migration jobs">
          <IconGrid />
        </Link>
        <Link href="/migrate" className="mg-brand">DashboardBridge</Link>
        <span className="mg-note" style={{ fontWeight: 700, letterSpacing: "0.05em" }}>POWER BI</span>
        <nav style={{ display: "flex", gap: 2 }} aria-label="Menu">
          <Menu label="File">
            <MenuItem onClick={() => void download()}>Export .pbip (selected visuals)</MenuItem>
            <MenuItem onClick={() => window.open(reportUrl(projectId), "_blank", "noreferrer")}>Migration report</MenuItem>
            <MenuItem disabled title={UNAVAILABLE.pbit}>Export .pbit</MenuItem>
            <MenuItem onClick={() => (window.location.href = `/jobs/${projectId}`)}>Back to the job</MenuItem>
          </Menu>
          <Menu label="Edit">
            <MenuItem onClick={stage} disabled={!dirty}>Stage change (Ctrl+S)</MenuItem>
            <MenuItem onClick={() => setDrafts(new Map())} disabled={drafts.size === 0}>Discard all draft changes</MenuItem>
          </Menu>
          <Menu label="View">
            <MenuItem onClick={() => setShowRight(!showRight)}>{showRight ? "Hide" : "Show"} versions panel</MenuItem>
            <MenuItem onClick={() => setLeft("held")}>Held for you</MenuItem>
            <MenuItem onClick={() => setLeft("files")}>Project files</MenuItem>
          </Menu>
          <Menu label="Run">
            <MenuItem onClick={() => void validate()}>Validate project</MenuItem>
            <MenuItem onClick={referenceCheck}>Check DAX references</MenuItem>
          </Menu>
          <Menu label="Help">
            <MenuItem onClick={() => setNotice("Select a measure or table on the left, edit it, stage the change (Ctrl+S), then save a version on the right. The download always serves the newest version.")}>
              How editing works
            </MenuItem>
          </Menu>
        </nav>
        <div className="mg-ide__title">{model?.name ?? "…"}</div>
        {stats && (
          <span className="mg-note" style={{ display: "flex", gap: 10 }} aria-label="Model size">
            <span title="Tables"><IconTable size={12} /> {stats.tables}T</span>
            <span title="Columns">{stats.columns}C</span>
            <span title="Measures"><IconSigma size={12} /> {stats.measures}M</span>
            <span title="Held for you" style={{ color: stats.held ? "var(--mg-warn)" : undefined }}><IconHand size={12} /> {stats.held}H</span>
          </span>
        )}
        <button type="button" className="mg-iconbtn" onClick={() => void load()} aria-label="Reload the model" title="Reload">
          <IconRefresh />
        </button>
        <span className={`mg-pill ${connected ? "mg-pill--good" : "mg-pill--bad"}`}>
          <IconWifi size={13} /> {connected ? "Connected" : health.phase === "checking" ? "Checking" : "Offline"}
        </span>
      </div>

      <div className="mg-toolbar" role="toolbar" aria-label="Workspace tools">
        <ToolGroup label="Connections">
          <Tool icon={<IconLayers />} label="Power BI" disabled title={UNAVAILABLE.connections} />
          <Tool icon={<IconLayers />} label="Tableau" disabled title={UNAVAILABLE.connections} />
          <Tool icon={<IconDatabase />} label="Warehouse" disabled title={UNAVAILABLE.connections} />
        </ToolGroup>
        <ToolGroup label="Tools">
          <Tool icon={<IconPlug />} label="MCP" disabled title={UNAVAILABLE.mcp} />
        </ToolGroup>
        <ToolGroup label="Data">
          <Tool icon={<IconTable />} label="Preview" disabled title={UNAVAILABLE.preview} />
          <Tool icon={<IconRefresh />} label="Refresh" onClick={() => void load()} />
          <Tool icon={<IconPlay />} label="DAX Query" disabled title={UNAVAILABLE.daxQuery} />
        </ToolGroup>
        <ToolGroup label="Model">
          <Tool icon={<IconCheck />} label="Check DAX" onClick={referenceCheck} title="Check that every reference names something in this model" />
          <Tool icon={<IconCode />} label="Validate" onClick={() => void validate()} />
        </ToolGroup>
        <ToolGroup label="Publish">
          <Tool icon={<IconDownload />} label=".pbit" disabled title={UNAVAILABLE.pbit} />
          <Tool
            icon={<IconDownload />}
            label=".pbip"
            onClick={() => void download()}
            title={`Export the project with ${chosen.size} of ${visualCount} visuals selected in the Report Explorer`}
          />
          <Tool icon={<IconUpload />} label="Publish" disabled title={UNAVAILABLE.publish} />
        </ToolGroup>
      </div>

      <div className="mg-ide__body" style={showRight ? undefined : { gridTemplateColumns: "44px 290px 1fr" }}>
        <nav className="mg-ide__rail" aria-label="Panels">
          {railButton("tables", "Tables", <IconTable />)}
          {railButton("measures", "Measures", <IconSigma />)}
          {railButton("held", "Held for you", <IconHand />)}
          {railButton("mquery", "M-Query", <IconCode />)}
          {railButton("report", "Report Explorer", <IconReport />)}
          {railButton("files", "Project files", <IconDoc />)}
        </nav>

        <aside className="mg-ide__left" aria-label="Model">
          {leftPanel()}
        </aside>

        <section className="mg-ide__center" aria-label="Editor">
          <div className="mg-tabs mg-tabs--line" role="tablist" style={{ padding: "0 14px" }}>
            {aiAvailable && (
              <button type="button" role="tab" className="mg-tab" aria-selected={false} disabled title="The assistant proposes; a person applies. Coming to this screen.">
                AI Chat
              </button>
            )}
            {(
              [
                ["tree", "Model Tree"],
                ["validation", "Data Validation"],
                ["dax", "DAX Studio"],
                ["mquery", "M-Query"],
                ["report", "Report"],
              ] as const
            ).map(([id, label]) => (
              <button key={id} type="button" role="tab" className="mg-tab" aria-selected={center === id} onClick={() => setCenter(id)}>
                {label}
              </button>
            ))}
          </div>
          {(error || notice) && (
            <div className={error ? "mg-error" : "mg-section"} role={error ? "alert" : "status"} style={{ margin: 10, display: "flex", justifyContent: "space-between", gap: 8 }}>
              <span>{error ? error.message : notice}</span>
              <button type="button" className="mg-iconbtn" aria-label="Dismiss" onClick={() => { setError(null); setNotice(null); }}>
                <IconClose size={14} />
              </button>
            </div>
          )}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
            {center === "dax" && editorPane("dax")}
            {center === "mquery" && editorPane("mquery")}
            {center === "validation" && validationPane()}
            {center === "tree" && treePane()}
            {center === "report" && reportPane()}
          </div>
        </section>

        {showRight && (
          <aside className="mg-ide__right" aria-label="Versions and changes">
            <div className="mg-tabs mg-tabs--line" role="tablist" style={{ padding: "0 12px" }}>
              <button type="button" role="tab" className="mg-tab" aria-selected={rightTab === "versions"} onClick={() => setRightTab("versions")}>
                Versions
              </button>
              <button type="button" role="tab" className="mg-tab" aria-selected={rightTab === "changes"} onClick={() => setRightTab("changes")}>
                Changes {drafts.size > 0 && <span className="mg-pill mg-pill--warn">{drafts.size}</span>}
              </button>
              <button type="button" className="mg-iconbtn" style={{ marginLeft: "auto" }} aria-label="Hide panel" onClick={() => setShowRight(false)}>
                <IconClose size={14} />
              </button>
            </div>

            <div className="mg-section">
              <div className="mg-section__head">
                <span><IconChevron size={12} /> Draft Changes</span>
                {drafts.size > 0 && (
                  <button type="button" className="mg-link" onClick={() => setDrafts(new Map())}>Discard all</button>
                )}
              </div>
              {drafts.size === 0 ? (
                <p className="mg-note" style={{ textAlign: "center" }}>
                  <IconCheck size={16} />
                  <br />
                  No uncommitted changes
                </p>
              ) : (
                <>
                  {[...drafts.entries()].map(([key, edit]) => (
                    <div key={key} className="mg-version">
                      <span>
                        {edit.kind === "partition" ? <IconCode size={12} /> : <IconSigma size={12} />} {edit.table}[{edit.name}]
                      </span>
                      <button type="button" className="mg-iconbtn" aria-label={`Drop the change to ${edit.name}`} onClick={() => setDrafts(withoutDraft(drafts, key))}>
                        <IconClose size={12} />
                      </button>
                    </div>
                  ))}
                  <input className="mg-input" placeholder="What changed? (optional)" value={note} onChange={(event) => setNote(event.target.value)} aria-label="Version note" style={{ marginTop: 8 }} />
                  <button type="button" className="mg-btn mg-btn--primary mg-btn--block" style={{ marginTop: 8 }} disabled={saving} onClick={() => void save()}>
                    {saving ? "Saving…" : `Save as v${(model?.version ?? 0) + 1}`}
                  </button>
                </>
              )}
            </div>

            {rightTab === "versions" && (
              <div className="mg-section">
                <div className="mg-section__head">
                  <span><IconHistory size={13} /> Version History ({model?.versions?.length ?? 0})</span>
                  <button type="button" className="mg-iconbtn" aria-label="Reload versions" onClick={() => void load()}>
                    <IconRefresh size={13} />
                  </button>
                </div>
                {[...(model?.versions ?? [])].reverse().map((version) => (
                  <div key={version.artifact_id} className="mg-version">
                    <span>
                      <strong>v{version.version}</strong>{" "}
                      {version.version === model?.version && <span className="mg-pill mg-pill--soft">Active</span>}{" "}
                      <span className="mg-note">{version.note}</span>
                    </span>
                    <span className="mg-note">{new Date(version.created_at).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            )}
            {rightTab === "changes" && drafts.size > 0 && (
              <div className="mg-section">
                <p className="mg-note">
                  Saving writes these into the project&apos;s TMDL as v{(model?.version ?? 0) + 1}. The conversion report is unchanged: it records what the converter did, and these are your edits.
                </p>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

function PanelHead({ title, count }: { readonly title: string; readonly count: number }) {
  return (
    <div className="mg-panelhead" style={{ padding: "8px 12px" }}>
      <strong style={{ fontSize: 12, letterSpacing: "0.05em", textTransform: "uppercase" }}>{title}</strong>
      <span className="mg-note">{count}</span>
    </div>
  );
}

function SearchBox({ value, onChange, placeholder }: { readonly value: string; readonly onChange: (next: string) => void; readonly placeholder: string }) {
  return (
    <div className="mg-search mg-listsearch">
      <IconSearch size={13} />
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} aria-label={placeholder} />
    </div>
  );
}

function ListItem({
  icon,
  name,
  meta,
  code,
  current,
  staged,
  onClick,
}: {
  readonly icon: ReactNode;
  readonly name: string;
  readonly meta?: string;
  readonly code?: string;
  readonly current?: boolean;
  readonly staged?: boolean;
  readonly onClick: () => void;
}) {
  return (
    <button type="button" className="mg-listitem" aria-current={current} onClick={onClick}>
      <span style={{ marginTop: 2 }}>{icon}</span>
      <span style={{ minWidth: 0 }}>
        <span className="mg-listitem__name">
          {name} {staged && <span className="mg-pill mg-pill--warn" style={{ padding: "0 6px" }}>staged</span>}
        </span>
        {meta && <span className="mg-listitem__meta" style={{ display: "block" }}>{meta}</span>}
        {code && <span className="mg-listitem__code" style={{ display: "block" }}>{code}</span>}
      </span>
    </button>
  );
}
