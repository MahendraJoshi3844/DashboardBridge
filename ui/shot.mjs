// Design QA: screenshot the running UI using the Chrome already on this machine.
// Dev-only tool; not part of the app or its build.
import puppeteer from "puppeteer-core";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const out = process.argv[2] || "shot.png";
const wait = Number(process.argv[3] || 1200);
const clickSelector = process.argv[4] || "";

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: [
    "--no-sandbox",
    "--disable-gpu",
    "--force-device-scale-factor=1",
    "--user-data-dir=" + process.env.TEMP + "/t2pbi-shot-profile",
  ],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 820 });

const errs = [];
page.on("pageerror", (e) => errs.push(String(e)));
page.on("console", (m) => {
  if (m.type() === "error") errs.push(m.text());
});

await page.goto("http://localhost:5199/", { waitUntil: "networkidle0" });
const open = await page.$(".open");
if (open) await open.click();
await new Promise((r) => setTimeout(r, wait));

if (clickSelector) {
  const [sel, text] = clickSelector.split("::");
  const clicked = await page.evaluate(
    (sel, text) => {
      const nodes = [...document.querySelectorAll(sel)];
      const hit = text
        ? nodes.find((n) => n.textContent.includes(text))
        : nodes[0];
      if (hit) hit.click();
      return Boolean(hit);
    },
    sel,
    text || "",
  );
  if (!clicked) console.log("no match for:", clickSelector);
  await new Promise((r) => setTimeout(r, 700));
}

const second = process.argv[5] || "";
if (second) {
  try {
    await page.waitForSelector(second, { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 400));
    const box = await (await page.$(second)).boundingBox();
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    console.log("clicked", second, "at", Math.round(box.x), Math.round(box.y));
  } catch (e) {
    console.log("second click failed:", String(e).slice(0, 100));
  }
  await new Promise((r) => setTimeout(r, 2500));
}

await page.screenshot({ path: out });
console.log("errors:", errs.length ? errs.slice(0, 4) : "none");
await browser.close();
