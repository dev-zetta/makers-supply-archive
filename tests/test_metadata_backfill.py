import hashlib
from datetime import UTC, datetime
from pathlib import Path

from makers_supply.metadata_backfill import CachedMetadataBackfill
from makers_supply.models import Product, Region, SourceAlias
from makers_supply.storage import Catalog


def test_cached_metadata_backfill_recovers_sections_and_is_idempotent(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"models":{"label":"Maker\'s Supply Models"},'
        '"uncategorized":{"label":"Uncategorized"}},'
        '"rules":[{"pattern":"zh\\\\d{3}","category":"models"}]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    product = Product(
        id="zh159-capsule-lamp",
        name="Capsule Lamp",
        aliases=[SourceAlias(region=Region.EU, handle="capsule-lamp")],
        first_seen=timestamp,
        last_seen=timestamp,
    )
    catalog = Catalog(tmp_path)
    catalog.write_product(product)
    pages = tmp_path / ".staging/pages"
    pages.mkdir(parents=True)
    key = hashlib.sha256(b"eu:capsule-lamp").hexdigest()
    (pages / f"{key}.html").write_text(
        """
        <script type="application/ld+json">
        {"@type":"Product","name":"Capsule Lamp","sku":"ZH159",
         "offers":{"url":"https://eu.store.bambulab.com/products/capsule-lamp?id=1",
         "priceCurrency":"EUR","price":"40"}}
        </script>
        <div class="pct"><h2>Overview</h2><p>A rotating project lamp.</p></div>
        <div class="pct"><h2>Product Specifications</h2><table>
          <thead><tr><td>Product ID</td><td>Voltage</td></tr></thead>
          <tbody><tr><td>ZH159</td><td>5 V</td></tr></tbody>
        </table></div>
        """,
        encoding="utf-8",
    )

    preview = CachedMetadataBackfill(tmp_path).run(promote=False)
    assert preview.products_updated == 1
    assert not catalog.load_product(product.id).description_text

    result = CachedMetadataBackfill(tmp_path).run()
    updated = catalog.load_product(product.id)
    assert result.descriptions_recovered == 1
    assert result.specifications_recovered == 1
    assert updated.description_text == "A rotating project lamp."
    assert updated.specifications == {"Product ID": "ZH159", "Voltage": "5 V"}
    assert updated.categories == ["Maker's Supply Models"]
    assert CachedMetadataBackfill(tmp_path).run().products_updated == 0
