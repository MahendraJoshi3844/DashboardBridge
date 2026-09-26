/**
 * Drive an engine-backed migration (MicroStrategy or Qlik → Power BI) through the
 * real app and screenshot each step.
 *
 *   node scripts/mstr-walkthrough.mjs <package.mstr> [outdir]
 *   CARD="Qlik → Power BI" node scripts/mstr-walkthrough.mjs <app.zip|script.qvs> [outdir]
 *
 * Needs the API (API_URL, default :8010) and `next dev` on :3000, and an
 * account to sign in with (DBB_EMAIL / DBB_PASSWORD). puppeteer-core and the
 * machine's own Chrome, as `walkthrough.mjs` does.
 */

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const pkg = resolve(process.argv[2] ?? "Executive Sales.mstr");
const outDir = resolve(here, "..", process.argv[3] ?? "screenshots/mstr-walkthrough");
const chrome = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
mkdirSync(outDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: "new",
  userDataDir: `${process.env.TEMP ?? "/tmp"}/dbb-mstr-walkthrough`,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000 });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));

let step = 0;
async function shot(name) {
  step += 1;
  const file = `${outDir}/${String(step).padStart(2, "0")}-${name}.png`;
  await page.screenshot({ path: file, fullPage: true });
  console.log(`  ${file}`);
}
async function clickText(selector, text) {
  const handle = await page.evaluateHandle(
    (sel, want) => [...document.querySelectorAll(sel)].find((el) => (el.textContent ?? "").includes(want)) ?? null,
    selector,
    text,
  );
  const el = handle.asElement();
  if (!el) return false;
  await el.click();
  return true;
}
async function waitForText(text, timeout = 90_000) {
  try {
    await page.waitForFunction((w) => document.body.innerText.includes(w), { timeout, polling: 500 }, text);
    return true;
  } catch {
    return false;
  }
}

await page.goto("http://localhost:3000/migrate", { waitUntil: "networkidle0" });
if (await page.$('input[type="email"]')) {
  await page.type('input[type="email"]', process.env.DBB_EMAIL ?? "dev@local.test");
  await page.type('input[type="password"]', process.env.DBB_PASSWORD ?? "dev password long enough");
  await clickText("button", "Sign in");
  await new Promise((r) => setTimeout(r, 2500));
  await page.goto("http://localhost:3000/migrate", { waitUntil: "networkidle0" });
}
await shot("paths");

const card = process.env.CARD ?? "MicroStrategy → Power BI";
if (!(await clickText("button.mg-path", card))) throw new Error(`no '${card}' card`);
await waitForText("file here", 15_000);
await shot("modal");

const input = await page.$('input[type="file"]');
await input.uploadFile(pkg);
await new Promise((r) => setTimeout(r, 500));
await shot("file-chosen");

await clickText("button", "Start Migration");
await page.waitForNavigation({ waitUntil: "networkidle0", timeout: 60_000 }).catch(() => {});
const done = await waitForText("Migration complete", 120_000);
await new Promise((r) => setTimeout(r, 1500));
await shot(done ? "job-complete" : "job-not-complete");

console.log(done ? "RESULT: migration complete" : "RESULT: did not complete");
console.log(`url: ${page.url()}`);
if (problems.length) console.log(`console errors:\n  ${problems.join("\n  ")}`);
await browser.close();
