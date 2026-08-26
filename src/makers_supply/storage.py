from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from makers_supply.models import Product, RunManifest


def canonical_json(model: Product | RunManifest | dict[str, Any]) -> str:
    payload = model if isinstance(model, dict) else model.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs: dict[str, Any] = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, mode, **kwargs) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


class Catalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.products_dir = root / "data" / "products"
        self.blobs_dir = root / "data" / "blobs" / "sha256"

    def product_path(self, product_id: str) -> Path:
        return self.products_dir / f"{product_id}.json"

    def load_product(self, product_id: str) -> Product:
        return Product.model_validate_json(self.product_path(product_id).read_text("utf-8"))

    def products(self) -> list[Product]:
        return [
            Product.model_validate_json(path.read_text("utf-8"))
            for path in sorted(self.products_dir.glob("*.json"))
        ]

    def write_product(self, product: Product) -> None:
        atomic_write(self.product_path(product.id), canonical_json(product))

    def write_products(self, products: Iterable[Product]) -> None:
        for product in sorted(products, key=lambda item: item.id):
            self.write_product(product)

    def blob_path(self, sha256: str, suffix: str) -> Path:
        normalized_suffix = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
        return self.blobs_dir / sha256[:2] / f"{sha256}{normalized_suffix}"
