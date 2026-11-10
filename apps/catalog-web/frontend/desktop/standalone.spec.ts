import { _electron as electron, expect, test, type ElectronApplication } from "@playwright/test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync, type ChildProcess } from "node:child_process";

type DownloadState = { filename: string; state: string } | null;
type DownloadGlobal = { catalogDownload: DownloadState };
type NativeDownload = {
  setSavePath(path: string): void;
  getFilename(): string;
  once(event: "done", callback: (event: unknown, state: string) => void): void;
};

async function cleanup(app: ElectronApplication | undefined, child: ChildProcess | undefined): Promise<void> {
  if (!app || !child || child.exitCode !== null) return;
  await Promise.race([app.close().catch(() => {}),
    new Promise<void>((resolve) => setTimeout(resolve, 5_000))]);
  if (child.exitCode === null) {
    if (process.platform === "win32" && child.pid) {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"]);
    } else child.kill("SIGKILL");
  }
}

test("delivered offline app preserves lists, previews models, exports, and stops its sidecar", async () => {
  const executablePath = process.env.E2E_DESKTOP_EXECUTABLE;
  if (!executablePath) throw new Error("E2E_DESKTOP_EXECUTABLE must identify the extracted app");
  const state = await mkdtemp(path.join(tmpdir(), "catalog-state-Ž-"));
  let application: ElectronApplication | undefined;
  let child: ChildProcess | undefined;
  const launch = async () => {
    const app = await electron.launch({
      executablePath,
      chromiumSandbox: true,
      args: process.env.E2E_DESKTOP_SOFTWARE_GPU === "1"
        ? ["--use-gl=angle", "--use-angle=swiftshader"] : [],
      env: { ...process.env, MAKERS_SUPPLY_DESKTOP_STATE: state },
      timeout: 60_000,
    });
    application = app;
    child = app.process();
    app.on("console", (message) => console.log(`[electron] ${message.text()}`));
    child.stdout?.on("data", (chunk) => process.stdout.write(chunk));
    child.stderr?.on("data", (chunk) => process.stderr.write(chunk));
    console.log("Electron launched; waiting for catalog window");
    // The installed catalog is fully hashed before the window opens.
    const page = await app.firstWindow({ timeout: 120_000 });
    await page.context().route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.hostname === "127.0.0.1" || ["data:", "blob:"].includes(url.protocol)) {
        return route.continue();
      }
      return route.abort();
    });
    await expect(page.getByRole("heading", { name: "Hardware catalog" })).toBeVisible();
    const security = await app.evaluate(({ app, BrowserWindow }) => {
      const preferences = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
      return {
        sandbox: preferences.sandbox,
        contextIsolation: preferences.contextIsolation,
        nodeIntegration: preferences.nodeIntegration,
        noSandbox: app.commandLine.hasSwitch("no-sandbox"),
        unsafeSoftware: app.commandLine.hasSwitch("enable-unsafe-swiftshader"),
        noGpuSandbox: app.commandLine.hasSwitch("disable-gpu-sandbox"),
      };
    });
    expect(security).toEqual({ sandbox: true, contextIsolation: true,
      nodeIntegration: false, noSandbox: false, unsafeSoftware: false, noGpuSandbox: false });
    return { app, page };
  };
  try {
    let launched = await launch();
    application = launched.app;
    let page = launched.page;
    const origin = new URL(page.url()).origin;
    await page.getByRole("searchbox").fill("motor");
    await page.getByRole("button", { name: "Apply filters" }).click();
    await expect(page.locator(".product-card").first()).toBeVisible();
    for (const [product, selector] of [
      ["la024-030-micro-dc-motor-with-sh1-0", ".preview-button[data-model-name$='.stl']"],
      ["aa004-bt2-6-socket-head-cap-self-tapping-screw-shcs", ".preview-button[data-model-name$='.3mf']"],
    ]) {
      console.log(`Previewing ${product}`);
      await page.goto(`${origin}/products/${product}`);
      await page.locator(selector).first().click();
      await expect(page.locator("#model-viewer")).toHaveAttribute("aria-busy", "false");
      await expect(page.locator("#model-viewer canvas")).toBeVisible();
      await page.locator("#model-dialog .dialog-close").click();
    }
    await page.goto(`${origin}/lists`);
    await page.getByLabel("Name", { exact: true }).fill("Žluťoučký 🔩");
    await page.getByLabel("Store region").selectOption("eu");
    await page.getByRole("button", { name: "Create list" }).click();
    const listPath = new URL(page.url()).pathname;
    await page.getByRole("link", { name: "Browse and select products" }).click();
    await page.locator("[data-product-select]").first().check();
    await page.getByRole("button", { name: /Selected 1/ }).click();
    await page.getByRole("button", { name: "Add selected products" }).click();
    await expect(page.locator(".line-item")).toHaveCount(1);
    for (const format of ["CSV", "JSON"]) {
      console.log(`Downloading ${format}`);
      const destination = path.join(state, `export.${format.toLowerCase()}`);
      await application.evaluate(({ session }, destination) => {
        const status = globalThis as unknown as DownloadGlobal;
        status.catalogDownload = null;
        session.defaultSession.once("will-download", (_event: unknown, item: NativeDownload) => {
          item.setSavePath(destination);
          item.once("done", (_event, state) => {
            status.catalogDownload = { filename: item.getFilename(), state };
          });
        });
      }, destination);
      await page.getByRole("link", { name: `Export ${format}` }).click();
      await expect.poll(() => application!.evaluate(() => (
        globalThis as unknown as DownloadGlobal
      ).catalogDownload)).toEqual({
        filename: `Žluťoučký 🔩.${format.toLowerCase()}`, state: "completed",
      });
      expect((await readFile(destination)).length).toBeGreaterThan(0);
    }
    await page.close();
    await expect.poll(async () => {
      try { await fetch(`${origin}/healthz`); return false; } catch { return true; }
    }).toBe(true);
    await expect.poll(() => child!.exitCode).not.toBeNull();
    await cleanup(application, child);
    application = undefined;
    launched = await launch();
    application = launched.app;
    page = launched.page;
    await page.goto(new URL(listPath, page.url()).href);
    await expect(page.getByRole("heading", { name: "Žluťoučký 🔩" })).toBeVisible();
    await expect(page.locator(".line-item")).toHaveCount(1);
    await page.screenshot({ path: "test-results/desktop/retained-list.png" });
    const restartedOrigin = new URL(page.url()).origin;
    await page.close();
    await expect.poll(async () => {
      try { await fetch(`${restartedOrigin}/healthz`); return false; } catch { return true; }
    }).toBe(true);
    await expect.poll(() => child!.exitCode).not.toBeNull();
  } finally {
    await cleanup(application, child);
    await rm(state, { recursive: true, force: true });
  }
});
