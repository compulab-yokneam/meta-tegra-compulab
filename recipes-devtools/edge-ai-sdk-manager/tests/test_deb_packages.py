#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Discover native add-on package builder fixtures."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_deb_packages.py"
SPEC = importlib.util.spec_from_file_location("sdk_deb_package_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DebPackageTests = MODULE.DebPackageTests
