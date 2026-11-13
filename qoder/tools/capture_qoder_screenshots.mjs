/**
 * Drive the Qoder review app with a real browser and capture screenshots.
 *
 * Usage:
 *   node tools/capture_qoder_screenshots.mjs [baseUrl] [outDir]
 *
 * Needs playwright-core (already installed under stepfun/node_modules) and a
 * local Edge/Chromium install.
 */
import { chromium } from "../../stepfun/node_modules/playwright-core/index.mjs";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

const baseUrl = process.argv[2] || "http://localhost:8601";
const outDir = process.argv[3] || new URL("../screenshots/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

await mkdir(outDir, { recursive: true });

const browser = await chromium.launch({
  channel: "msedge",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
const page = await context.newPage();

async function shot(name) {
  const file = join(outDir, name);
  await page.screenshot({ path: file, fullPage: false });
  console.log(`saved ${file}`);
}

console.log(`opening ${baseUrl}`);
await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 90_000 });
await page.waitForTimeout(4000);
await shot("04-app-home.png");

// Fill the SQL box with the slow-query sample and run the review.
const textarea = page.locator("textarea").first();
await textarea.click();
await textarea.fill(
  [
    "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id",
    "WHERE DATE(o.created_at) = '2026-01-01'",
    "  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')",
    "  AND c.city LIKE '%杭州%'",
    "ORDER BY o.created_at DESC",
    "LIMIT 20, 200000;",
  ].join("\n"),
);
await page.waitForTimeout(500);

const reviewButton = page.getByRole("button", { name: /开始审查/ });
await reviewButton.click();
await page.waitForTimeout(3000);

// Scroll to the results block and capture it.
await page.getByText("审查结果").first().scrollIntoViewIfNeeded();
await page.waitForTimeout(1200);
await shot("05-app-review-results.png");

// Expand the rule list from the sidebar caption area is optional; capture the findings list.
const findings = await page.locator("text=/OB-00").count();
console.log(`rule ids rendered: ${findings}`);

await browser.close();
console.log("done");
