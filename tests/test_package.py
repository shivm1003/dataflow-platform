"""Package-level smoke tests."""

import dataflow_platform


def test_package_version() -> None:
    assert dataflow_platform.__version__ == "0.1.0"
