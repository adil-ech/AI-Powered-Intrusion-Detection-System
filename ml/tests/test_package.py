"""Machine-learning package foundation tests."""

import ids_ml


def test_package_exposes_version() -> None:
    assert ids_ml.__version__ == "0.1.0"
