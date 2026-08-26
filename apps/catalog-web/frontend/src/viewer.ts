import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
import { toCreasedNormals } from "three/examples/jsm/utils/BufferGeometryUtils.js";

type GalleryImage = {
  src: string;
  alt: string;
  name: string;
  variant: string;
  partNumber: string;
  skus: string;
};

const galleryPanel = document.querySelector<HTMLElement>(".gallery");
const productHeading = document.querySelector<HTMLElement>(".product-heading");
const productDescription = document.querySelector<HTMLElement>("[data-product-description]");
const descriptionToggle = document.querySelector<HTMLButtonElement>("[data-description-toggle]");

function descriptionOverflows(): boolean {
  if (!productDescription || !productHeading) return false;
  return productDescription.scrollHeight > productDescription.clientHeight + 2 ||
    productHeading.classList.contains("description-expanded");
}

function refreshDescriptionSummary(): void {
  if (!galleryPanel || !productHeading || !descriptionToggle) return;
  const galleryHeight = galleryPanel.getBoundingClientRect().height;
  if (galleryHeight > 0) {
    productHeading.style.setProperty("--product-summary-height", `${galleryHeight.toFixed(2)}px`);
    productHeading.dataset.summaryReady = "true";
  }
  requestAnimationFrame(() => {
    descriptionToggle.hidden = !descriptionOverflows();
  });
}

descriptionToggle?.addEventListener("click", () => {
  if (!productHeading || !descriptionToggle) return;
  const expanded = productHeading.classList.toggle("description-expanded");
  descriptionToggle.setAttribute("aria-expanded", String(expanded));
  descriptionToggle.textContent = expanded ? "Show less" : "Read more";
  if (!expanded) refreshDescriptionSummary();
});

if (galleryPanel && productHeading && descriptionToggle) {
  new ResizeObserver(refreshDescriptionSummary).observe(galleryPanel);
  window.addEventListener("resize", refreshDescriptionSummary);
  refreshDescriptionSummary();
}

const galleryMain = document.querySelector<HTMLImageElement>("#gallery-main-image");
const galleryOpen = document.querySelector<HTMLButtonElement>("[data-gallery-open]");
const galleryPosition = document.querySelector<HTMLElement>("[data-gallery-position]");
const galleryVariant = document.querySelector<HTMLElement>("[data-gallery-variant-output]");
const galleryPartNumber = document.querySelector<HTMLElement>(
  "[data-gallery-part-number-output]",
);
const gallerySkus = document.querySelector<HTMLElement>("[data-gallery-skus-output]");
const galleryThumbnails = [
  ...document.querySelectorAll<HTMLButtonElement>("[data-gallery-thumbnail]"),
];
const galleryImages: GalleryImage[] = galleryThumbnails.length > 0
  ? galleryThumbnails.map((thumbnail) => ({
      src: thumbnail.dataset.gallerySrc ?? "",
      alt: thumbnail.dataset.galleryAlt ?? "Product image",
      name: thumbnail.dataset.galleryName ?? "Product image",
      variant: thumbnail.dataset.galleryVariant ?? "Product overview image",
      partNumber: thumbnail.dataset.galleryPartNumber ?? "Not variant-specific",
      skus: thumbnail.dataset.gallerySkus ?? "Not variant-specific",
    }))
  : galleryMain
    ? [{
        src: galleryMain.src,
        alt: galleryMain.alt,
        name: galleryMain.dataset.galleryName ?? galleryMain.alt,
        variant: galleryMain.dataset.galleryVariant ?? "Product overview image",
        partNumber: galleryMain.dataset.galleryPartNumber ?? "Not variant-specific",
        skus: galleryMain.dataset.gallerySkus ?? "Not variant-specific",
      }]
    : [];

const imageDialog = document.querySelector<HTMLDialogElement>("#image-dialog");
const imageDialogImage = document.querySelector<HTMLImageElement>("#image-dialog-image");
const imageDialogTitle = document.querySelector<HTMLElement>("#image-dialog-title");
const imageViewport = document.querySelector<HTMLElement>("[data-image-viewport]");
const zoomLevel = document.querySelector<HTMLButtonElement>("[data-image-zoom-reset]");
let galleryIndex = 0;
let imageScale = 1;
let imageX = 0;
let imageY = 0;

function renderImageTransform(): void {
  if (!imageDialogImage) return;
  imageDialogImage.style.transform = `translate(${imageX}px, ${imageY}px) scale(${imageScale})`;
  if (zoomLevel) zoomLevel.textContent = `${Math.round(imageScale * 100)}%`;
}

function setImageZoom(scale: number): void {
  imageScale = Math.min(5, Math.max(1, scale));
  if (imageScale === 1) {
    imageX = 0;
    imageY = 0;
  }
  renderImageTransform();
}

function showGalleryImage(index: number): void {
  if (galleryImages.length === 0) return;
  galleryIndex = (index + galleryImages.length) % galleryImages.length;
  const selected = galleryImages[galleryIndex];
  if (galleryMain) {
    galleryMain.hidden = false;
    galleryMain.src = selected.src;
    galleryMain.alt = selected.alt;
    const fallback = galleryMain.nextElementSibling;
    if (fallback instanceof HTMLElement) fallback.hidden = true;
  }
  if (galleryPosition) galleryPosition.textContent = String(galleryIndex + 1);
  if (galleryVariant) galleryVariant.textContent = selected.variant;
  if (galleryPartNumber) galleryPartNumber.textContent = selected.partNumber;
  if (gallerySkus) gallerySkus.textContent = selected.skus;
  galleryThumbnails.forEach((thumbnail, thumbnailIndex) => {
    const active = thumbnailIndex === galleryIndex;
    thumbnail.classList.toggle("active", active);
    thumbnail.setAttribute("aria-current", String(active));
    if (active) thumbnail.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
  if (imageDialog?.open && imageDialogImage && imageDialogTitle) {
    imageDialogImage.src = selected.src;
    imageDialogImage.alt = selected.alt;
    imageDialogTitle.textContent = selected.name;
    setImageZoom(1);
  }
}

function openImageDialog(): void {
  if (!imageDialog || !imageDialogImage || !imageDialogTitle || galleryImages.length === 0) return;
  const selected = galleryImages[galleryIndex];
  imageDialogImage.src = selected.src;
  imageDialogImage.alt = selected.alt;
  imageDialogTitle.textContent = selected.name;
  setImageZoom(1);
  imageDialog.showModal();
}

galleryThumbnails.forEach((thumbnail) => {
  thumbnail.addEventListener("click", () => {
    showGalleryImage(Number(thumbnail.dataset.galleryIndex ?? 0));
  });
});
galleryOpen?.addEventListener("click", openImageDialog);
document.querySelector<HTMLButtonElement>("[data-gallery-previous]")?.addEventListener(
  "click", () => showGalleryImage(galleryIndex - 1),
);
document.querySelector<HTMLButtonElement>("[data-gallery-next]")?.addEventListener(
  "click", () => showGalleryImage(galleryIndex + 1),
);
document.querySelector<HTMLButtonElement>("[data-lightbox-previous]")?.addEventListener(
  "click", () => showGalleryImage(galleryIndex - 1),
);
document.querySelector<HTMLButtonElement>("[data-lightbox-next]")?.addEventListener(
  "click", () => showGalleryImage(galleryIndex + 1),
);
document.querySelector<HTMLButtonElement>("[data-image-zoom-in]")?.addEventListener(
  "click", () => setImageZoom(imageScale + 0.25),
);
document.querySelector<HTMLButtonElement>("[data-image-zoom-out]")?.addEventListener(
  "click", () => setImageZoom(imageScale - 0.25),
);
zoomLevel?.addEventListener("click", () => setImageZoom(1));
imageViewport?.addEventListener("wheel", (event) => {
  event.preventDefault();
  setImageZoom(imageScale + (event.deltaY < 0 ? 0.2 : -0.2));
}, { passive: false });
imageViewport?.addEventListener("dblclick", () => setImageZoom(imageScale === 1 ? 2 : 1));

let dragStart: { pointerX: number; pointerY: number; imageX: number; imageY: number } | null = null;
imageViewport?.addEventListener("pointerdown", (event) => {
  if (imageScale === 1) return;
  imageViewport.setPointerCapture(event.pointerId);
  imageViewport.classList.add("dragging");
  dragStart = { pointerX: event.clientX, pointerY: event.clientY, imageX, imageY };
});
imageViewport?.addEventListener("pointermove", (event) => {
  if (!dragStart) return;
  imageX = dragStart.imageX + event.clientX - dragStart.pointerX;
  imageY = dragStart.imageY + event.clientY - dragStart.pointerY;
  renderImageTransform();
});
function endImageDrag(): void {
  dragStart = null;
  imageViewport?.classList.remove("dragging");
}
imageViewport?.addEventListener("pointerup", endImageDrag);
imageViewport?.addEventListener("pointercancel", endImageDrag);
imageDialog?.addEventListener("close", () => setImageZoom(1));
document.addEventListener("keydown", (event) => {
  if (!imageDialog?.open) return;
  if (event.key === "ArrowLeft") showGalleryImage(galleryIndex - 1);
  if (event.key === "ArrowRight") showGalleryImage(galleryIndex + 1);
  if (event.key === "+" || event.key === "=") setImageZoom(imageScale + 0.25);
  if (event.key === "-") setImageZoom(imageScale - 0.25);
  if (event.key === "0") setImageZoom(1);
});

const dialog = document.querySelector<HTMLDialogElement>("#model-dialog");
const host = document.querySelector<HTMLDivElement>("#model-viewer");
const title = document.querySelector<HTMLElement>("#model-title");

type SurfaceMaterial = THREE.Material & {
  alphaMap?: THREE.Texture | null;
  bumpMap?: THREE.Texture | null;
  clearcoat?: number;
  clearcoatRoughness?: number;
  color?: THREE.Color;
  emissive?: THREE.Color;
  emissiveIntensity?: number;
  emissiveMap?: THREE.Texture | null;
  map?: THREE.Texture | null;
  metalness?: number;
  metalnessMap?: THREE.Texture | null;
  normalMap?: THREE.Texture | null;
  roughness?: number;
  roughnessMap?: THREE.Texture | null;
  vertexColors?: boolean;
};

type ColorStlGeometry = THREE.BufferGeometry & {
  alpha?: number;
  hasColors?: boolean;
};

const MODEL_COLOR = new THREE.Color(0x08796d);
const CREASE_ANGLE = THREE.MathUtils.degToRad(42);

function physicalMaterial(source: THREE.Material): THREE.MeshPhysicalMaterial {
  const input = source as SurfaceMaterial;
  const hasMap = input.map instanceof THREE.Texture;
  const hasVertexColors = input.vertexColors === true;
  const usesLoaderDefault = source.name === THREE.Loader.DEFAULT_MATERIAL_NAME;
  const color = usesLoaderDefault && !hasMap && !hasVertexColors
    ? MODEL_COLOR.clone()
    : input.color?.clone() ?? MODEL_COLOR.clone();
  const material = new THREE.MeshPhysicalMaterial({
    alphaMap: input.alphaMap ?? null,
    alphaTest: source.alphaTest,
    bumpMap: input.bumpMap ?? null,
    clearcoat: input.clearcoat ?? (hasMap ? 0.14 : 0.42),
    clearcoatRoughness: input.clearcoatRoughness ?? 0.22,
    color,
    depthTest: source.depthTest,
    depthWrite: source.depthWrite,
    emissive: input.emissive?.clone() ?? new THREE.Color(0x000000),
    emissiveIntensity: input.emissiveIntensity ?? 1,
    emissiveMap: input.emissiveMap ?? null,
    flatShading: false,
    map: input.map ?? null,
    metalness: input.metalness ?? 0.14,
    metalnessMap: input.metalnessMap ?? null,
    name: source.name,
    normalMap: input.normalMap ?? null,
    opacity: source.opacity,
    roughness: input.roughness ?? (hasMap ? 0.46 : 0.25),
    roughnessMap: input.roughnessMap ?? null,
    side: source.side,
    transparent: source.transparent || source.opacity < 1,
    vertexColors: hasVertexColors,
  });
  material.polygonOffset = source.polygonOffset;
  material.polygonOffsetFactor = source.polygonOffsetFactor;
  material.polygonOffsetUnits = source.polygonOffsetUnits;
  return material;
}

function prepareObject(object: THREE.Object3D, renderer: THREE.WebGLRenderer): void {
  const maximumAnisotropy = renderer.capabilities.getMaxAnisotropy();
  object.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return;
    const previousGeometry = child.geometry;
    const geometry = toCreasedNormals(previousGeometry, CREASE_ANGLE);
    if (geometry !== previousGeometry) previousGeometry.dispose();
    child.geometry = geometry;
    child.castShadow = true;
    child.receiveShadow = true;
    const previousMaterials = Array.isArray(child.material)
      ? child.material
      : [child.material];
    const materials = previousMaterials.map((material) => physicalMaterial(material));
    child.material = Array.isArray(child.material) ? materials : materials[0];
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (value instanceof THREE.Texture) value.anisotropy = maximumAnisotropy;
      }
    }
    previousMaterials.forEach((material) => material.dispose());
  });
}

function disposeObject(object: THREE.Object3D): void {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  object.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return;
    geometries.add(child.geometry);
    const childMaterials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of childMaterials) {
      materials.add(material);
      for (const value of Object.values(material)) {
        if (value instanceof THREE.Texture) textures.add(value);
      }
    }
  });
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
  textures.forEach((texture) => texture.dispose());
}

function addStudioLights(
  scene: THREE.Scene,
  modelSize: number,
  modelHeight: number,
): void {
  const hemisphere = new THREE.HemisphereLight(0xeaf7ff, 0x53615c, 0.72);
  scene.add(hemisphere);

  const key = new THREE.DirectionalLight(0xfff8ed, 2.3);
  key.position.set(modelSize * 1.8, modelSize * 2.4, modelSize * 2.2);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -modelSize;
  key.shadow.camera.right = modelSize;
  key.shadow.camera.top = modelSize;
  key.shadow.camera.bottom = -modelSize;
  key.shadow.camera.near = Math.max(modelSize * 0.01, 0.001);
  key.shadow.camera.far = modelSize * 8;
  key.shadow.bias = -0.0002;
  scene.add(key, key.target);

  const fill = new THREE.DirectionalLight(0xaedcff, 0.72);
  fill.position.set(-modelSize * 2, modelSize * 0.8, modelSize * 1.4);
  scene.add(fill);

  const rim = new THREE.DirectionalLight(0xd7fff2, 1.45);
  rim.position.set(modelSize * 0.4, modelSize * 1.2, -modelSize * 2.4);
  scene.add(rim);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(modelSize * 5, modelSize * 5),
    new THREE.ShadowMaterial({ color: 0x153548, opacity: 0.16 }),
  );
  floor.position.y = -(modelHeight / 2) - modelSize * 0.045;
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
}

async function preview(url: string, name: string): Promise<void> {
  if (!dialog || !host || !title) return;
  host.replaceChildren();
  host.setAttribute("aria-busy", "true");
  title.textContent = name;
  dialog.showModal();
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, host.clientWidth / host.clientHeight, 0.1, 10000);
  const renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(host.clientWidth, host.clientHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.96;
  host.append(renderer.domElement);

  const room = new RoomEnvironment();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environment = pmrem.fromScene(room, 0.035).texture;
  scene.environment = environment;
  scene.environmentIntensity = 0.82;
  room.dispose();
  pmrem.dispose();

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.screenSpacePanning = true;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.65;
  renderer.domElement.addEventListener("pointerdown", () => {
    controls.autoRotate = false;
  }, { once: true });

  let active = true;
  let object: THREE.Object3D | null = null;
  const resize = () => {
    camera.aspect = host.clientWidth / host.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(host.clientWidth, host.clientHeight);
  };
  const cleanup = () => {
    if (!active) return;
    active = false;
    renderer.setAnimationLoop(null);
    controls.dispose();
    removeEventListener("resize", resize);
    disposeObject(scene);
    environment.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    host.removeAttribute("aria-busy");
  };
  dialog.addEventListener("close", cleanup, { once: true });

  try {
    const extension = name.split(".").pop()?.toLowerCase();
    if (extension === "stl") {
      const geometry = await new STLLoader().loadAsync(url) as ColorStlGeometry;
      const hasColors = geometry.hasColors === true || geometry.hasAttribute("color");
      object = new THREE.Mesh(
        geometry,
        new THREE.MeshPhysicalMaterial({
          clearcoat: 0.46,
          clearcoatRoughness: 0.2,
          color: hasColors ? 0xffffff : MODEL_COLOR,
          metalness: 0.18,
          opacity: geometry.alpha ?? 1,
          roughness: 0.24,
          transparent: (geometry.alpha ?? 1) < 1,
          vertexColors: hasColors,
        }),
      );
    } else if (extension === "3mf") {
      object = await new ThreeMFLoader().loadAsync(url);
    } else {
      throw new Error("Unsupported preview format");
    }
  } catch (error) {
    cleanup();
    throw error;
  }
  if (!active) {
    disposeObject(object);
    return;
  }
  prepareObject(object, renderer);
  scene.add(object);
  const bounds = new THREE.Box3().setFromObject(object);
  const center = bounds.getCenter(new THREE.Vector3());
  const dimensions = bounds.getSize(new THREE.Vector3());
  const size = Math.max(dimensions.x, dimensions.y, dimensions.z, 0.001);
  object.position.sub(center);
  addStudioLights(scene, size, dimensions.y);

  const verticalDistance = size / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
  const distance = Math.max(verticalDistance, verticalDistance / camera.aspect) * 1.78;
  camera.position.copy(
    new THREE.Vector3(0.9, 0.65, 1).normalize().multiplyScalar(distance),
  );
  camera.near = Math.max(size / 1000, 0.01);
  camera.far = Math.max(size * 100, 10);
  camera.updateProjectionMatrix();
  controls.target.set(0, 0, 0);
  controls.minDistance = size * 0.35;
  controls.maxDistance = size * 12;
  controls.update();
  addEventListener("resize", resize, { passive: true });
  host.setAttribute("aria-busy", "false");
  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(scene, camera);
  });
}

document.querySelectorAll<HTMLButtonElement>(".preview-button").forEach((button) => {
  button.addEventListener("click", () => {
    void preview(button.dataset.modelUrl ?? "", button.dataset.modelName ?? "Model").catch((error: unknown) => {
      if (host) host.textContent = error instanceof Error ? error.message : "Preview failed";
    });
  });
});

const listSelector = document.querySelector<HTMLSelectElement>("#target-list");
const variantSelector = document.querySelector<HTMLSelectElement>("#target-variant");
const addForm = document.querySelector<HTMLFormElement>("#add-to-list");
function selectList(): void {
  if (!listSelector || !variantSelector || !addForm) return;
  const selected = listSelector.selectedOptions[0];
  const region = selected?.dataset.region;
  addForm.action = `/lists/${listSelector.value}/items`;
  for (const option of variantSelector.options) {
    option.hidden = Boolean(option.dataset.region && option.dataset.region !== region);
  }
  if (variantSelector.selectedOptions[0]?.hidden) variantSelector.value = "";
}
listSelector?.addEventListener("change", selectList);
selectList();
