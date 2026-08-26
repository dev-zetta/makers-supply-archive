from makers_supply.models import Product


def test_product_json_schema_exposes_public_contract() -> None:
    schema = Product.model_json_schema()
    assert schema["properties"]["schema_version"]["default"] == 4
    assert schema["properties"]["schema_version"]["enum"] == [1, 2, 3, 4]
    assert "offers" in schema["properties"]
    assert "assets" in schema["properties"]
