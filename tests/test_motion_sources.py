"""Motion parts retain distinct, human-readable supplier identities."""

from makersfridge.suppliers import SUPPLIERS


def test_motion_supplier_identities() -> None:
    assert SUPPLIERS["openbuilds"] == "OpenBuilds"
