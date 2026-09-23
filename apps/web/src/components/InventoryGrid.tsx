"use client";

import { motion } from "motion/react";

import type { Inventory } from "@/types/contracts";

import { AnimatedNumber } from "./AnimatedNumber";

/**
 * What is actually in the workbook, grouped as the user thinks about it rather
 * than as the parser found it (01-product-spec.md, "Inventory").
 *
 * Every number here was counted by the engine from the canonical model. None is
 * estimated, none is rounded, and a count of zero is shown as zero rather than
 * hidden — an absent card would read as "not looked at", which is a different
 * claim from "none present".
 */
interface CountSpec {
  readonly key: keyof Inventory;
  readonly label: string;
  /** What the number means, in one line, in the user's terms. */
  readonly meaning: string;
  readonly group: "Data" | "Semantic" | "Visualisation";
}

const COUNTS: readonly CountSpec[] = [
  {
    key: "datasources",
    label: "Data sources",
    meaning: "Connections the workbook reads from",
    group: "Data",
  },
  {
    key: "tables",
    label: "Tables",
    meaning: "Physical and federated objects behind them",
    group: "Data",
  },
  {
    key: "columns",
    label: "Columns",
    meaning: "Fields available to the model",
    group: "Data",
  },
  {
    key: "relationships",
    label: "Relationships",
    meaning: "Joins that must survive the move",
    group: "Data",
  },
  {
    key: "calculations",
    label: "Calculated fields",
    meaning: "Expressions needing DAX, or a person",
    group: "Semantic",
  },
  {
    key: "parameters",
    label: "Parameters",
    meaning: "Inputs a reader can change",
    group: "Semantic",
  },
  {
    key: "visuals",
    label: "Visuals",
    meaning: "Worksheets to rebuild as Power BI visuals",
    group: "Visualisation",
  },
  {
    key: "dashboards",
    label: "Dashboards",
    meaning: "Pages the visuals are laid out on",
    group: "Visualisation",
  },
];

const GROUP_TONE: Record<CountSpec["group"], string> = {
  Data: "text-source",
  Semantic: "text-held",
  Visualisation: "text-target",
};

const card = {
  hidden: { opacity: 0, y: 12, scale: 0.99 },
  visible: { opacity: 1, y: 0, scale: 1 },
};

const list = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.05 } },
};

export function InventoryGrid({ inventory }: { readonly inventory: Inventory }) {
  return (
    <section aria-labelledby="inventory-heading">
      <h2 id="inventory-heading" className="eyebrow">
        Inventory — what is in this workbook
      </h2>

      <motion.div
        variants={list}
        initial="hidden"
        animate="visible"
        className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
      >
        {COUNTS.map((spec) => (
          <motion.article
            key={spec.key}
            variants={card}
            className="panel flex flex-col justify-between p-4"
          >
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-xs font-medium text-ink-muted">{spec.label}</h3>
              <span
                className={`tag text-xs ${GROUP_TONE[spec.group]}`}
              >
                {spec.group}
              </span>
            </div>
            <p className="mt-3">
              <AnimatedNumber
                value={inventory[spec.key] ?? 0}
                className="numeral text-3xl font-semibold tracking-tight text-ink"
              />
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-faint">
              {spec.meaning}
            </p>
          </motion.article>
        ))}
      </motion.div>
    </section>
  );
}
