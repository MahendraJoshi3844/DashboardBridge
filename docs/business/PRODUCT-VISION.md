# Product Vision & Pitch — t2pbi

> A one-page-ish narrative for customer pitches and investor conversations.
> Pairs with the Spec (`docs/specs/`) and Technical Design (`docs/design/`).

## The one-liner
**t2pbi turns weeks of manual Tableau-to-Power-BI rebuilding into a 30-second,
fully-offline conversion — and tells you exactly what's left to finish.**

## The problem (why now)
Enterprises are consolidating BI onto Microsoft Fabric / Power BI to cut Tableau
licensing and unify governance. But migrating existing Tableau content is brutal:
analysts open each workbook and **rebuild it by hand**, rewriting every calculation
from Tableau's language into **DAX**. A mid-size workbook takes **days to weeks**, and
quality depends on the analyst. Consultancies bill heavily for this rote work.

## The solution
A desktop app + engine that reads a `.twb`/`.twbx` and emits a **ready-to-open Power
BI project (PBIP)**, recovering the data model, fields, supported calculations (as
DAX), and the common visuals automatically — then produces a **Migration Report**
itemizing what converted cleanly and what needs a human. Automate the mechanical 80%;
make the last 20% a checklist instead of a from-scratch rebuild.

## Why we win
- **Speed:** seconds, not weeks, per workbook.
- **Trust:** we never emit guessed DAX/visuals — uncertain items are flagged, not
  faked. The report is the product as much as the conversion.
- **Privacy:** 100% offline desktop. Sensitive workbooks never leave the customer's
  machine — a hard requirement for banks, healthcare, government.
- **Open output:** we emit Microsoft's text-based PBIP/TMDL — diffable, git-friendly,
  future-proof — not a brittle reverse-engineered binary.

## Who buys
1. **BI consultancies / SIs** doing migration engagements — we make their billable
   work faster and more predictable (land-and-expand).
2. **Enterprise BI teams** with large Tableau estates and a Power BI mandate.
3. **Individual analysts** who inherited Tableau content.

## How we make money (hypotheses to validate)
- **Per-seat desktop license** for consultancies/analysts (annual).
- **Per-workbook / volume pack** pricing for one-off large migrations.
- Later: **team/SaaS tier** (the same engine behind a web app) for collaboration,
  audit trails, and batch migration of an estate.

## Go-to-market (early)
- Free/beta for **3–5 pilot customers** (target: consultancies) to gather real
  workbooks and proof-of-value metrics (hours saved, % auto-converted).
- Publish before/after case studies: "X-sheet workbook, Y% auto-converted, Z hours
  saved."

## Proof metrics we will track
- % of model/fields/calcs/visuals auto-converted per workbook.
- Hours saved vs manual baseline.
- Conversion time (must stay < 30s for typical workbooks).
- Report accuracy: flagged items that truly needed manual work (no silent loss).

## Roadmap (product)
- **v1:** data model + fields + supported DAX + basic visuals + report + desktop app
  (PBIP output).
- **v2:** `.pbix` packaging; wider DAX coverage; more visual types.
- **v3:** dashboard layout fidelity; parameters/actions; LOD coverage.
- **v4:** SaaS/team tier (batch estate migration) reusing the same engine.

## Honest limitations (say these in the pitch — they build trust)
- v1 does not reproduce pixel-perfect dashboard layouts or every advanced Tableau
  calculation. It gets you most of the way and **tells you precisely what remains**.
- Output certified against a specific Power BI Desktop version.
