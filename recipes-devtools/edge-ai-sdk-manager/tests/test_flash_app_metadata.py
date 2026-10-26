#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the portable APP metadata fixtures from the recipe checkout."""
import importlib.util
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_flash_app_metadata.py"
SPEC = importlib.util.spec_from_file_location("sdk_flash_app_metadata_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FlashAppMetadataTests = MODULE.FlashAppMetadataTests
