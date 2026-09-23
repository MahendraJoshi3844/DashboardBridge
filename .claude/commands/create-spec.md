---
description: Scaffold a new Spec Document for a feature using the project's SDD template, on its own feature branch.
---

You are creating a new **Spec Document** for the feature described in: $ARGUMENTS

Follow the team's Spec-Driven Development standard:

1. **Branch first.** Ensure the working tree is clean, then create and switch to a
   new feature branch named `feature/<kebab-feature-name>`. Never write specs on
   `main`.
2. Create `docs/specs/SPEC-<kebab-feature-name>.md` using EXACTLY these sections
   (tech-agnostic — no stack details; those belong in a Technical Design Plan):
   - **1. Problem Statement** — why are we building this?
   - **2. Functional Requirements** — what exactly will it do?
   - **3. Input / Output Behaviour (Contract)** — what goes in, what comes out?
   - **4. Constraints** — performance, privacy, limits.
   - **5. Edge Cases & Error Handling** — table of case → handling.
   - **6. Acceptance Criteria** — checkboxes; how we know it's done.
   - **7. Open Questions** — anything unresolved.
3. Keep performance and "fidelity over guesswork" front of mind — both are core to
   this product.
4. After writing, **pause and ask the user to review** before any Technical Design
   or code (the SDD review step is not optional).
