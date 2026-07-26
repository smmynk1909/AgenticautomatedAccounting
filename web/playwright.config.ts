import { defineConfig, devices } from "@playwright/test";

// doc 12 §5's Sprint 4 "Playwright ticket flow" deliverable. Runs against
// the Vite dev server with the gateway API mocked at the network layer
// (e2e/ticket-flow.spec.ts's page.route calls) rather than a live
// docker-compose stack — see DEVIATIONS.md for why: a browser-driven e2e
// suite that needs Postgres/Redis/Ollama/every MCP server up just to
// exercise React state transitions would make `npm test` here as heavy as
// `make bootstrap`, for a test whose actual job is "does the UI wire up
// correctly," not "does the backend work" (that's the graph/contract test
// tiers' job, doc 11 §10).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --port 5173",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
