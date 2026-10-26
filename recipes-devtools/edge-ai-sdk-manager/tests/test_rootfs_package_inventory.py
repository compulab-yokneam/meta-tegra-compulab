#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the self-contained Ubuntu addon package inventory fixtures."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_rootfs_package_inventory.py"
SPEC = importlib.util.spec_from_file_location(
    "sdk_package_inventory_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RootfsPackageInventoryTests = MODULE.RootfsPackageInventoryTests
