/**
 * Measure text contrast against the surface each ink actually sits on.
 *
 * 03-ux-spec.md: "Text contrast >= 4.5:1 against its own surface. Disabled
 * controls are exempt; meaningful text is not. Contrast is measured, not
 * judged by eye."
 *
 * Glass surfaces are translucent, so the effective background is composited
 * here exactly as the browser composites it: alpha over the ground beneath.
 * Comparing an ink against the *token* rather than the *composite* would
 * report a number nobody ever sees.
 *
 *   node scripts/check-contrast.mjs        exits 1 if any pair is under 4.5:1
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const tokensPath = resolve(here, "../src/styles/tokens.css");
const css = readFileSync(tokensPath, "utf8");

/**
 * Read one palette's tokens out of a `{ ... }` block.
 *
 * Two palettes now live in this file, and the light one overrides only what it
 * changes - so it is read *on top of* the dark one rather than instead of it.
 * Reading it alone would measure a handful of inks against a background token
 * it never redefined, which is a number nobody sees.
 *
 * @param {string} selector
 * @returns {Map<string, string>}
 */
function tokensIn(selector) {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`No ${selector} block in tokens.css`);
  const open = css.indexOf("{", start);
  let depth = 0;
  let end = open;
  for (; end < css.length; end += 1) {
    if (css[end] === "{") depth += 1;
    else if (css[end] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  const block = css.slice(open, end);
  /** @type {Map<string, string>} */
  const found = new Map();
  for (const match of block.matchAll(/(--dbb-[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    found.set(match[1], match[2].trim());
  }
  return found;
}

const dark = tokensIn(":root {");
const light = new Map([...dark, ...tokensIn(':root[data-theme="light"]')]);

/** The palette currently being measured. */
let tokens = dark;

/** @param {string} name */
function token(name) {
  const value = tokens.get(name);
  if (value === undefined) throw new Error(`Missing token ${name}`);
  return value;
}

/**
 * Parse `#rrggbb` or `rgba(r, g, b, a)` into [r, g, b, a] with 0-255 channels.
 * @param {string} value
 * @returns {[number, number, number, number]}
 */
function parseColor(value) {
  const hex = value.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
  }
  const rgba = value.match(
    /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,/\s]+([\d.]+))?\s*\)$/i,
  );
  if (rgba) {
    return [
      Number(rgba[1]),
      Number(rgba[2]),
      Number(rgba[3]),
      rgba[4] === undefined ? 1 : Number(rgba[4]),
    ];
  }
  throw new Error(`Cannot parse colour: ${value}`);
}

/**
 * Composite a possibly-translucent colour over an opaque one.
 * @param {[number, number, number, number]} fg
 * @param {[number, number, number, number]} bg
 * @returns {[number, number, number, number]}
 */
function over(fg, bg) {
  const a = fg[3];
  return [
    fg[0] * a + bg[0] * (1 - a),
    fg[1] * a + bg[1] * (1 - a),
    fg[2] * a + bg[2] * (1 - a),
    1,
  ];
}

/** WCAG 2.1 relative luminance. @param {[number,number,number,number]} c */
function luminance(c) {
  const [r, g, b] = [c[0], c[1], c[2]].map((channel) => {
    const s = channel / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * @param {[number,number,number,number]} fg
 * @param {[number,number,number,number]} bg
 */
function ratio(fg, bg) {
  const a = luminance(fg);
  const b = luminance(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

/** Surfaces, resolved to what the eye receives. */
const MIN = 4.5;

/** Every ink that carries meaning. Nothing decorative is exempted here. */
const inks = [
  ["ink", "--dbb-ink"],
  ["ink-muted", "--dbb-ink-muted"],
  ["ink-faint", "--dbb-ink-faint"],
  ["ink-source", "--dbb-ink-source"],
  ["ink-target", "--dbb-ink-target"],
  ["ink-held", "--dbb-ink-held"],
  ["status-good", "--dbb-status-good"],
  ["status-warning", "--dbb-status-warning"],
  ["status-serious", "--dbb-status-serious"],
  ["status-critical", "--dbb-status-critical"],
  ["focus", "--dbb-focus"],
];

/**
 * Measure one palette and report. Returns how many pairs failed.
 * @param {string} name
 * @param {Map<string, string>} palette
 */
function measure(name, palette) {
  tokens = palette;

  const base = parseColor(token("--dbb-bg-base"));
  const raised = over(parseColor(token("--dbb-bg-raised")), base);
  const glass = over(parseColor(token("--dbb-surface")), base);
  const glassStrong = over(parseColor(token("--dbb-surface-strong")), base);

  const surfaces = [
    ["page ground", base],
    ["raised header", raised],
    ["glass panel", glass],
    ["glass panel (strong)", glassStrong],
  ];

  let failures = 0;
  const rows = [];
  for (const [inkName, inkToken] of inks) {
    const ink = parseColor(token(inkToken));
    for (const [surfaceName, surface] of surfaces) {
      const value = ratio(over(ink, surface), surface);
      const pass = value >= MIN;
      if (!pass) failures += 1;
      rows.push(
        `${pass ? "PASS" : "FAIL"}  ${value.toFixed(2).padStart(6)}:1  ` +
          `${inkName.padEnd(16)} on ${surfaceName}`,
      );
    }
  }

  console.log(`\n--- ${name} ---`);
  console.log(rows.join("\n"));
  console.log(
    `${rows.length} pairs measured against WCAG AA ${MIN}:1 - ` +
      (failures === 0 ? "all pass." : `${failures} FAILING.`),
  );
  return failures;
}

// Both palettes, every run. A theme that is only checked when someone
// remembers is a theme that fails contrast the first time nobody does.
const total = measure("dark", dark) + measure("light", light);

process.exit(total === 0 ? 0 : 1);
