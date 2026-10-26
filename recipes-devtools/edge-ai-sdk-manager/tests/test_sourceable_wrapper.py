#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the portable SDK wrapper fixtures from the recipe checkout."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_sourceable_wrapper.py"
SPEC = importlib.util.spec_from_file_location("sdk_sourceable_wrapper_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SourceableWrapperTests = MODULE.SourceableWrapperTests
