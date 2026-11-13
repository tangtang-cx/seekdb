/**
 * Drive the published Dify chat app with a real browser (Edge via playwright-core),
 * run the verification sample, capture the answer text and a screenshot.
 *
 * Usage:
 *   node tools/drive_dify_chat.mjs <shareUrl> [outDir]
 */
import { chromium } from "../../stepfun/node_modules/playwright-core/index.mjs";
import { mkdir, writeFile } from "node:fs/promises";

const shareUrl = process.argv[2] || "https://udify.app/chat/CTbEyrNETzo7iVA7";
const outDir = process.argv[3] || new URL("../screenshots/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
await mkdir(outDir, { recursive: true });

const browser = await chromium.launch({ channel: "msedge", args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
const page = await context.newPage();

console.log(`opening ${shareUrl}`);
await page.goto(shareUrl, { waitUntil: "networkidle", timeout: 90_000 });
await page.waitForTimeout(6000);

const title = await page.title();
console.log("title:", title);

const input = page.locator("textarea").first();
await input.waitFor({ state: "visible", timeout: 60_000 });

const query = "HNSW 向量索引的建表语句是什么？";
await input.click();
await input.fill(query);
await page.waitForTimeout(500);
await page.screenshot({ path: `${outDir}/01-dify-typed.png` });
console.log("typed the sample query");

await input.press("Enter");
console.log("sent; waiting for generation to finish...");

// Wait until the generation stops (the "stop" button disappears) and the last
// markdown block contains the six section markers.
const markers = ["医书摘录", "望闻问切", "药方", "忌口", "养生建议", "医嘱小笺"];
let answer = "";
let found = [];
for (let attempt = 0; attempt < 90; attempt += 1) {
  await page.waitForTimeout(2000);
  const blocks = page.locator(".markdown-body, [class*='markdown'], div[class*='answer']");
  const count = await blocks.count();
  let text = "";
  for (let index = count - 1; index >= 0; index -= 1) {
    const candidate = await blocks.nth(index).innerText().catch(() => "");
    if (candidate && candidate.length > 120) {
      text = candidate;
      break;
    }
  }
  found = markers.filter((marker) => text.includes(marker));
  const stillGenerating = await page.getByText("停止响应").count();
  if (found.length >= 5 && stillGenerating === 0) {
    answer = text;
    break;
  }
  if (attempt % 5 === 0) console.log(`  ... waiting (markers ${found.length}, generating ${stillGenerating})`);
}
console.log("markers found in the answer:", found.join(", ") || "(none)");

await page.screenshot({ path: `${outDir}/02-dify-answer.png` });
console.log(`saved ${outDir}/02-dify-answer.png`);

await writeFile(`${outDir}/dify-answer.txt`, answer || "(empty)", "utf8");
console.log("---- answer ----");
console.log((answer || "(empty)").slice(2500));

await browser.close();
console.log("done");
