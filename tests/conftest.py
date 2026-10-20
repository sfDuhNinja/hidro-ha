"""Încarcă modulele pure ale integrării fără a importa Home Assistant."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "hidro_ro"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PKG = "hidro_pure"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(COMPONENT)]
    sys.modules[_PKG] = pkg
    for name in ("const", "parsing"):
        spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", COMPONENT / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PKG}.{name}"] = module
        spec.loader.exec_module(module)


@pytest.fixture(scope="session")
def parsing():
    return sys.modules[f"{_PKG}.parsing"]


@pytest.fixture(scope="session")
def fx():
    def load(name: str):
        return json.loads((FIXTURES / f"{name}.json").read_text())["data"]
    return load
