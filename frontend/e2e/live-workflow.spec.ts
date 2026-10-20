import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const specDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(specDirectory, "../..");
const samplePath = path.join(
  projectRoot,
  "frontend/public/samples/ids-demo-mixed.csv",
);
const evidenceDirectory = process.env.E2E_EVIDENCE_DIR
  ? path.resolve(projectRoot, process.env.E2E_EVIDENCE_DIR)
  : path.join(projectRoot, "test-results/e2e-evidence");

function compose(...args: string[]) {
  execFileSync(
    "docker",
    ["compose", "--project-directory", projectRoot, ...args],
    { cwd: projectRoot, stdio: "pipe" },
  );
}

async function expectMetric(
  page: import("@playwright/test").Page,
  label: string,
  value: string,
) {
  const metric = page
    .getByLabel("Analysis summary")
    .locator("div")
    .filter({ has: page.getByText(label, { exact: true }) });
  await expect(metric.locator("strong")).toHaveText(value);
}

async function expectNoHorizontalOverflow(
  page: import("@playwright/test").Page,
) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}

test("real model upload, review, export, validation, and recovery", async ({
  page,
  request,
  baseURL,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });
  const applicationErrors: string[] = [];
  page.on("pageerror", (error) => applicationErrors.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !/status of (422|502|504)/.test(message.text())
    ) {
      applicationErrors.push(message.text());
    }
  });

  await page.goto("/");
  await expect(page.getByText(/Model ready: ids-rf-v1\.0\.0/)).toBeVisible();
  await expect(page.getByLabel("Traffic CSV")).toBeEnabled();

  const templateDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download model template" }).click();
  const templateDownload = await templateDownloadPromise;
  expect(templateDownload.suggestedFilename()).toBe("ids-input-template.csv");
  const templatePath = await templateDownload.path();
  expect(templatePath).not.toBeNull();
  const templateLines = readFileSync(templatePath!, "utf8").trim().split("\n");
  expect(templateLines).toHaveLength(2);
  expect(templateLines[0].split(",")).toHaveLength(64);
  expect(templateLines[0].startsWith("row_id,flow_duration,")).toBe(true);

  await page.getByLabel("Traffic CSV").setInputFiles(samplePath);
  await expect(
    page.getByRole("heading", { name: "Traffic review" }),
  ).toBeVisible();
  await expect(page.getByText("Live model")).toBeVisible();
  await expect(page.getByText("ids-rf-v1.0.0", { exact: true })).toBeVisible();
  await expectMetric(page, "Rows received", "6");
  await expectMetric(page, "Valid", "6");
  await expectMetric(page, "Suspicious", "5");
  await expectMetric(page, "High priority", "4");
  await expectMetric(page, "Needs review", "0");
  for (const category of [
    "Benign",
    "DoS / DDoS",
    "Port scan",
    "Brute force",
    "Web attack",
    "Botnet",
  ]) {
    await expect(
      page.getByText(category, { exact: true }).first(),
    ).toBeVisible();
  }
  await page.screenshot({
    path: path.join(evidenceDirectory, "live-results-desktop.png"),
    fullPage: true,
  });
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 768, height: 1024 });
  await expectNoHorizontalOverflow(page);
  await page.screenshot({
    path: path.join(evidenceDirectory, "live-results-tablet.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
  await page.screenshot({
    path: path.join(evidenceDirectory, "live-results-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.getByLabel("Verdict").selectOption("SUSPICIOUS");
  await expect(page.getByText("Showing 1–5 of 5")).toBeVisible();
  await page.getByRole("button", { name: "Details" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Suspicious", { exact: true })).toBeVisible();
  await expect(
    dialog.getByText("100.00%", { exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(evidenceDirectory, "live-row-detail-desktop.png"),
    fullPage: false,
  });
  await dialog.getByRole("button", { name: "Close" }).click();

  const exportDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export view" }).click();
  const exportDownload = await exportDownloadPromise;
  expect(exportDownload.suggestedFilename()).toBe(
    "flow-review-ids-demo-mixed.csv",
  );
  const exportPath = await exportDownload.path();
  expect(exportPath).not.toBeNull();
  const exportedLines = readFileSync(exportPath!, "utf8").trim().split("\n");
  expect(exportedLines).toHaveLength(6);
  expect(exportedLines[0]).toContain(
    "request_id,model_name,model_version,feature_schema_version,analysis_status",
  );

  await page.getByRole("button", { name: "New analysis" }).click();
  await expect(page.getByText(/Model ready: ids-rf-v1\.0\.0/)).toBeVisible();
  await page.getByLabel("Traffic CSV").setInputFiles({
    name: "invalid-schema.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("row_id,flow_duration\nbad-row,1\n"),
  });
  await expect(page.getByText("MISSING_REQUIRED_COLUMNS")).toBeVisible();
  await expect(page.getByText(/and 54 more required fields/)).toBeVisible();
  await page.screenshot({
    path: path.join(evidenceDirectory, "invalid-schema-desktop.png"),
    fullPage: true,
  });

  await page.getByRole("button", { name: "Choose another CSV" }).click();
  await expect(page.getByText(/Model ready: ids-rf-v1\.0\.0/)).toBeVisible();
  await page.getByLabel("Traffic CSV").setInputFiles({
    name: "over-limit.csv",
    mimeType: "text/csv",
    buffer: Buffer.alloc(10 * 1024 * 1024 + 1, "0"),
  });
  await expect(page.getByText("FILE_TOO_LARGE")).toBeVisible();

  await page.getByRole("button", { name: "Choose another CSV" }).click();
  await expect(page.getByText(/Model ready: ids-rf-v1\.0\.0/)).toBeVisible();
  compose("stop", "api");
  await page.getByRole("button", { name: "Review sample" }).click();
  await expect(
    page.getByText(/HTTP_502|HTTP_504|NETWORK_UNAVAILABLE/),
  ).toBeVisible();

  compose("start", "api");
  await expect
    .poll(async () => (await request.get(`${baseURL}/ready`)).status(), {
      timeout: 60_000,
    })
    .toBe(200);
  await page.getByRole("button", { name: "Choose another CSV" }).click();
  await expect(page.getByText(/Model ready: ids-rf-v1\.0\.0/)).toBeVisible();
  await page.getByRole("button", { name: "Review sample" }).click();
  await expect(
    page.getByRole("heading", { name: "Traffic review" }),
  ).toBeVisible();
  await expectMetric(page, "Rows received", "6");
  await page.screenshot({
    path: path.join(evidenceDirectory, "recovered-results-desktop.png"),
    fullPage: true,
  });

  expect(applicationErrors).toEqual([]);
});
