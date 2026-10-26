#!/usr/bin/env python3
"""Discover the unprivileged maintained runtime/provisioning fixtures."""
import importlib.util
from pathlib import Path

FILES = Path(__file__).resolve().parents[1] / "files"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ProvisionRuntimeTests = load("runtime_provision_fixtures", FILES / "test_provision_runtime.py").ProvisionRuntimeTests
RuntimeBundleTests = load("runtime_bundle_fixtures", FILES / "runtime/tests/test_bundle.py").RuntimeBundleTests
