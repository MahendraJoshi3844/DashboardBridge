/**
 * Drive the real app end to end and screenshot each screen.
 *
 * The `screenshots/e2e-*.png` set was taken by hand, so it ages silently: the
 * files stay on disk looking current long after the screens change. This walks
 * the running app instead — choose a direction, open a workbook, analyse,
 * convert, read the results — so every picture is of the build that produced
 * it.
 *
 *   node scripts/walkthrough.mjs [workbook.twb] [outdir]
 *
 * Needs both servers up: the API (default :8010, set API_URL) and `next dev` on
 * :3000, which is the only origin the API's CORS allows.
 *
 * puppeteer-core and the machine's own Chrome, for the same reason
 * `screenshot.mjs` gives: an offline-first product should not have a build step
 * that downloads a browser.
 */

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const workbook = resolve(process.argv[2] ?? "../../testing_content/Superstore.twb");
const outDir = resolve(here, "..", process.argv[3] ?? "screenshots/walkthrough");
const chrome =
  process.env.CHROME_PATH ??
  "C:/Program Files/Google/Chrome/Application/chrome.exe";

mkdirSync(outDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: "new",
  // Chrome exits immediately here without its own profile directory.
  userDataDir: `${process.env.TEMP ?? "/tmp"}/dbb-walkthrough`,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });

const problems = [];
page.on("console", (message) => {
  if (message.type() === "error") problems.push(message.text());
});

let step = 0;
async function shot(name) {
  step += 1;
  const file = `${outDir}/${String(step).padStart(2, "0")}-${name}.png`;
  await page.screenshot({ path: file, fullPage: true });
  console.log(`  ${file}`);
}

/** Click the first element whose text contains `text`. Returns whether it did. */
async function clickText(selector, text) {
  const handle = await page.evaluateHandle(
    (sel, want) =>
      [...document.querySelectorAll(sel)].find((el) =>
        (el.textContent ?? "").toLowerCase().includes(want.toLowerCase()),
      ) ?? null,
    selector,
    text,
  );
  const element = handle.asElement();
  if (!element) return false;
  await element.click();
  return true;
}

/** Wait until some element's text contains `text`, or give up and say so. */
async function waitForText(text, timeout = 60_000) {
  try {
    await page.waitForFunction(
      (want) => document.body.innerText.toLowerCase().includes(want.toLowerCase()),
      { timeout, polling: 400 },
      text,
    );
    return true;
  } catch {
    return false;
  }
}

console.log(`workbook: ${workbook}`);

await page.goto("http://localhost:3000", { waitUntil: "networkidle0" });
await shot("landing");

// Choosing a direction settles in place; a second, separate control is what
// actually moves to the workspace. Two clicks, not one.
if (!(await clickText("a, button", "Choose"))) {
  throw new Error("no direction card to choose - the landing page changed shape");
}
await new Promise((r) => setTimeout(r, 600));
await shot("direction-chosen");

if (!(await clickText("a, button", "Open a workbook"))) {
  throw new Error("nothing offered to open a workbook after choosing a direction");
}
await page.waitForNavigation({ waitUntil: "networkidle0" }).catch(() => {});
await new Promise((r) => setTimeout(r, 800));
await shot("workspace");

const input = await page.$('input[type="file"]');
if (!input) throw new Error("no file input on the workspace page");
await input.uploadFile(workbook);
await shot("workbook-open");

// Analysis and conversion each run inline on the server, so the wait is for
// the screen to say so rather than for a queue.
if (await waitForText("analys")) await shot("analysing");
if (await waitForText("table")) await shot("analysed");

// Each step is confirmed before it runs, so the walk is click, settle, shoot -
// and the labels are the ones on the buttons, not the step names, because
// "Convert" and "Convert this workbook" are two different controls.
const steps = [
  ["Analyse", "analyse"],
  ["Convert this workbook", "convert"],
  ["Convert this workbook", "converted"],
  ["Validate", "validate"],
];

for (const [label, name] of steps) {
  if (!(await clickText("button, a", label))) continue;
  await new Promise((r) => setTimeout(r, 2500));
  await shot(name);
}

// The results screen is the one worth waiting for: it is where the product
// says what it actually produced rather than what it expected to.
if (await waitForText("results", 30_000)) {
  await new Promise((r) => setTimeout(r, 1500));
  await shot("results");
}

await shot("final");

console.log(
  problems.length ? `console errors:\n  ${problems.join("\n  ")}` : "No console errors.",
);
await browser.close();
