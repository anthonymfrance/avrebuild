"""Inventory of participant-facing text, extracted from the source itself.

Walks the AST of the modules that draw text, evaluates each string expression
against the real `config` values, and prints every screen string with its
wording, word count and character count. Run it again after editing text to see
how much a screen has shrunk.

    python3 tools/participant_text_inventory.py

Runtime-only values (block names, counts, remaining keys) are shown as
«name» placeholders, so a screen's wording is complete but its numbers are
illustrative.
"""

from __future__ import annotations

import ast
import builtins
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402  (import after sys.path fix)
import practice  # noqa: E402
import screens  # noqa: E402


class Placeholder:
    """Stands in for a value only known at run time."""

    def __init__(self, name):
        self.name = name

    def __getitem__(self, _key):
        return self

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __str__(self):
        return f'«{self.name}»'

    def __format__(self, _spec):
        return str(self)

    def __call__(self, *_args, **_kwargs):
        return self

    def __add__(self, _other):
        return self

    __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __add__

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __float__(self):
        return 0.0

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Placeholder(f'{self.name}.{name}')

    def __eq__(self, other):
        return self is other

    __hash__ = object.__hash__


class TolerantLabels(dict):
    """BLOCK_LABELS, but a placeholder key resolves to that placeholder."""

    def __missing__(self, key):
        return Placeholder(str(key))


NAMESPACE = {name: getattr(config, name) for name in dir(config) if not name.startswith('_')}
NAMESPACE.update({'config': config, 'math': math})
for module in (screens, practice):
    NAMESPACE.update({
        name: value for name, value in vars(module).items()
        if not name.startswith('_') and not callable(value) and not isinstance(value, type)
    })
NAMESPACE.update({
    'BLOCK_LABELS': TolerantLabels(config.BLOCK_LABELS),
    'KEY_NUMBER': practice.KEY_NUMBER,
})

MODULES = ('screens.py', 'practice.py', 'experiment.py')


def _string_value(node):
    """Evaluate a string expression (literal, f-string, or `a + b` of those)."""
    names = {
        child.id for child in ast.walk(node)
        if isinstance(child, ast.Name) and child.id not in NAMESPACE
        and not hasattr(builtins, child.id)
    }
    scope = dict(NAMESPACE)
    scope.update({name: Placeholder(name) for name in names})
    try:
        expression = ast.Expression(body=node)
        ast.fix_missing_locations(expression)
        value = eval(compile(expression, '<inventory>', 'eval'), scope)
    except Exception:
        return None
    return value if isinstance(value, str) and value.strip() else None


def _is_text_target(target):
    return isinstance(target, ast.Attribute) and target.attr == 'text'


def collect(path):
    """Every string drawn to the screen in one module, in source order."""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(_is_text_target(t) for t in node.targets):
            text = _string_value(node.value)
            if text is not None:
                found.append((path.name, node.lineno, 'text.text =', text))
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            text = _string_value(node.value)
            if text is not None and len(text.split()) > 2:
                found.append((path.name, node.lineno, 'returned notice', text))
            continue
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in {'prompt', 'caption'}:
                    text = _string_value(value)
                    if text is not None:
                        found.append((path.name, node.lineno, f'{key.value!r} text', text))
            continue
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, 'attr', None) or getattr(func, 'id', '')
            candidates = []
            if name == 'TextStim':
                candidates = [k.value for k in node.keywords if k.arg == 'text']
            elif name in {'continuation', '_hold'} and node.args:
                candidates = [node.args[-1]]
            elif name == '_frame' and len(node.args) >= 5:
                candidates = [node.args[4]]
            for candidate in candidates:
                text = _string_value(candidate)
                if text is not None:
                    found.append((path.name, node.lineno, f'{name}() message', text))
    return sorted(found, key=lambda row: row[1])


def main():
    rows = []
    for name in MODULES:
        rows.extend(collect(ROOT / name))
    print(f'{"file":<12} {"line":>5}  {"words":>5} {"chars":>5}  label')
    print('-' * 78)
    for module, lineno, label, _text in rows:
        print(f'{module:<12} {lineno:>5}  {len(_text.split()):>5} {len(_text):>5}  {label}')
    print('-' * 78)
    print(f'{len(rows)} text strings; {sum(len(r[3].split()) for r in rows)} words total.')
    if '--full' in sys.argv:
        for module, lineno, _label, text in rows:
            print(f'\n=== {module}:{lineno} ({len(text.split())} words) ===\n{text}')


if __name__ == '__main__':
    main()
