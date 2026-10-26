#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run self-contained fixtures for the native massflash initrd isolation fix."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_massflash_initrd_fix.py"
SPEC = importlib.util.spec_from_file_location("sdk_massflash_initrd_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MassflashInitrdFixTests = MODULE.MassflashInitrdFixTests
