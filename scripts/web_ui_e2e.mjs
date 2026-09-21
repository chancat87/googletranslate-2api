import { spawn } from "node:child_process";
import http from "node:http";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(SCRIPT_DIR, "..");
const MOCK_PORT = 8899;
const APP_PORT = 8091;
const MOCK_URL = `http://127.0.0.1:${MOCK_PORT}`;
const APP_URL = `http://127.0.0.1:${APP_PORT}`;
const MASTER_KEY = "test-master-key-0000000000000000000000";

function pythonBin() {
  const win = process.platform === "win32";
  const venv = win
    ? join(ROOT, ".venv", "Scripts", "python.exe")
    : join(ROOT, ".venv", "bin", "python");
  return existsSync(venv) ? venv : process.env.PYTHON || "python";
}

function waitUrl(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolvePromise, reject) => {
    const check = () => {
      if (Date.now() > deadline) return reject(new Error(`timeout: ${url}`));
      const req = http.get(url, { timeout: 1500 }, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolvePromise();
        setTimeout(check, 300);
      });
      req.on("error", () => setTimeout(check, 300));
      req.on("timeout", () => {
        req.destroy();
      });
    };
    check();
  });
}

function stop(proc) {
  if (!proc || proc.exitCode !== null) return;
  try { proc.kill(); } catch (e) { /* ignore */ }
}

async function main() {
  const baseEnv = { ...process.env, PYTHONUTF8: "1" };
  const appEnv = {
    ...baseEnv,
    GOOGLE_API_KEY: "dummy-key-for-mock",
    API_MASTER_KEY: MASTER_KEY,
    LOG_LEVEL: "WARNING",
    LOG_FORMAT: "json",
    UPSTREAM_BASE_URL: MOCK_URL,
    CACHE_BACKEND: "memory",
  };
  const mock = spawn(
    pythonBin(),
    ["-m", "uvicorn", "mock_upstream:app", "--app-dir", join(ROOT, "scripts"), "--port", String(MOCK_PORT), "--log-level", "warning"],
    { cwd: ROOT, env: baseEnv, stdio: "ignore", windowsHide: true }
  );
  const app = spawn(
    pythonBin(),
    ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", String(APP_PORT), "--log-level", "warning"],
    { cwd: ROOT, env: appEnv, stdio: "ignore", windowsHide: true }
  );
  let browser;
  try {
    await waitUrl(`${MOCK_URL}/health`, 30000);
    await waitUrl(`${APP_URL}/health`, 30000);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.addInitScript((key) => {
      localStorage.setItem("ui_token", key);
    }, MASTER_KEY);
    const errors = [];
    page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
    page.on("pageerror", (err) => errors.push(String(err)));

    await page.goto(`${APP_URL}/app`, { waitUntil: "networkidle" });
    const title = await page.title();
    if (!title.includes("管理面板")) throw new Error(`unexpected title: ${title}`);

    await page.click('[data-action="theme"]');
    const theme = await page.evaluate(() => document.documentElement.dataset.theme);
    if (theme !== "dark") throw new Error(`theme not dark: ${theme}`);

    await page.fill("#token", MASTER_KEY);
    await page.click('[data-action="savetoken"]');
    await page.click('[data-view="translate"]');
    await page.fill("#transText", "hello world");
    await page.click('[data-action="translate"]');
    await page.waitForFunction(
      () => {
        const el = document.getElementById("translateOutput");
        return el && el.textContent.trim() && el.textContent !== "翻译中…";
      },
      undefined,
      { timeout: 30000 }
    );
    const output = await page.textContent("#translateOutput");
    if (!output.includes("mock")) throw new Error(`unexpected output: ${output}`);

    await page.click('.nav-item[data-view="keys"]');
    await page.click('summary:has-text("批量导入")');
    await page.fill("#bulkKeys", "k-bulk-1\nk-bulk-2");
    await page.click('[data-action="bulkkeys"]');
    await page.waitForFunction(
      () => document.getElementById("toast").textContent.includes("新增 2 个"),
      undefined,
      { timeout: 10000 }
    );

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(400);
    const mobileNavVisible = await page.isVisible(".mobile-nav");
    if (!mobileNavVisible) throw new Error("mobile nav not visible");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2
    );
    if (overflow) throw new Error("horizontal overflow on mobile");

    await page.goto(`${APP_URL}/admin`, { waitUntil: "networkidle" });
    const adminText = await page.textContent("body");
    if (!adminText.includes("管理面板")) throw new Error("admin page missing brand");

    if (errors.length) throw new Error(`console errors: ${errors.join(" | ")}`);
    console.log("WEB UI BROWSER E2E: PASS");
  } finally {
    if (browser) await browser.close();
    stop(app);
    stop(mock);
  }
}

main().catch((err) => {
  console.error("WEB UI BROWSER E2E: FAIL", err);
  process.exitCode = 1;
});
