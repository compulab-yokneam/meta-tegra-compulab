#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the native package BSP policy fixtures from the recipe checkout."""
import importlib.util
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_package_bsp_policy.py"
SPEC = importlib.util.spec_from_file_location("sdk_package_bsp_policy", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PackageBspPolicyTests = MODULE.PackageBspPolicyTests
