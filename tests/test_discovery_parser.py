from pathlib import Path

import httpx
import pytest

from makers_supply.config import STORES
from makers_supply.discovery import discover_products, extract_series_id
from makers_supply.http import ArchiveHttpClient
from makers_supply.models import AssetKind, Region
from makers_supply.parser import parse_product_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_series_id() -> None:
    assert extract_series_id((FIXTURES / "collection.html").read_text()) == "284768927880"


def test_discover_products_uses_regional_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/collections/makers-supply":
            return httpx.Response(200, text=(FIXTURES / "collection.html").read_text())
        assert request.headers["X-BBL-STORE-REGION"] == "US"
        return httpx.Response(
            200,
            json={
                "data": {
                    "productGlobalSearchVOIPage": {
                        "records": [
                            {
                                "id": "123",
                                "seoCode": "power-board",
                                "name": "Power board",
                                "currency": "USD",
                                "lowerPrice": 5.29,
                                "mediaFiles": ["https://example.com/image.png"],
                            }
                        ],
                        "total": "1",
                    }
                }
            },
        )

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        products = discover_products(client, STORES[Region.US])
    assert products[0].handle == "power-board"
    assert products[0].price == "5.29"


def test_parse_product_page() -> None:
    product = parse_product_page((FIXTURES / "product.html").read_text())
    assert product.name == "Power Distribution Board"
    assert product.part_numbers == ("IA005",)
    assert product.variants[0].variant_id == "98765"
    assert product.variants[0].available is True
    assert product.specifications == {"Input voltage": "5 V"}
    assert product.box_contents[0].name == "Board"
    assert {asset.kind for asset in product.assets} == {AssetKind.IMAGE, AssetKind.MODEL}
    assert any(asset.url.endswith("board-2.png") for asset in product.assets)
    assert product.related_links[0].kind == "makerworld"
    assert len(product.source_tables) == 2
    assert product.source_tables[0].rows == [["Input voltage", "5 V"]]


def test_parse_product_page_ignores_malformed_related_link() -> None:
    html = (
        (FIXTURES / "product.html")
        .read_text()
        .replace("https://makerworld.com/en/models/123", "notes makerworld.com but not a URL")
    )
    assert parse_product_page(html).related_links == ()


def test_parse_product_page_names_generic_makerworld_links_from_url() -> None:
    html = (
        (FIXTURES / "product.html")
        .read_text()
        .replace(
            "https://makerworld.com/en/models/123\">Example model",
            "https://makerworld.com/en/models/1395994-cyberbrick-official-forklift\">MakerWorld",
        )
    )

    product = parse_product_page(html)

    assert product.related_links[0].title == "CyberBrick Official Forklift"


def test_parse_product_page_uses_linked_image_alt_for_numeric_makerworld_url() -> None:
    html = (
        (FIXTURES / "product.html")
        .read_text()
        .replace(
            "https://makerworld.com/en/models/123\">Example model",
            'https://makerworld.com/en/models/2857279\"><img alt="Forklift">',
        )
    )

    product = parse_product_page(html)

    assert product.related_links[0].title == "Forklift"


def test_parse_product_page_does_not_replace_model_name_with_yes_link() -> None:
    html = (
        (FIXTURES / "product.html")
        .read_text()
        .replace(
            '<a href="https://makerworld.com/en/models/123">Example model</a>',
            '<a href="https://makerworld.com/en/models/797259">Bubble Blaster</a>'
            '<a href="https://makerworld.com/en/models/797259">YES</a>',
        )
    )

    product = parse_product_page(html)

    assert product.related_links[0].title == "Bubble Blaster"


def test_parse_product_page_separates_overview_and_td_box_table() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"Product","name":"Robot Kit","description":"Fallback",
     "sku":"ZH001","offers":{"url":"https://us.store.bambulab.com/products/robot-kit",
     "priceCurrency":"USD","price":"10"}}
    </script>
    <div class="pct">
      <h2>Overview</h2><p>Build a <strong>small robot</strong>.</p>
      <h2>In The Box</h2><table>
        <tr><td><strong>Item</strong></td><td><strong>Qty</strong></td></tr>
        <tr><td><a href="../products/power-board">Power board</a></td><td>2 pcs</td></tr>
      </table>
    </div>
    """
    product = parse_product_page(html)

    assert product.description_text == "Build a small robot."
    assert [block.kind for block in product.description_blocks] == ["heading", "paragraph"]
    assert product.specifications == {}
    assert product.box_contents[0].name == "Power board"
    assert product.box_contents[0].quantity == "2 pcs"
    assert str(product.box_contents[0].source_url) == (
        "https://us.store.bambulab.com/products/power-board"
    )
    assert product.source_tables[0].headers == ["Item", "Qty"]


def test_parse_product_page_extracts_variant_quantity_package_matrix() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"Product","name":"Robot Kit","sku":"ZK003",
     "offers":{"url":"https://us.store.bambulab.com/products/robot-kit",
     "priceCurrency":"USD","price":"55.99"}}
    </script>
    <div class="pct"><h2>In The Box</h2><table>
      <thead><tr><td>No.</td><td>Item Name</td><td>Ultimate Kit</td>
        <td>Beginner Kit</td></tr></thead>
      <tbody>
        <tr><td>1</td><td><a href="../products/power-board">Power board</a></td>
            <td>4 pcs</td><td>2 pcs</td></tr>
        <tr><td>2</td><td>Remote</td><td>2 pcs</td><td>-</td></tr>
      </tbody>
    </table></div>
    """

    product = parse_product_page(html)

    assert [item.name for item in product.box_contents] == ["Power board", "Remote"]
    assert product.box_contents[0].quantity is None
    assert [
        (item.variant, item.quantity) for item in product.box_contents[0].variant_quantities
    ] == [("Ultimate Kit", "4 pcs"), ("Beginner Kit", "2 pcs")]
    assert str(product.box_contents[0].source_url) == (
        "https://us.store.bambulab.com/products/power-board"
    )


def test_parse_product_page_combines_overview_and_horizontal_specification_sections() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"Product","name":"Micro Motor","sku":"LA024",
     "offers":{"url":"https://eu.store.bambulab.com/products/micro-motor?id=1",
     "priceCurrency":"EUR","price":"4.76"}}
    </script>
    <div class="pct"><h2>Product Specifications</h2><table>
      <thead><tr><td>Product ID</td><td>Rated Voltage</td><td>Direction</td></tr></thead>
      <tbody><tr><td>LA024</td><td>DC 8.0V</td><td>CCW</td></tr></tbody>
    </table></div>
    <div class="pct"><h2>Introduction</h2>
      <p>A compact motor for space-constrained projects.</p>
    </div>
    """

    product = parse_product_page(html)

    assert product.description_text == "A compact motor for space-constrained projects."
    assert product.specifications == {
        "Product ID": "LA024",
        "Rated Voltage": "DC 8.0V",
        "Direction": "CCW",
    }
    assert product.source_tables[0].caption == "Product Specifications"
    assert str(product.source_tables[0].provenance.source_url) == (
        "https://eu.store.bambulab.com/products/micro-motor?id=1"
    )


def test_parse_product_page_finds_top_level_cad_and_pdf_downloads() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"Product","name":"Micro Motor","sku":"LA024",
     "offers":{"url":"https://us.store.bambulab.com/products/micro-motor",
     "priceCurrency":"USD","price":"4.39"}}
    </script>
    <p class="pct_downloadContent">
      <a href="https://store.bblcdn.com/motor.pdf">Specification</a>
      <a href="https://store.bblcdn.com/motor.zip">3D Model</a>
    </p>
    <div class="pct"><h2>Introduction</h2><p>A compact motor.</p></div>
    """
    product = parse_product_page(html)

    downloads = {asset.filename: asset.kind for asset in product.assets}
    assert downloads == {
        "motor.pdf": AssetKind.DOCUMENT,
        "motor.zip": AssetKind.ARCHIVE,
    }


@pytest.mark.parametrize(
    "page",
    [None, {}, {"records": []}, {"total": 0}, {"records": None, "total": 0},
     {"records": [], "total": -1}, {"records": [], "total": True},
     {"records": [None], "total": 1}, {"records": [{}], "total": 0}],
)
def test_incomplete_catalog_api_responses_are_not_successful_empty_scans(
    page: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/collections/makers-supply":
            return httpx.Response(200, text=(FIXTURES / "collection.html").read_text())
        return httpx.Response(200, json={"data": {"productGlobalSearchVOIPage": page}})

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="catalog API"):
            discover_products(client, STORES[Region.US])
