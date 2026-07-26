import { expect, test } from "@playwright/test";

// doc 12 §5 Sprint 4's "Playwright ticket flow" deliverable, doc 07's
// create-ticket UX (gateway POST/GET /api/tickets, awp_gateway/routers/
// tickets.py). Gateway responses are mocked via page.route — see
// playwright.config.ts's docstring for why this isn't a live-backend e2e
// test.

const CREATED_TICKET = {
  ticket_id: "TKT-2026-E2E0001",
  category: "device",
  subcategory: null,
  priority: "P3",
  status: "new",
  summary_current: "Laptop screen flickering",
  assignee_id: null,
};

test("dev login -> create ticket -> ticket appears in list", async ({ page }) => {
  let ticketCreated = false;

  await page.route("**/api/dev/login", async (route) => {
    await route.fulfill({ json: { token: "fake-dev-token" } });
  });

  await page.route("**/api/tickets", async (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      ticketCreated = true;
      await route.fulfill({ json: CREATED_TICKET });
      return;
    }
    // GET
    await route.fulfill({ json: { tickets: ticketCreated ? [CREATED_TICKET] : [] } });
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "AWP — Dev Login" })).toBeVisible();
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page.getByRole("heading", { name: "AWP" })).toBeVisible();
  await page.getByRole("button", { name: "Tickets" }).click();

  await expect(page.getByText("No tickets visible to your role.")).toBeVisible();

  await page.getByRole("button", { name: "New ticket" }).click();
  await page.getByPlaceholder("Subject").fill("Broken laptop screen");
  await page.getByPlaceholder("Description").fill("Laptop screen flickering");
  await page.getByRole("button", { name: "Create" }).click();

  await expect(page.getByText("TKT-2026-E2E0001")).toBeVisible();
  await expect(page.getByText("Laptop screen flickering")).toBeVisible();
});

test("failed ticket list load surfaces an error instead of a blank screen", async ({ page }) => {
  await page.route("**/api/dev/login", async (route) => {
    await route.fulfill({ json: { token: "fake-dev-token" } });
  });
  await page.route("**/api/tickets", async (route) => {
    await route.fulfill({
      status: 500,
      json: { error: { code: "INTERNAL", message: "boom" } },
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("button", { name: "Tickets" }).click();

  await expect(page.getByText("boom")).toBeVisible();
});
