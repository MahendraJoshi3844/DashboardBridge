"use client";

import { motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useMigration, useMigrationDispatch } from "@/lib/state/context";

import { DirectionCard } from "./DirectionCard";
import { ArrowRightIcon } from "./Icons";
import { StepRail } from "./StepRail";

const list = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.12 } },
};

/**
 * The landing screen's one decision.
 *
 * Choosing a direction is a real transition of the real machine
 * (`IDLE → SOURCE_SELECTED`), and the machine lives above the router, so the
 * choice made here is the same state the workspace uploads from. Everything
 * the user can see about where they are is read from `state.name`.
 *
 * Once the migration has moved past the choice, this card stops being a toggle
 * and becomes a way back into the run. Clearing a direction from the middle of
 * an upload is an illegal transition, and the machine would be right to refuse
 * it — so the card does not offer it.
 */
export function DirectionChoice() {
  const state = useMigration();
  const dispatch = useMigrationDispatch();
  const router = useRouter();

  const selected = state.name !== "IDLE";
  const canChoose = state.name === "IDLE";
  const canClear = state.name === "SOURCE_SELECTED";

  return (
    <section aria-labelledby="direction-heading" className="mt-10 sm:mt-14">
      <h2 id="direction-heading" className="eyebrow">
        Step 1 — choose a direction
      </h2>

      <motion.div
        variants={list}
        initial="hidden"
        animate="visible"
        className="mt-4 grid gap-5 lg:grid-cols-2"
      >
        <DirectionCard
          index={0}
          source="tableau"
          target="powerbi"
          blurb="Open a Tableau workbook and produce a Power BI project, with every transformation traceable to the rule that made it and every gap named."
          produces={[
            "PBIP project — TMDL model and PBIR report",
            "Calculated fields translated to DAX, or held for you",
            "Migration report: what converted, what did not, and why",
          ]}
          availability="available"
          selected={selected}
          onSelect={() => {
            if (canChoose) {
              dispatch({
                type: "DIRECTION_CHOSEN",
                direction: { source: "tableau", target: "powerbi" },
              });
              return;
            }
            if (canClear) {
              dispatch({ type: "DIRECTION_CLEARED" });
              return;
            }
            // Already past the choice: take the user back to the run rather
            // than unwinding it.
            router.push("/workspace");
          }}
        />

        <DirectionCard
          index={1}
          source="powerbi"
          target="tableau"
          blurb="Open a Power BI project and produce a Tableau workbook."
          produces={[]}
          availability="not_yet"
          reason="This direction is not symmetric with the other one, so we are not offering it yet. Reading Power BI and writing Tableau are both still to be built; there is no engine behind this card today, and a card that opened a screen would be claiming otherwise. See ADR-005."
          selected={false}
          onSelect={() => undefined}
        />
      </motion.div>

      <div className="mt-8">
        <StepRail state={state}>
          {selected ? (
            <>
              Direction set:{" "}
              <span className="data text-ink">Tableau → Power BI</span>. Nothing
              has left this machine yet.
            </>
          ) : (
            "Pick a direction to begin. Nothing leaves this machine until you choose a workbook."
          )}
        </StepRail>
      </div>

      {selected ? (
        <motion.p
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-5"
        >
          <Link className="btn" href="/workspace">
            Open a workbook
            <ArrowRightIcon className="h-4 w-4" />
          </Link>
        </motion.p>
      ) : null}
    </section>
  );
}
