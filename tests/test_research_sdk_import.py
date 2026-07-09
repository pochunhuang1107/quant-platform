import importlib
from types import ModuleType


def test_research_sdk_imports() -> None:
    module = importlib.import_module("research_sdk")

    assert isinstance(module, ModuleType)
