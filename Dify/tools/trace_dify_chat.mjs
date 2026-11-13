/**
 * Capture what the published Dify app actually returns for a chat turn
 * (SSE payload / error messages). This tells us why the answer is empty.
 *
 * Usage:
 *   node Dify/tools/trace_dify_chat.mjs <shareUrl>
 */
import { chromium } from "../../stepfun/node_modules/playwright-core/index.mjs";

const shareUrl = process.argv[2] || "https://udify.app/chat/CTbEyrNETzo7iVA7";

const browser = await chromium.launch({ channel: "msedge", args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

const events = [];
page.on("response", async (response) => {
  const url = response.url();
  if (!/chat|message|agent|workflow|error/i.test(url)) return;
  const status = response.status();
  let body = "";
  try {
    body = (await response.text()).slice(0, 1200);
  } catch {
    body = "<no body>";
  }
  events.push({ status, url: url.slice(0, 140), body });
});

page.on("console", (message) => {
  if (message.type() === "error") events.push({ status: "console", url: "", body: message.text().slice(0, 400) });
});

await page.goto(shareUrl, { waitUntil: "networkidle", timeout: 90_000 });
await page.waitForTimeout(5000);

const input = page.locator("textarea").first();
await input.click();
await input.fill("HNSW 向量索引的建表语句是什么？");
await input.press("Enter");

for (let i = 0; i < 45; i += 1) {
  await page.waitForTimeout(2000);
  if ((await page.getByText("停止响应").count()) === 0 && events.some((e) => /chat-messages|message/.test(e.url))) break;
}

await page.waitForTimeout(4000);

console.log("=== network events ===");
for (const event of events) {
  console.log(`[${event.status}] ${event.url}`);
  if (event.body) console.log("    ", event.body.replace(/\n/g, " ").slice(0, 700));
  console.log();
}

const body = await page.locator("body").innerText();
console.log("=== chat text tail ===");
console.log(body.slice(-1200));

await browser.close();
