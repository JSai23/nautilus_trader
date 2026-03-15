"""Shared utilities for runner modules."""

from __future__ import annotations

import importlib


def import_strategy_class(strategy_path: str):
    """Import a strategy class from a dotted path like 'module.submod:ClassName'."""
    module_path, class_name = strategy_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
