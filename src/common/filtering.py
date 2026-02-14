from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union


FilterCondition = Union[
    Any,  # default eq
    Dict[str, Any],  # {"op": "...", "value": ...} / {"operator": "...", "value": ...}
    Tuple[str, Any],  # ("gte", 5)
]


def _get_field_value(item: Dict[str, Any], field: str) -> Any:
    """
    Resolve dotted field paths like "provider.name".
    Returns None if any segment is missing.
    """
    cur: Any = item
    for part in field.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _to_casefold(value: Any) -> Any:
    return value.casefold() if isinstance(value, str) else value


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None

    # Common ISO formats; normalize Zulu timestamps.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # If only date, parse as midnight.
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Some APIs return "YYYY-MM-DD HH:MM:SS"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def _try_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def matches_filter(item: Dict[str, Any], field: str, condition: FilterCondition) -> bool:
    """
    Check if `item[field]` matches `condition`.

    Supported operators:
    - eq (default), neq
    - contains, startswith
    - gt, gte, lt, lte
    - in

    All string comparisons are case-insensitive.
    """
    op = "eq"
    expected: Any = condition

    if isinstance(condition, tuple) and len(condition) == 2:
        op, expected = condition
    elif isinstance(condition, dict):
        op = condition.get("op") or condition.get("operator") or "eq"
        expected = condition.get("value")

    op = str(op).lower().strip()
    actual = _get_field_value(item, field)

    # Normalize strings for case-insensitive comparisons.
    actual_norm = _to_casefold(actual)
    expected_norm = _to_casefold(expected)

    if op == "eq":
        return actual_norm == expected_norm
    if op == "neq":
        return actual_norm != expected_norm

    if op in ("contains", "startswith"):
        if actual is None or expected is None:
            return False
        if isinstance(actual, list):
            haystack = " ".join([str(x) for x in actual if x is not None])
            haystack = haystack.casefold()
        else:
            haystack = str(actual).casefold()
        needle = str(expected).casefold()
        return needle in haystack if op == "contains" else haystack.startswith(needle)

    if op == "in":
        if expected is None:
            return False
        candidates = expected if isinstance(expected, (list, tuple, set)) else [expected]
        if isinstance(actual, list):
            actual_values = [_to_casefold(v) for v in actual]
            return any(_to_casefold(c) in actual_values for c in candidates)
        return any(actual_norm == _to_casefold(c) for c in candidates)

    # Comparisons (numbers/dates/strings)
    a_num = _try_float(actual)
    e_num = _try_float(expected)
    if a_num is not None and e_num is not None:
        if op == "gt":
            return a_num > e_num
        if op == "gte":
            return a_num >= e_num
        if op == "lt":
            return a_num < e_num
        if op == "lte":
            return a_num <= e_num
        return False

    a_dt = _parse_datetime(actual)
    e_dt = _parse_datetime(expected)
    if a_dt is not None and e_dt is not None:
        if op == "gt":
            return a_dt > e_dt
        if op == "gte":
            return a_dt >= e_dt
        if op == "lt":
            return a_dt < e_dt
        if op == "lte":
            return a_dt <= e_dt
        return False

    # Fallback: string compare (case-insensitive)
    if actual is None or expected is None:
        return False
    a_str = str(actual).casefold()
    e_str = str(expected).casefold()
    if op == "gt":
        return a_str > e_str
    if op == "gte":
        return a_str >= e_str
    if op == "lt":
        return a_str < e_str
    if op == "lte":
        return a_str <= e_str
    return False


def filter_items(
    items: List[Dict[str, Any]],
    filters: Optional[Dict[str, FilterCondition]] = None,
    limit: Optional[int] = None,
    sort_field: Optional[str] = None,
    sort_order: str = "asc",
) -> Dict[str, Any]:
    """
    Filter, sort, and limit a list of dict items.

    Returns:
      - items: the (optionally limited) filtered list
      - total_count: original item count
      - filtered_count: count after applying filters (before limit)
    """
    total_count = len(items or [])
    working: List[Dict[str, Any]] = list(items or [])

    if filters:
        def _matches_all(it: Dict[str, Any]) -> bool:
            for field, cond in filters.items():
                if cond is None:
                    continue
                if not matches_filter(it, field, cond):
                    return False
            return True

        working = [it for it in working if _matches_all(it)]

    filtered_count = len(working)

    if sort_field:
        order = (sort_order or "asc").lower().strip()

        def _sort_key(it: Dict[str, Any]):
            v = _get_field_value(it, sort_field)
            if isinstance(v, str):
                v = v.casefold()
            return (v is None, v)

        working.sort(key=_sort_key, reverse=(order == "desc"))

    if limit is not None:
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = None
        if lim is not None and lim >= 0:
            working = working[:lim]

    return {"items": working, "total_count": total_count, "filtered_count": filtered_count}

