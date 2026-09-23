/**
 * Generate the frontend's TypeScript types from the contract schema.
 *
 * AGENTS.md rule 5: nothing crosses a boundary untyped. Pydantic owns the
 * shapes; `packages/contracts/schema.json` is their serialised form; this file
 * is the only thing allowed to turn them into TypeScript. A hand-written
 * interface that duplicates a contract is a second source of truth, and the
 * second one is always the one that drifts.
 *
 *   npm run gen:types
 *
 * The output is committed so a checkout typechecks without running Python.
 * Re-run it whenever packages/contracts changes; never edit the output.
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../../../packages/contracts/schema.json");
const outPath = resolve(here, "../src/types/contracts.ts");

const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
const names = Object.keys(schema.definitions ?? {}).sort();
if (names.length === 0) {
  throw new Error(`No definitions found in ${schemaPath}`);
}

const banner = [
  "/**",
  " * GENERATED FILE — DO NOT EDIT.",
  " *",
  " * Source: packages/contracts/schema.json (Pydantic → JSON Schema).",
  " * Regenerate: npm run gen:types",
  " *",
  ` * ${names.length} contract definitions.`,
  " */",
  "",
  "/* eslint-disable */",
].join("\n");

/*
 * Nothing references the definitions from the schema root, so they are all
 * "unreachable" by the generator's reckoning. They are precisely what we want.
 * Sorting the key order first keeps the output byte-identical run to run
 * (determinism, AGENTS.md "Definition of done").
 */
const sorted = {
  ...schema,
  definitions: Object.fromEntries(names.map((n) => [n, schema.definitions[n]])),
};

const ts = await compile(sorted, schema.title ?? "Contracts", {
  additionalProperties: false,
  bannerComment: banner,
  declareExternallyReferenced: true,
  unreachableDefinitions: true,
  enableConstEnums: false,
  style: {
    singleQuote: false,
    semi: true,
    trailingComma: "all",
  },
});

mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, ts, "utf8");
console.log(`Wrote ${outPath} — ${names.length} definitions.`);
