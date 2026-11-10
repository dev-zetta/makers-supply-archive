import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "desktop",
  outputDir: "test-results/desktop",
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  reporter: "list",
});
