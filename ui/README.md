# t2pbi interface

Vite + React + TypeScript + Motion. No Tailwind, no component library, no icon
package, no web fonts — hand-written CSS and Windows system faces, which is both
lighter and more distinctive than a utility framework.

```bash
npm install
npm run dev     # http://localhost:5173, driven by a fixture from a real run
npm run build   # -> ../engines/t2pbi/desktop/web, bundled into the exe
```

`src/fixture.json` is recorded from a real Superstore conversion, so the UI is
always developed against genuine engine output. It and the AI-assist stub in
`bridge.ts` are guarded by `import.meta.env.DEV` and never ship.

`shot.mjs` screenshots the running UI using the Chrome already installed on the
machine (no bundled browser). It is how the design gets critiqued, and it caught
three real defects: the stream not autoplaying, flight chips smearing into an
illegible pile, and held calculations being buried under field-well holds.

```bash
node shot.mjs out.png 6500 ".helditem::Sales Forecast" ".btn--draft"
```
