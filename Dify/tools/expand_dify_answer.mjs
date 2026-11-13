/**
 * Open the collapsed answer node in the published Dify chat app and capture it.
 *
 * Usage:
 *   node Dify/tools/expand_dify_answer.mjs <shareUrl> [outDir]
 */
import { chromium } from "../../stepfun/node_modules/playwright-core/index.mjs";
import { mkdir, writeFile } from "node:fs/promises";

const shareUrl = process.argv[2] || "https://udify.app/chat/CTbEyrNETzo7iVA7";
const outDir = process.argv[3] || new URL("../screenshots/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
await mkdir(outDir, { recursive: true });

const browser = await chromium.launch({ channel: "msedge", args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
await page.goto(shareUrl, { waitUntil: "networkidle", timeout: 90_000 });
await page.waitForTimeout(6000);

const input = page.locator("textarea").first();
await input.click();
await input.fill("HNSW 向量索引的建表语句是什么？");
await input.press("Enter");
console.log("sent");

// wait for the answer node to finish (the stop button disappears)
for (let i = 0; i < 60; i += 1) {
  await page.waitForTimeout(2000);
  if ((await page.getByText("停止响应").count()) === 0) break;
}
await page.waitForTimeout(3000);

// expand every collapsed node output (Dify chatflow shows them behind a chevron)
const expanders = page.locator('[class*="expand"], button:has(svg)');
const clicks = await expanders.count();
console.log("clickable nodes:", clicks);
for (let i = 0; i < clicks; i += 1) {
  try {
    await expanders.nth(i).click({ timeout: 1500 });
    await page.waitForTimeout(600);
  } catch {
    /* not clickable */
  }
}
await page.waitForTimeout(2500);

const body = await page.locator("body").innerText();
const blocks = page.locator(".markdown-body, [class*='markdown']");
const texts = [];
for (let i = 0; i < (await blocks.count()); i += 1) {
  const t = await blocks.nth(i).innerText().catch(() => "");
  if (t && t.length > 200) texts.push(t);
}
const answer = texts.length ? texts[texts.length - 1] : body.slice(-3000);

const markers = ["医书摘录", "望闻问切", "药方", "忌口", "养生建议", "医嘱小笺"];
console.log("markers in last block:", markers.filter((m) => answer.includes(m)).join(", ") || "(none)");
console.log("answer length:", answer.length);

await page.screenshot({ path: `${outDir}/03-dify-answer-expanded.png`, fullPage: false });
console.log(`saved ${outDir}/03-dify-answer-expanded.png`);
await writeFile(`${outDir}/dify-answer.txt`, answer, "utf8");
console.log("---- answer head ----");
console.log(answer.slice(0, 2000));
await browser.close();
