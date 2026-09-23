/**
 * Screenshot the running app with the Chrome already installed on the machine.
 *
 * puppeteer-core, never puppeteer: the product is offline-first and a build
 * step that downloads a 150 MB browser is a network dependency in the wrong
 * place. Chrome is where Windows puts it, and a --user-data-dir is mandatory —
 * without one Chrome exits immediately here with "Code: 0".
 *
 *   npm run shot -- [url] [outfile]
 *
 * Two env vars, because the accessibility requirements have to be *seen* and
 * not asserted (03-ux-spec.md, Reduced motion and Accessibility):
 *
 *   SHOT_WIDTH=390            a phone-sized viewport
 *   SHOT_REDUCED=1            emulate prefers-reduced-motion: reduce
 *   SHOT_FOCUS=1              press Tab a few times so the focus ring is in shot
 *   SHOT_TABS=n               how many times (default 3)
 *   SHOT_FULLPAGE=0           just the viewport, for reading detail at 1:1
 *   SHOT_SCROLL=px            scroll to this offset before the shot
 *
 * `emulateMediaFeatures` is the load-bearing part of the reduced-motion shot: a
 * CSS media query alone does not stop a JS animation library, so the page must
 * be rendered with the browser actually reporting the preference.
 */

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const url = process.argv[2] ?? "http://localhost:3000";
const out = resolve(here, "..", process.argv[3] ?? "screenshots/landing.png");
const chrome =
  process.env.CHROME_PATH ??
  "C:/Program Files/Google/Chrome/Application/chrome.exe";

mkdirSync(dirname(out), { recursive: true });

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: "shell",
  args: [
    "--no-sandbox",
    "--disable-gpu",
    `--user-data-dir=${process.env.TEMP}/dbb-shot`,
  ],
});

try {
  const page = await browser.newPage();
  const width = Number(process.env.SHOT_WIDTH ?? 1440);
  const height = Number(process.env.SHOT_HEIGHT ?? 1000);
  await page.setViewport({ width, height, deviceScaleFactor: 1 });

  if (process.env.SHOT_REDUCED === "1") {
    await page.emulateMediaFeatures([
      { name: "prefers-reduced-motion", value: "reduce" },
    ]);
  }

  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));

  await page.goto(url, { waitUntil: "networkidle0", timeout: 60_000 });
  // The status strip resolves its health probe after hydration; wait for the
  // settled screen rather than the first paint.
  await new Promise((r) => setTimeout(r, 1200));

  if (process.env.SHOT_SCROLL !== undefined) {
    const y = Number(process.env.SHOT_SCROLL);
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await new Promise((r) => setTimeout(r, 300));
  }

  if (process.env.SHOT_FOCUS === "1") {
    const tabs = Number(process.env.SHOT_TABS ?? 3);
    for (let i = 0; i < tabs; i += 1) await page.keyboard.press("Tab");
    await new Promise((r) => setTimeout(r, 250));
    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      if (el === null) return "none";
      return `${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 60)}"`;
    });
    console.log(`Focus after ${tabs} Tab presses: ${focused}`);
  }

  // A page that scrolls sideways is a layout failure, so it is measured rather
  // than judged from a full-page screenshot that hides it by widening.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  console.log(
    overflow > 0
      ? `HORIZONTAL OVERFLOW: ${overflow}px past the viewport`
      : "No horizontal overflow.",
  );

  await page.screenshot({
    path: out,
    fullPage: process.env.SHOT_FULLPAGE !== "0",
  });
  console.log(`Wrote ${out}`);

  if (consoleErrors.length > 0) {
    console.log(`\nConsole errors (${consoleErrors.length}):`);
    for (const error of consoleErrors) console.log(`  ${error}`);
  } else {
    console.log("No console errors.");
  }
} finally {
  await browser.close();
}
