from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

from makers_supply_web.catalog import catalog_version, product_detail
from makers_supply_web.config import Settings
from makers_supply_web.parts import export_list
from makers_supply_web.security import now

MAX_PROJECT_BYTES = 5 * 1024**3
FOLDERS = {
    "image": "Images",
    "model": "Models",
    "archive": "Archives",
    "document": "Documents",
    "other": "Other",
}


class ProjectExportError(ValueError):
    """An export cannot safely represent the selected local files."""


def _segment(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", value).strip(" .")
    value = value.encode("utf-8")[:200].decode("utf-8", errors="ignore").rstrip(" .") or "file"
    if value.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        value = f"_{value}"
    return value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"


def build_project_archive(
    settings: Settings,
    selected_list: dict[str, Any],
    *,
    include_images: bool = False,
) -> tempfile.SpooledTemporaryFile[bytes]:
    """Build on temporary storage, never writing to the catalog or source assets.

    The caller owns the returned stream. Verification finishes before any response bytes
    are sent, so changed or corrupt source files cannot produce a seemingly valid export.
    """
    root = settings.root.resolve()
    manifest: dict[str, Any] = {
        "format": "makers-supply-project",
        "schema_version": 1,
        "exported_at": now().isoformat(),
        "list_id": selected_list["id"],
        "region": selected_list["region"],
        "include_images": include_images,
        "catalog_schema": catalog_version(settings.catalog_db),
        "products": [],
        "assets": [],
        "metadata_files": [],
    }
    used: set[str] = set()
    total_bytes = 0
    # Ownership is transferred to the streaming response, which closes it on completion.
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024**2, mode="w+b")  # noqa: SIM115

    def unique_path(parent: str, filename: str) -> str:
        candidate = f"{parent}/{filename}"
        suffix = 2
        while unicodedata.normalize("NFC", candidate).casefold() in used:
            candidate = f"{parent}/copy-{suffix}/{filename}"
            suffix += 1
        used.add(unicodedata.normalize("NFC", candidate).casefold())
        return candidate

    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:

            def metadata(path: str, content: str) -> None:
                raw = content.encode("utf-8")
                archive.writestr(path, raw)
                manifest["metadata_files"].append(
                    {
                        "path": path,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "size": len(raw),
                    }
                )

            metadata("parts-list.json", export_list(selected_list, "json")[0])
            metadata("parts-list.csv", export_list(selected_list, "csv")[0])
            metadata(
                "build-progress.json",
                _json(
                    {
                        "list_id": selected_list["id"],
                        "build": selected_list["build"],
                        "items": [
                            {
                                "id": item["id"],
                                "product_id": item["product_id"],
                                "variant_id": item["variant_id"],
                                "quantity": item["quantity"],
                                "completed_quantity": item["completed_quantity"],
                                "progress_updated_at": item["progress_updated_at"],
                            }
                            for item in selected_list["items"]
                        ],
                    }
                ),
            )
            for product_id in sorted({item["product_id"] for item in selected_list["items"]}):
                product = product_detail(settings.catalog_db, product_id)
                if product is None:
                    manifest["products"].append({"id": product_id, "status": "unavailable"})
                    continue
                for asset in product["assets"]:
                    entry = {key: value for key, value in asset.items() if key != "blob_path"}
                    entry.update(
                        {
                            "product_id": product_id,
                            "asset_id": asset["id"],
                            "status": "unavailable",
                            "package_path": None,
                        }
                    )
                    manifest["assets"].append(entry)
                    asset["package_path"] = None
                    blob_path = asset.pop("blob_path", None)
                    if asset["kind"] == "image" and not include_images:
                        entry.update(status="excluded", reason="Images were not selected")
                        continue
                    if asset["rejection_reason"] or not blob_path:
                        entry["reason"] = asset["rejection_reason"] or "No local file recorded"
                        continue
                    relative = Path(str(blob_path))
                    source = (root / relative).resolve()
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or not source.is_relative_to(root)
                        or not source.is_file()
                    ):
                        entry["reason"] = "Local file is unavailable"
                        continue
                    package_path = unique_path(
                        f"assets/{_segment(product_id)}/{FOLDERS.get(asset['kind'], 'Other')}",
                        _segment(str(asset["original_filename"])),
                    )
                    digest = hashlib.sha256()
                    size = 0
                    with (
                        source.open("rb") as stream,
                        archive.open(package_path, "w", force_zip64=True) as target,
                    ):
                        while chunk := stream.read(1024 * 1024):
                            total_bytes += len(chunk)
                            size += len(chunk)
                            if total_bytes > MAX_PROJECT_BYTES:
                                raise ProjectExportError(
                                    "Project files exceed 5 GiB. Export a smaller parts list."
                                )
                            digest.update(chunk)
                            target.write(chunk)
                    actual_hash = digest.hexdigest()
                    if (asset["sha256"] and actual_hash != asset["sha256"]) or (
                        asset["size"] is not None and size != asset["size"]
                    ):
                        raise ProjectExportError(
                            "An archived file failed verification. Restore or refresh the "
                            "catalog files before exporting this project."
                        )
                    entry.update(
                        status="included",
                        package_path=package_path,
                        sha256=actual_hash,
                        size=size,
                        verified_against_catalog=bool(asset["sha256"]),
                    )
                    asset["package_path"] = package_path
                product_path = unique_path("products", f"{_segment(product_id)}.json")
                metadata(product_path, _json(product))
                manifest["products"].append(
                    {
                        "id": product_id,
                        "status": "included",
                        "metadata_path": product_path,
                        "first_seen": product["first_seen"],
                        "last_seen": product["last_seen"],
                    }
                )
            missing = sum(entry["status"] == "unavailable" for entry in manifest["assets"])
            metadata(
                "README.txt",
                (
                    f"{selected_list['name']}\nMaker's Supply project export\n\n"
                    "parts-list.json retains the list, variants, region, quantities, notes, "
                    "current prices and saved price snapshots. parts-list.csv keeps the existing "
                    "CSV format. build-progress.json contains build status and checklist "
                    "progress.\n"
                    "Products retain all archived regional offers and provenance in products/. "
                    "Files are included once per product, including shared and other-variant "
                    "files.\n"
                    f"Unavailable asset records: {missing}. See manifest.json for included, "
                    "excluded and unavailable files, SHA-256 hashes, source URLs and rights "
                    "status.\n"
                    "Prices exclude tax, shipping and currency conversion. Unknown prices are "
                    "not zero. These files retain their original third-party rights; this export "
                    "does not grant redistribution rights. No files were fetched from the "
                    "network.\n"
                ),
            )
            archive.writestr("manifest.json", _json(manifest))
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise
