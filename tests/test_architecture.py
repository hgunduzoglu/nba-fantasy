"""Mimari kurallar (README §2, §4.1, §9.3) — AST ile import taraması."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "fdo"

#: İlke 1: değer ve matchup paketleri ADP'ye ve botlara erişemez.
ADP_FREE = ("valuation", "matchup")
FORBIDDEN_FOR_ADP_FREE = ("fdo.bots", "fdo.advisor", "fdo.realism", "fdo.ingest.adp_fallback",
                          "fdo.ingest.load", "fdo.ingest.synthetic", "fdo.ui")


def modules(pkg: str | None = None):
    base = SRC / pkg if pkg else SRC
    return sorted(p for p in base.rglob("*.py"))


def module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                base = module_name(path).split(".")
                base = base[: len(base) - node.level + (1 if path.name == "__init__.py" else 0)]
                out.add(".".join([*base, node.module]))
            else:
                out.add(node.module)
                out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


@pytest.mark.parametrize("pkg", ADP_FREE)
def test_valuation_and_matchup_do_not_import_adp_or_bots(pkg):
    for path in modules(pkg):
        bad = {m for m in imports(path) if m.startswith(FORBIDDEN_FOR_ADP_FREE)}
        assert not bad, f"{path.name}: yasak import {sorted(bad)}"


@pytest.mark.parametrize("pkg", ADP_FREE)
def test_valuation_and_matchup_do_not_touch_adp_columns(pkg):
    for path in modules(pkg):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert "adp" not in node.attr.lower(), f"{path.name}: .{node.attr}"
            if isinstance(node, ast.Name):
                assert "adp" not in node.id.lower(), f"{path.name}: {node.id}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                assert "adp" not in node.value.lower(), f"{path.name}: {node.value!r}"


def test_matchup_does_not_read_weights():
    for path in modules("matchup"):
        text = path.read_text(encoding="utf-8")
        assert "fdo.valuation" not in text, path.name
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.arg):
                assert "weight" not in node.arg.lower(), f"{path.name}: {node.arg}"


def test_streamlit_only_in_ui():
    for path in modules():
        if "ui" in path.relative_to(SRC).parts:
            continue
        assert not any(m.split(".")[0] == "streamlit" for m in imports(path)), path


def test_no_cyclic_imports_between_subpackages():
    graph: dict[str, set[str]] = {}
    for path in modules():
        rel = path.relative_to(SRC).parts
        src_pkg = rel[0].removesuffix(".py") if len(rel) > 1 else rel[0].removesuffix(".py")
        for m in imports(path):
            if m.startswith("fdo."):
                dst = m.split(".")[1]
                if dst != src_pkg:
                    graph.setdefault(src_pkg, set()).add(dst)

    seen, stack = set(), []

    def visit(n):
        if n in stack:
            raise AssertionError("Döngü: " + " → ".join(stack[stack.index(n):] + [n]))
        if n in seen:
            return
        stack.append(n)
        for m in sorted(graph.get(n, ())):
            visit(m)
        stack.pop()
        seen.add(n)

    for node in sorted(graph):
        visit(node)
