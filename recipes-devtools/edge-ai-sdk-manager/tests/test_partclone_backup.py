#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the self-contained, mocked SDK partclone backup fixtures."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / \
    "files/sdk-source/compulab/tests/test_partclone_backup.py"
SPEC = importlib.util.spec_from_file_location("sdk_partclone_backup_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PartcloneBackupTests = MODULE.PartcloneBackupTests
