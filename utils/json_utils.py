"""
json_utils.py — Safe JSON I/O and dict manipulation helpers.

All functions are designed to be silent on error, returning sentinel values
(None / False) instead of raising exceptions. This matches the enrichment
pipeline's defensive data-handling pattern.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


def safe_load(path_or_str: Union[str, Path]) -> Optional[Union[dict, list]]:
    """
    Load JSON from a file path or a raw JSON string.

    Tries file-path first: if the value is (or points to) a readable file,
    it is read and parsed. If the file does not exist, the value is treated
    as a JSON string and parsed directly.

    Returns:
        Parsed dict or list, or None on any error.
    """
    if path_or_str is None:
        return None

    # Normalise to string for path resolution
    as_str = str(path_or_str).strip()

    # Try as a file path first
    candidate = Path(as_str)
    if candidate.exists() and candidate.is_file():
        try:
            text = candidate.read_text(encoding="utf-8")
            return json.loads(text)
        except Exception as exc:
            logger.debug("safe_load: file read/parse failed for '%s': %s", candidate, exc)
            return None

    # Fall back: treat as a raw JSON string
    try:
        return json.loads(as_str)
    except Exception as exc:
        logger.debug("safe_load: JSON parse failed for string input: %s", exc)
        return None


def safe_dump(obj: Any, path: Path, indent: int = 2) -> bool:
    """
    Serialise *obj* to JSON and write it to *path*.

    Creates parent directories if they do not exist.

    Returns:
        True on success, False on any error.
    """
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(obj, indent=indent, default=str, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("safe_dump: write failed for '%s': %s", path, exc)
        return False


def merge_dicts(base: dict, override: dict) -> dict:
    """
    Deep-merge two dicts. *override* wins on key conflicts.

    Nested dicts are merged recursively; all other value types
    (including lists) are replaced by the *override* value.

    Returns:
        A new dict; neither input is mutated.
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override if isinstance(override, dict) else base

    result: dict = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = merge_dicts(result[key], val)
        else:
            result[key] = val
    return result


def flatten_keys(d: dict, sep: str = ".", prefix: str = "") -> dict:
    """
    Flatten a nested dict to dot-notation keys.

    Example:
        {"a": {"b": {"c": 1}}, "d": 2}
        → {"a.b.c": 1, "d": 2}

    Args:
        d:      Dict to flatten (may contain nested dicts).
        sep:    Key separator (default ".").
        prefix: Internal recursion prefix; callers should leave this empty.

    Returns:
        Flat dict with string keys.
    """
    items: dict = {}
    for key, val in d.items():
        full_key = f"{prefix}{sep}{key}" if prefix else str(key)
        if isinstance(val, dict):
            items.update(flatten_keys(val, sep=sep, prefix=full_key))
        else:
            items[full_key] = val
    return items


def get_nested(d: dict, *keys: str, default: Any = None) -> Any:
    """
    Safe nested key access via a chain of string keys.

    Usage:
        get_nested(d, "a", "b", "c")  →  d["a"]["b"]["c"] or *default*

    Returns *default* instead of raising KeyError / TypeError.
    """
    current: Any = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
        if current is default:
            return default
    return current


def strip_nulls(d: dict) -> dict:
    """
    Recursively remove all keys whose value is None from a dict.

    Lists are traversed; any None elements inside a list are kept
    (only None dict *values* are removed to avoid surprising list mutations).

    Returns:
        A new dict with None values removed at all nesting levels.
    """
    result: dict = {}
    for key, val in d.items():
        if val is None:
            continue
        if isinstance(val, dict):
            result[key] = strip_nulls(val)
        elif isinstance(val, list):
            result[key] = [
                strip_nulls(item) if isinstance(item, dict) else item
                for item in val
            ]
        else:
            result[key] = val
    return result
