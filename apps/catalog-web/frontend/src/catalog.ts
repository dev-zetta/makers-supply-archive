const filterForm = document.querySelector<HTMLFormElement>("#catalog-filters");

document.querySelectorAll<HTMLSelectElement>("[data-global-region-switch]").forEach((control) => {
  control.addEventListener("change", () => {
    const form = control.closest("form");
    form?.setAttribute("aria-busy", "true");
    form?.requestSubmit();
  });
});

document.querySelectorAll<HTMLSelectElement>("[data-auto-submit]").forEach((control) => {
  control.addEventListener("change", () => filterForm?.requestSubmit());
});

document.querySelectorAll<HTMLInputElement>("[data-change-submit]").forEach((control) => {
  control.addEventListener("change", () => filterForm?.requestSubmit());
});

const search = document.querySelector<HTMLInputElement>("[data-search-submit]");
let searchTimer: number | undefined;
search?.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => filterForm?.requestSubmit(), 550);
});
filterForm?.addEventListener("submit", () => {
  window.clearTimeout(searchTimer);
  filterForm.setAttribute("aria-busy", "true");
});

const layout = document.querySelector<HTMLElement>("#catalog-layout");
const sidebarToggle = document.querySelector<HTMLButtonElement>(".sidebar-toggle");
const sidebarPreference = "makers-supply-filters-collapsed";

function setSidebar(collapsed: boolean): void {
  if (!layout || !sidebarToggle) return;
  layout.classList.toggle("filters-collapsed", collapsed);
  sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
  sidebarToggle.title = collapsed ? "Expand filters" : "Collapse filters";
  try {
    localStorage.setItem(sidebarPreference, String(collapsed));
  } catch {
    // Storage can be disabled without affecting the control itself.
  }
}

if (layout && sidebarToggle) {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(sidebarPreference) === "true";
  } catch {
    // Use the expanded default when storage is unavailable.
  }
  setSidebar(collapsed);
  sidebarToggle.addEventListener("click", () => {
    setSidebar(!layout.classList.contains("filters-collapsed"));
  });
}

document.querySelectorAll<HTMLTimeElement>("time[data-local-time]").forEach((element) => {
  const value = element.dateTime;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return;
  element.textContent = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
  element.title = value;
});

function initializeImageFallbacks(root: ParentNode = document): void {
  root.querySelectorAll<HTMLImageElement>("img[data-image-fallback]").forEach((image) => {
    if (image.dataset.fallbackReady === "true") return;
    image.dataset.fallbackReady = "true";
    const showFallback = (): void => {
      image.hidden = true;
      const fallback = image.nextElementSibling;
      if (fallback instanceof HTMLElement) fallback.hidden = false;
    };
    image.addEventListener("error", showFallback, { once: true });
    if (image.complete && image.naturalWidth === 0) showFallback();
  });
}

initializeImageFallbacks();

type SelectedProduct = {
  id: string;
  name: string;
  price: string;
  currency: string;
  image: string;
};

const selectionKey = "makers-supply-catalog-selection-v1";
const selectionDrawer = document.querySelector<HTMLElement>("#selection-drawer");
const selectionOpen = document.querySelector<HTMLButtonElement>("#selection-open");
const selectionClose = document.querySelector<HTMLButtonElement>("#selection-close");
const selectionBackdrop = document.querySelector<HTMLButtonElement>("#selection-backdrop");
const selectionItems = document.querySelector<HTMLOListElement>("#selection-items");
const selectionEmpty = document.querySelector<HTMLElement>("[data-selection-empty]");
const selectionForm = document.querySelector<HTMLFormElement>("#catalog-selection-form");
const selectionHidden = document.querySelector<HTMLElement>("#selection-hidden-inputs");
const selectionSubmit = document.querySelector<HTMLButtonElement>("#selection-submit");
const selectionClear = document.querySelector<HTMLButtonElement>("#selection-clear");
const listSelect = document.querySelector<HTMLSelectElement>("#selection-list");
const newListFields = document.querySelector<HTMLElement>("#new-list-fields");
const newListName = document.querySelector<HTMLInputElement>("#selection-list-name");

function readSelection(): Map<string, SelectedProduct> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(selectionKey) ?? "[]");
    if (!Array.isArray(parsed)) return new Map();
    return new Map(
      parsed
        .filter((item): item is SelectedProduct => (
          typeof item === "object" && item !== null &&
          typeof (item as SelectedProduct).id === "string" &&
          typeof (item as SelectedProduct).name === "string"
        ))
        .map((item) => [item.id, item]),
    );
  } catch {
    return new Map();
  }
}

let selectedProducts = readSelection();

function saveSelection(): void {
  try {
    localStorage.setItem(selectionKey, JSON.stringify([...selectedProducts.values()]));
  } catch {
    // The picker continues to work on the current page if storage is unavailable.
  }
}

function productFromCheckbox(checkbox: HTMLInputElement): SelectedProduct {
  return {
    id: checkbox.value,
    name: checkbox.dataset.productName ?? checkbox.value,
    price: checkbox.dataset.productPrice ?? "",
    currency: checkbox.dataset.productCurrency ?? "",
    image: checkbox.dataset.productImage ?? "",
  };
}

function setDrawer(open: boolean): void {
  if (!selectionDrawer || !selectionBackdrop || !selectionOpen) return;
  selectionDrawer.classList.toggle("open", open);
  selectionDrawer.setAttribute("aria-hidden", String(!open));
  selectionDrawer.inert = !open;
  selectionBackdrop.hidden = !open;
  document.body.classList.toggle("selection-drawer-open", open);
  if (open) selectionClose?.focus();
  else selectionOpen.focus();
}

function renderSelection(): void {
  const selected = [...selectedProducts.values()];
  document.querySelectorAll<HTMLElement>("[data-selection-count]").forEach((element) => {
    element.textContent = String(selected.length);
  });
  document.querySelectorAll<HTMLInputElement>("[data-product-select]").forEach((checkbox) => {
    checkbox.checked = selectedProducts.has(checkbox.value);
    checkbox.closest(".product-card")?.classList.toggle("selected", checkbox.checked);
  });
  if (selectionItems) {
    selectionItems.replaceChildren(...selected.map((product) => {
      const item = document.createElement("li");
      if (product.image) {
        const image = document.createElement("img");
        image.src = product.image;
        image.alt = "";
        image.loading = "lazy";
        item.append(image);
      } else {
        const placeholder = document.createElement("span");
        placeholder.className = "selection-thumb-placeholder";
        placeholder.textContent = "◇";
        item.append(placeholder);
      }
      const details = document.createElement("span");
      details.className = "selection-item-details";
      const name = document.createElement("strong");
      name.textContent = product.name;
      const price = document.createElement("small");
      price.textContent = product.price
        ? `${product.price} ${product.currency}`
        : "Price unavailable";
      details.append(name, price);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "selection-remove";
      remove.setAttribute("aria-label", `Remove ${product.name}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        selectedProducts.delete(product.id);
        saveSelection();
        renderSelection();
      });
      item.append(details, remove);
      return item;
    }));
  }
  if (selectionHidden) {
    selectionHidden.replaceChildren(...selected.map((product) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "product_ids";
      input.value = product.id;
      return input;
    }));
  }
  if (selectionEmpty) selectionEmpty.hidden = selected.length > 0;
  if (selectionSubmit) selectionSubmit.disabled = selected.length === 0;
}

function updateNewListFields(): void {
  const creating = listSelect?.value === "__new__";
  if (newListFields) newListFields.hidden = !creating;
  if (newListName) newListName.required = creating;
}

function initializeProductSelectors(root: ParentNode = document): void {
  root.querySelectorAll<HTMLInputElement>("[data-product-select]").forEach((checkbox) => {
    if (checkbox.dataset.selectionReady === "true") return;
    checkbox.dataset.selectionReady = "true";
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedProducts.set(checkbox.value, productFromCheckbox(checkbox));
      else selectedProducts.delete(checkbox.value);
      saveSelection();
      renderSelection();
    });
  });
}

initializeProductSelectors();

selectionOpen?.addEventListener("click", () => setDrawer(true));
selectionClose?.addEventListener("click", () => setDrawer(false));
selectionBackdrop?.addEventListener("click", () => setDrawer(false));
selectionClear?.addEventListener("click", () => {
  selectedProducts.clear();
  saveSelection();
  renderSelection();
});
listSelect?.addEventListener("change", updateNewListFields);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && selectionDrawer?.classList.contains("open")) setDrawer(false);
});

if (document.querySelector("[data-selection-committed]")) {
  selectedProducts.clear();
  saveSelection();
}
selectionForm?.addEventListener("submit", (event) => {
  if (selectedProducts.size === 0) event.preventDefault();
});
updateNewListFields();
renderSelection();

const productGrid = document.querySelector<HTMLElement>(".product-grid");
const pagination = document.querySelector<HTMLElement>("[data-pagination]");
const infiniteStatus = document.querySelector<HTMLElement>("[data-infinite-status]");
const resultsTitle = document.querySelector<HTMLElement>("[data-results-title]");
let loadingNextPage = false;

function updateLoadedResultCount(nextDocument: Document): void {
  if (!resultsTitle || !productGrid) return;
  const nextTitle = nextDocument.querySelector<HTMLElement>("[data-results-title]");
  const total = nextTitle?.dataset.resultsTotal ?? resultsTitle.dataset.resultsTotal ?? "";
  const count = productGrid.querySelectorAll(".product-card").length;
  if (!total || count === 0) return;
  const start = Number(resultsTitle.dataset.resultsStart || "1");
  const end = Math.min(start + count - 1, Number(total));
  resultsTitle.dataset.resultsEnd = String(end);
  resultsTitle.textContent = `Showing ${start}–${end} of ${total}`;
}

async function loadNextPage(): Promise<void> {
  if (!productGrid || !pagination || loadingNextPage) return;
  const nextLink = pagination.querySelector<HTMLAnchorElement>("[data-next-page]");
  if (!nextLink) {
    if (infiniteStatus) infiniteStatus.textContent = "All matching products loaded.";
    return;
  }
  loadingNextPage = true;
  pagination.setAttribute("aria-busy", "true");
  if (infiniteStatus) infiniteStatus.textContent = "Loading more products…";
  try {
    const response = await fetch(nextLink.href, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "catalog-infinite-scroll" },
    });
    if (!response.ok) throw new Error(`Catalog page returned ${response.status}`);
    const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
    const nextGrid = nextDocument.querySelector<HTMLElement>(".product-grid");
    const cards = [...(nextGrid?.querySelectorAll<HTMLElement>(".product-card") ?? [])];
    const knownIds = new Set(
      [...productGrid.querySelectorAll<HTMLInputElement>("[data-product-select]")]
        .map((checkbox) => checkbox.value),
    );
    const newCards = cards.filter((card) => {
      const productId = card.querySelector<HTMLInputElement>("[data-product-select]")?.value;
      return productId !== undefined && !knownIds.has(productId);
    });
    productGrid.append(...newCards);
    initializeImageFallbacks(productGrid);
    initializeProductSelectors(productGrid);
    renderSelection();

    const nextPagination = nextDocument.querySelector<HTMLElement>("[data-pagination]");
    if (nextPagination) pagination.replaceChildren(...nextPagination.childNodes);
    updateLoadedResultCount(nextDocument);
    const hasMore = pagination.querySelector("[data-next-page]") !== null;
    if (infiniteStatus) {
      infiniteStatus.textContent = hasMore
        ? `${newCards.length} more products loaded.`
        : "All matching products loaded.";
    }
  } catch {
    if (infiniteStatus) {
      infiniteStatus.textContent = "Automatic loading failed. Use Next to continue.";
    }
  } finally {
    loadingNextPage = false;
    pagination.removeAttribute("aria-busy");
  }
}

if (pagination && productGrid && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) void loadNextPage();
  }, { rootMargin: "600px 0px" });
  observer.observe(pagination);
}
