#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the portable post-generation image fixtures from the recipe checkout."""
import importlib.util
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_deployment_images.py"
SPEC = importlib.util.spec_from_file_location("sdk_deployment_images_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DeploymentImagesTests = MODULE.DeploymentImagesTests
