import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("e2e-admin");
  await page.getByLabel("Password").fill(process.env.E2E_PASSWORD ?? "e2e secure password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Hardware catalog" })).toBeVisible();
});

test("searches and opens a product with its official information", async ({ page }) => {
  await page.getByLabel("Search").fill("motor");
  await page.getByRole("button", { name: "Apply filters" }).click();
  const firstProduct = page.locator(".product-card").first();
  await expect(firstProduct).toBeVisible();
  await firstProduct.locator("a").click();
  await expect(page.getByRole("heading", { name: /variants and pricing/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dimensions" })).toBeVisible();
});

test("renders an archived STL with the shaded model viewer", async ({ page }) => {
  await page.goto("/products/la024-030-micro-dc-motor-with-sh1-0");
  await page.getByRole("button", { name: "Preview 3D" }).first().click();
  const dialog = page.locator("#model-dialog");
  const viewer = page.locator("#model-viewer");
  await expect(dialog).toBeVisible();
  await expect(viewer).toHaveAttribute("aria-busy", "false", { timeout: 30_000 });
  await expect(viewer.locator("canvas")).toBeVisible();
  await expect(page.getByText("embedded 3MF colors and textures")).toBeVisible();
  await dialog.screenshot({ path: "test-results/shaded-stl-preview.png" });
});

test("renders embedded 3MF material data when available", async ({ page }) => {
  await page.goto("/products/aa004-bt2-6-socket-head-cap-self-tapping-screw-shcs");
  await page.locator('.preview-button[data-model-name$=".3mf"]').first().click();
  const viewer = page.locator("#model-viewer");
  await expect(viewer).toHaveAttribute("aria-busy", "false", { timeout: 30_000 });
  await expect(viewer.locator("canvas")).toBeVisible();
});

test("browses and zooms the product image gallery", async ({ page }) => {
  await page.locator(".product-card a").first().click();
  const mainImage = page.locator("#gallery-main-image");
  await expect(mainImage).toBeVisible();
  await page.locator("[data-gallery-open]").click();
  const dialog = page.locator("#image-dialog");
  await expect(dialog).toBeVisible();
  await page.locator("[data-image-zoom-in]").click();
  await expect(page.locator("[data-image-zoom-reset]")).toHaveText("125%");
  await page.locator("#image-dialog .dialog-close").click();
  await expect(dialog).not.toBeVisible();
});

test("updates image-specific identifiers while browsing variants", async ({ page }) => {
  await page.goto("/products/bb001-compression-spring?region=eu");
  const partNumber = page.locator("[data-gallery-part-number-output]");
  const sku = page.locator("[data-gallery-skus-output]");
  await page.locator('[data-gallery-thumbnail][data-gallery-part-number="BB001"]').click();
  await expect(partNumber).toHaveText("BB001");
  await expect(sku).toContainText("EU");
  await page.locator('[data-gallery-thumbnail][data-gallery-part-number="BB002"]').click();
  await expect(partNumber).toHaveText("BB002");
  await expect(sku).toContainText("47966946132316");
});

test("filters automatically and switches responsive result layouts", async ({ page }) => {
  const category = page.getByLabel("Category");
  await Promise.all([
    page.waitForURL(/category=/),
    category.selectOption({ index: 1 }),
  ]);
  await expect(page.locator(".product-card").first()).toBeVisible();

  await page.getByTitle("List view").click();
  await expect(page.locator(".product-grid")).toHaveClass(/view-list/);
  await expect(page).toHaveURL(/view=list/);

  const layout = page.locator("#catalog-layout");
  await page.getByTitle("Collapse filters").click();
  await expect(layout).toHaveClass(/filters-collapsed/);
  await expect(page.getByTitle("Expand filters")).toBeVisible();
});

test("switches the global storefront scope across catalog and product pages", async ({ page }) => {
  const region = page.getByLabel("Catalog region");
  await expect(page.locator('#catalog-filters select[name="region"]')).toHaveCount(0);
  await Promise.all([
    page.waitForResponse((response) => (
      new URL(response.url()).pathname === "/region" &&
      new URL(response.url()).searchParams.get("region") === "eu"
    )),
    region.selectOption("eu"),
  ]);
  await expect(page.getByLabel("Catalog region")).toHaveValue("eu");

  await page.goto("/products/zk003-cyberbrick-hardware-kit");
  await expect(page.getByRole("heading", { name: "EU variants and pricing" })).toBeVisible();
  await expect(page.locator(".commerce-table thead")).not.toContainText("Region");
  await expect(page.locator(".commerce-table tbody tr").first()).toContainText("EUR");

  await Promise.all([
    page.waitForResponse((response) => (
      new URL(response.url()).pathname === "/region" &&
      new URL(response.url()).searchParams.get("region") === "global"
    )),
    page.getByLabel("Catalog region").selectOption("global"),
  ]);
  await expect(page.getByRole("heading", { name: "Regional variants and pricing" })).toBeVisible();
  await expect(page.locator(".commerce-table thead")).toContainText("Region");
  await page.goto("/");
  await expect(page.getByLabel("Catalog region")).toHaveValue("global");
});

test("keeps pagination compact and loads the next page while scrolling", async ({ page }) => {
  await page.goto("/?page=2&region=us");
  const previous = page.locator("[data-previous-page]");
  const next = page.locator("[data-next-page]");
  await expect(previous).toBeVisible();
  await expect(next).toBeVisible();
  const previousBounds = await previous.boundingBox();
  const nextBounds = await next.boundingBox();
  expect(previousBounds).not.toBeNull();
  expect(nextBounds).not.toBeNull();
  expect(previousBounds!.width).toBeLessThan(180);
  expect(nextBounds!.width).toBeLessThan(180);

  const initialCount = await page.locator(".product-card").count();
  const expectedTotal = await page.locator("[data-results-title]").getAttribute(
    "data-results-total",
  );
  await page.locator("[data-pagination]").scrollIntoViewIfNeeded();
  await expect.poll(() => page.locator(".product-card").count()).toBeGreaterThan(initialCount);
  await expect(page.locator("[data-results-title]")).toContainText(`of ${expectedTotal}`);
});

test("loads a mirrored product image", async ({ page }) => {
  const image = page.locator(".product-card img").first();
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth))
    .toBeGreaterThan(0);
});

test("centers foreground content inside result images", async ({ page }) => {
  await page.goto("/?q=xc001&region=us");
  const image = page.locator(".product-card .product-media img").first();
  const media = image.locator("..");
  await expect(image).toHaveCSS("object-fit", "contain");
  await expect(image).toHaveCSS("object-position", "50% 50%");
  const imageBounds = await image.boundingBox();
  const mediaBounds = await media.boundingBox();
  expect(imageBounds).not.toBeNull();
  expect(mediaBounds).not.toBeNull();
  expect(imageBounds!.y).toBeCloseTo(mediaBounds!.y, 0);
  expect(imageBounds!.height).toBeCloseTo(mediaBounds!.height, 0);
});

test("fits mobile screens and keeps filters accessible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 740 });
  await expect(page.locator(".product-card").first()).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true);
  await page.getByTitle("Collapse filters").click();
  await expect(page.locator("#filter-panel")).toBeHidden();
  await page.getByTitle("Expand filters").click();
  await expect(page.locator("#filter-panel")).toBeVisible();
});

test("creates a regional parts list", async ({ page }) => {
  await page.getByRole("link", { name: "Parts lists" }).click();
  await page.getByLabel("Name").fill("Browser test BOM");
  await page.getByLabel("Store region").selectOption("eu");
  await page.getByRole("button", { name: "Create list" }).click();
  await expect(page.getByRole("heading", { name: "Browser test BOM" })).toBeVisible();
  await expect(page.getByText("Taxes, shipping, and currency conversion are not included.")).toBeVisible();
});

test("keeps the add-to-list form inside a narrow product card", async ({ page }) => {
  await page.getByRole("link", { name: "Parts lists" }).click();
  await page.getByLabel("Name").fill("Responsive product form");
  await page.getByLabel("Store region").selectOption("us");
  await page.getByRole("button", { name: "Create list" }).click();
  await page.setViewportSize({ width: 1365, height: 768 });
  await page.goto("/products/clock-components-kit-011");

  const form = page.locator("#add-to-list");
  const card = page.locator(".product-heading");
  await expect(form).toBeVisible();
  const formBounds = await form.boundingBox();
  const cardBounds = await card.boundingBox();
  expect(formBounds).not.toBeNull();
  expect(cardBounds).not.toBeNull();
  expect(formBounds!.x).toBeGreaterThanOrEqual(cardBounds!.x);
  expect(formBounds!.x + formBounds!.width).toBeLessThanOrEqual(
    cardBounds!.x + cardBounds!.width + 1,
  );
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true);
});

test("pins product facts and expands a gallery-height description", async ({ page }) => {
  await page.setViewportSize({ width: 1365, height: 768 });
  await page.goto("/products/zk003-cyberbrick-hardware-kit");
  const gallery = page.locator(".gallery");
  const heading = page.locator(".product-heading");
  const description = page.locator("[data-product-description]");
  const toggle = page.locator("[data-description-toggle]");
  await expect(toggle).toBeVisible();
  await expect(description).toHaveCSS("text-align", "justify");
  const galleryBounds = await gallery.boundingBox();
  const headingBounds = await heading.boundingBox();
  const factsBounds = await page.locator(".product-primary-facts").boundingBox();
  const descriptionBounds = await description.boundingBox();
  expect(galleryBounds).not.toBeNull();
  expect(headingBounds).not.toBeNull();
  expect(factsBounds).not.toBeNull();
  expect(descriptionBounds).not.toBeNull();
  expect(headingBounds!.height).toBeCloseTo(galleryBounds!.height, 0);
  expect(factsBounds!.y).toBeLessThan(descriptionBounds!.y);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toHaveText("Show less");
  await expect.poll(async () => (await heading.boundingBox())?.height ?? 0)
    .toBeGreaterThan(headingBounds!.height);
});

test("selects filtered catalog products into a new parts list", async ({ page }) => {
  await page.locator("[data-product-select]").first().check();
  await page.getByRole("button", { name: /Selected 1/ }).click();
  await expect(page.getByRole("heading", { name: "Selected hardware" })).toBeVisible();
  await page.getByLabel("Parts list").selectOption("__new__");
  await page.getByLabel("New list name").fill("Catalog picker BOM");
  await page.getByLabel("Store region").selectOption("us");
  await page.getByRole("button", { name: "Add selected products" }).click();
  await expect(page.getByRole("heading", { name: "Catalog picker BOM" })).toBeVisible();
  await expect(page.locator(".line-item")).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Browse and select products" })).toBeVisible();
});
