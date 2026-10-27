#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run portable, fixture-only SDK rootfs customization tests."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_customize_rootfs.py"
SPEC = importlib.util.spec_from_file_location("sdk_customize_rootfs_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CustomizeRootfsTests = MODULE.CustomizeRootfsTests
