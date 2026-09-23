"use client";

import { motion } from "motion/react";

const rise = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0 },
};

/**
 * The landing statement.
 *
 * ## Why it leads with a limitation
 *
 * "Transform Your BI Dashboards" is a sentence any migration tool could print,
 * and every one of them does. What is actually different here is the second
 * half of the job: this product tells you what it could *not* carry across, and
 * why, in the source tool's own words. So the headline says that, because a
 * headline should be the claim the product can defend rather than the one the
 * category expects.
 *
 * ## Why there is no eyebrow above it
 *
 * There was one - "Explainable BI migration", tracked-out, upper-cased,
 * monospace. It repeated the headline in smaller letters. A label earns its
 * place by carrying something the heading does not; that one carried the
 * category name, which nobody reading this page needs told.
 *
 * ## The three outcomes, and why there are no numbers beside them
 *
 * They are the product's real vocabulary - the same three words the analysis,
 * the report and the flags use - so seeing them here first is what makes the
 * results screen legible later. There is no count against them, because no
 * workbook has been opened yet and a specimen number on a landing page is the
 * exact failure this product exists to avoid.
 */
export function Hero() {
  return (
    <motion.div
      initial="hidden"
      animate="visible"
      transition={{ staggerChildren: 0.07 }}
      className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-16"
    >
      <div>
        <motion.h1
          variants={rise}
          className="max-w-[20ch] text-balance text-4xl font-semibold leading-[1.06] tracking-tight text-ink sm:text-5xl lg:text-[3.4rem]"
        >
          Most of a dashboard crosses. This tells you about the rest.
        </motion.h1>

        <motion.p
          variants={rise}
          className="mt-6 max-w-[62ch] text-base leading-relaxed text-ink-muted sm:text-lg"
        >
          Open a workbook and see every table, field and calculation it holds,
          what will survive the move, and what a person still has to write. The
          conversion is deterministic: the same workbook produces the same
          project, and nothing is guessed to make a number look better.
        </motion.p>
      </div>

      {/*
        The legend is the page's one piece of structure that is not prose, and
        it is set as a definition list because that is what it is - three terms
        the rest of the product uses, defined once, in the order they appear on
        every later screen.
      */}
      <motion.dl
        variants={rise}
        className="grid w-full gap-3 border-l border-line pl-5 lg:w-72"
      >
        <div>
          <dt className="text-sm font-medium text-status-good">
            Crossed by rule
          </dt>
          <dd className="mt-0.5 text-sm leading-snug text-ink-faint">
            A deterministic mapping produced it, and the rule is named.
          </dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-held">Held for you</dt>
          <dd className="mt-0.5 text-sm leading-snug text-ink-faint">
            No safe equivalent. You get the expression and the reason.
          </dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-status-serious">
            Will not cross
          </dt>
          <dd className="mt-0.5 text-sm leading-snug text-ink-faint">
            Power BI has no counterpart. Rebuilding it is a design decision.
          </dd>
        </div>
      </motion.dl>
    </motion.div>
  );
}
