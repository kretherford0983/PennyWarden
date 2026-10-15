import { defineConfig } from "@playwright/test";

// End-to-end UI tests against the production build served by FastAPI with a fresh, empty data directory.
// Run from the repo root after building: `npm --prefix frontend run e2e`
const PORT = 8798;
const PY = process.env.FM_PYTHON || "python";
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  // 2.0.0: on GitHub Actions also the "github" reporter, so each failing test and its error appear as an annotation
  // on the pull request (the job log is not always at hand)
  reporter: process.env.GITHUB_ACTIONS ? [["list"], ["github"]] : [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "off" },
  webServer: {
    command: `node e2e/fresh-server.mjs ${PY} ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
