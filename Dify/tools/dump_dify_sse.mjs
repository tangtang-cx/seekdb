/**
 * Dump the full SSE stream of one chat turn to a file and print the error-ish parts.
 *
 * Usage:
 *   node Dify/tools/dump_dify_sse.mjs <shareUrl> [outFile]
 */
import { chromium } from "../../stepfun/node_modules/playwright-core/index.mjs";
import { writeFile } from "node:fs/promises";

const shareUrl = process.argv[2] || "https://udify.app/chat/CTbEyrNETzo7iVA7";
const outFile = process.argv[3] || "C:/Users/Lenovo/AppData/Local/Temp/opencode/dify_sse.txt";

const browser = await chromium.launch({ channel: "msedge", args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

let sse = "";
page.on("response", async (response) => {
  const url = response.url();
  if (!url.includes("chat-messages")) return;
  try {
    sse = await response.text();
  } catch {
    sse = "<stream consumed>";
  }
});

await page.goto(shareUrl, { waitUntil: "networkidle", timeout: 90_000 });
await page.waitForTimeout(5000);
const input = page.locator("textarea").first();
await input.click();
await input.fill("HNSW 向量索引的建表语句是什么？");
await input.press("Enter");
await page.waitForTimeout(45_000);

await writeFile(outFile, sse, "utf8");
console.log("sse bytes:", sse.length);

const events = sse.split("\n\n").filter((chunk) => chunk.trim());
console.log("events:", events.length);
for (const event of events) {
  const kind = (event.match(/^event:\s*(\S+)/m) || [])[1] || "?";
  const data = (event.match(/^data:\s*([\s\S]*)$/m) || [])[1] || "";
  if (/error|failed|exception/i.test(event)) {
    console.log(`\n>>> ${kind}: ${data.slice(0, 1500)}`);
  } else {
    console.log(`    ${kind}  ${data.slice(0, 160)}`);
  }
}

await browser.close();
