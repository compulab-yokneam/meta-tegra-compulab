#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the self-contained SDK flash-input fixtures from the layer checkout."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_flash_inputs.py"
SPEC = importlib.util.spec_from_file_location("sdk_flash_input_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FlashInputTests = MODULE.FlashInputTests
