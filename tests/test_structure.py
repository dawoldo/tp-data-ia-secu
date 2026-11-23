"""The layers only depend on the ones before them."""

import ast

import pytest
from common import ROOT

ALLOWED = {
    "paths": set(),
    "bronze": {"paths"},
    "silver": {"paths"},  # reads the bronze files, not the bronze code
    "warehouse": {"paths", "bronze", "silver"},
    "evaluation": {"paths", "bronze", "silver"},
}


def imported(path, relative=False):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and bool(node.level) == relative:
            yield from [node.module.split(".")[0]] if node.module else (a.name for a in node.names)


@pytest.mark.parametrize("layer", ALLOWED)
def test_layer_dependencies(layer):
    files = [ROOT / "paths.py"] if layer == "paths" else (ROOT / layer).rglob("*.py")
    for path in files:
        others = set(imported(path)) & (ALLOWED.keys() - {layer})
        assert others <= ALLOWED[layer], f"{path} imports {others - ALLOWED[layer]}"


def test_bronze_stages_do_not_know_the_pipeline():
    for path in (ROOT / "bronze").glob("*/*.py"):
        assert "pipeline" not in set(imported(path, relative=True)), path
