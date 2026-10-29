#!/usr/bin/env python3
"""The plugin's Python scripts stay runnable on Python 3.8."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = sorted((ROOT / 'scripts').glob('*.py'))
# Library calls added after Python 3.8.
NEWER_APIS = re.compile(r'\.(?:removeprefix|removesuffix|is_relative_to)\(')
GENERIC_BUILTINS = {'list', 'dict', 'tuple', 'set', 'frozenset', 'type'}
# Shared with the Claude hooks and imported by sf_context; its evaluated PEP 585
# annotations already set the plugin's runtime floor at Python 3.9.
RUNTIME_ANNOTATIONS_EXEMPT = {'nudge_rules.py'}


def _newer_annotation(node):
    """A PEP 585/604 annotation, which Python 3.8 evaluates and rejects."""
    for child in ast.walk(node):
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.BitOr):
            return True
        if (isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name)
                and child.value.id in GENERIC_BUILTINS):
            return True
    return False


def _annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
                        arguments.vararg, arguments.kwarg]:
                if arg is not None and arg.annotation is not None:
                    yield arg.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


class Python38CompatibilityTests(unittest.TestCase):
    def test_scripts_parse_as_python_38_and_avoid_newer_apis(self):
        self.assertTrue(SCRIPTS)
        for script in SCRIPTS:
            with self.subTest(script=script.name):
                source = script.read_text(encoding='utf-8')
                tree = ast.parse(source, filename=str(script), feature_version=(3, 8))
                self.assertIsNone(NEWER_APIS.search(source))
                postponed = any(isinstance(node, ast.ImportFrom) and node.module == '__future__'
                                and any(alias.name == 'annotations' for alias in node.names)
                                for node in tree.body)
                if not postponed and script.name not in RUNTIME_ANNOTATIONS_EXEMPT:
                    self.assertFalse(any(_newer_annotation(a) for a in _annotations(tree)))


if __name__ == '__main__':
    unittest.main()
