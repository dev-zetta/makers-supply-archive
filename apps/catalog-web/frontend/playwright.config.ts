import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    trace: "on-first-retry",
  },
});
