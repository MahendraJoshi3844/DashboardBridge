# The Stage — demo-first UI for t2pbi

**Status:** approved 2026-08-29 · **Branch:** `feature/stage-ui`

## Why

The desktop app is the pitch surface for BI consultancies. The primary user is
**the buyer watching a ten-minute demo**, not the engineer doing triage. The demo
arc is **transformation → scale → proof**: watch a workbook convert, land on the
throughput, drill into any single item for evidence.

Two facts force the design:

1. **Conversion takes 0.45s.** Too fast to be a spectacle. Padding a progress bar
   is disqualifying for a product whose pitch is trustworthiness.
2. **Superstore yields 89 flags, 51 MANUAL.** The current Report page shows only
   calculated fields, so most of what the engine now reports has nowhere to go.

## Thesis: two languages, held apart

The existing `theme.py` signature is a Tableau-blue → Power BI-amber gradient.
It is cut. A gradient blends the two languages, and blending misrepresents the
product: t2pbi translates discretely, and where it cannot, it stops and says so.

The replacement is **two inks that never mix**, and a seam where translation
happens.

## Signature: The Seam

A single vertical hairline down the stage. Streamed items enter left in `source`
ink, cross, and land right in `target` ink. Items that cannot cross **stop at the
seam and stack** in `held`.

This renders the whole product as one image, and serves the full arc: items cross
(transformation), the piles grow (scale), clicking a held item shows why it
stopped (proof). It puts the 51 held items center-stage rather than in a footer —
the deliberate risk of this design.

## Honest pacing

The engine emits a real event per item — 54 columns, 21 calcs, 21 worksheets, 6
dashboards. Streaming genuine work at a readable rate takes 2–4s without a single
frame of fiction, and the volume itself sells the throughput claim. The true
elapsed time (0.45s) is displayed as the headline. Replay re-plays the *recorded*
timeline, so it is honest by construction: the same events, at a chosen clock
position.

## Architecture

### Event spine (`engines/t2pbi/events.py`)

- **`ConversionEvent`** — frozen record: `seq`, `elapsed_ms`, `stage`, `kind`
  (table|column|calc|visual|parameter|relationship), `name`, `outcome`
  (crossed|held), `detail`, `ref`.
- **`EventSink`** — owned by `pipeline.py`, passed *down* into stages. Stages
  emit; they never read the sink and never see each other, preserving the rule
  that only `pipeline.py` knows stage order. A null sink is the default so every
  existing caller and test keeps working.
- **`Timeline`** — the recorded run: ordered events plus real duration. The UI
  binds to this one object. Live and replay are the same renderer at different
  clock positions, not two code paths.

Events carry an IR `ref`, so clicking a streamed row opens the side-by-side proof
for that exact item — the drill-down comes nearly free.

### UI substrate

Qt is dropped entirely. PySide6 weighs 665 MB installed; the shell becomes
**pywebview** over the **WebView2** runtime that already ships with Windows 10/11,
with the UI built as static assets by Vite.

| layer | before | after |
|---|---|---|
| shell | PySide6 | pywebview → WebView2 |
| UI | QSS + QPainter + QML | Vite + React + TypeScript, built and bundled |
| bridge | Qt signals | pywebview JS API |
| engine | pure Python | unchanged |

The engine is untouched: `pipeline.run` and `worker.run_job` were built Qt-free
from the start, so this replaces only the shell. Assets are bundled into the
executable — no dev server, no CDN, no ports opened, so the offline guarantee
holds.

**Risk:** WebView2 must be present. It is preinstalled on Windows 11 and normally
present on Windows 10 via Edge. If missing, the app states what is needed rather
than failing blank; a fixed-version WebView2 can be bundled for locked-down
enterprises.

### Local AI assist

Held items are exactly what a model can help with, so t2pbi drafts DAX for them —
**entirely on the user's machine**, via a local runtime (Ollama / llama.cpp).
Suggestions are always *proposals*: shown next to the Tableau source with the
reason the item was held, and applied only when the user accepts.

This strengthens rather than weakens the trust contract, and the pitch says so:
*AI that drafts the hard DAX and never sees your client's data.* If no local
runtime is present the feature is simply absent — never a silent fallback to a
cloud call.

A drafted measure is marked as AI-suggested in the model and the report, so an
accepted suggestion is never mistaken for a deterministic conversion.

## Tokens

| token | hex | role |
|---|---|---|
| `void` | `#0A0E14` | stage ground — neutral deep ink |
| `plate` | `#131924` | raised surfaces |
| `rule` | `#232C3A` | hairlines, seam at rest |
| `read` | `#E8EDF5` | primary text |
| `quiet` | `#7A879E` | secondary text |
| `source` | `#4C9AFF` | Tableau ink |
| `target` | `#F2C811` | Power BI ink |
| `held` | `#FF7A6B` | stopped at the seam |

The ground moves off blue-slate `#0E1726` deliberately: a blue ground sides with
Tableau. Neutral ink lets both brand inks read as equals, which is the thesis.

`held` is not red-as-error. These items are the product doing its job.

## Type

- **Display:** Bahnschrift Condensed — DIN 1451, industrial signage lettering.
  Ships with Windows 10+, so nothing is bundled and the exe does not grow. In CSS:
  `"Bahnschrift Condensed", "Bahnschrift", "DIN Condensed", sans-serif` with a
  `font-stretch: condensed` fallback.
- **Body:** Segoe UI Variable Text
- **Data:** Cascadia Code — every formula, DAX expression, name, and number

All three are system faces on Windows, so nothing is downloaded or bundled and the
page renders identically offline.

## Copy

Named for what the user recognises, in the interface's voice.

- Empty stage: **"Drop a Tableau workbook to begin. Nothing leaves this machine."**
  The offline guarantee is a selling point, so it is the empty state.
- Held items: **"Held for you — the aggregation isn't stated in the formula."**
  Never "Failed to convert."
- Actions keep their name through the flow: `Convert` produces `Converted`.

## Quality floor

- Windows "show animations" off → all motion disabled; the seam stays readable.
- Visible keyboard focus throughout.
- Correct at 150% / 200% DPI, and at the 820×560 minimum window.
- If the QML scene fails to load, the Stage degrades to a static rendering. The
  app never shows a blank rectangle.

## Build order

1. **Event spine** — pure Python, test-driven, substrate-independent.
2. **Frontend** — Vite/React scaffold, tokens, the Stage and the Seam, driven by a
   recorded timeline fixture so it is developable without the shell.
3. **Shell + bridge** — pywebview hosting the built assets, wired to real runs.
4. **Local AI assist** — runtime detection, suggestion pipeline, review UI.

Each step is independently valuable and independently verifiable.

## Out of scope

Triage tooling (search, filter, mark-done, batch conversion). The primary user is
the buyer, not the engineer working the list down. Revisit when that changes.
