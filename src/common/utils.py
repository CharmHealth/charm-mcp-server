from typing import Dict, Any, List, Optional
from datetime import date, time

def build_params_from_locals(locals_dict: Dict, exclude: List[str] = None) -> Dict[str, Any]:
    """
    Build a dictionary of API parameters from the locals dictionary
    """
    exclude = exclude or []
    exclude.append("client")
    params = {}
    for k, v in locals_dict.items():
        if k not in exclude and v is not None:
            if isinstance(v, date):
                params[k] = v.isoformat()
            elif isinstance(v, bool):
                params[k] = str(v).lower()
            elif isinstance(v, time):
                params[k] = v.strftime("%I:%M %p")
            else:
                params[k] = v
    return params


def filter_items(
    items: List[Dict[str, Any]],
    filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    sort_field: Optional[str] = None,
    sort_order: Optional[str] = "asc",
) -> List[Dict[str, Any]]:
    """
    Filter and sort items based on the provided filters and sort criteria.
    """
    if not items:
        return items
    result = items.copy()
    if filters:
        for field, condition in filters.items():
            if isinstance(condition, dict):
                op = condition.get("op", "equals")
                value = condition.get("value", "")
            else:
                op = "equals"
                value = condition
            
            result = [
                item for item in result if matches_filter(item.get(field), value, op)
            ]
    
    if sort_field:
        reverse = sort_order.lower() == "desc"
        result = sorted(result, key=lambda x: x.get(sort_field), reverse=reverse)

    if limit and limit > 0:
        result = result[:limit]

    return result

def matches_filter(item_value: Any, filter_value: Any, op: str = "equals") -> bool:
    """
    Check if the value matches the filter condition based on the operator.
    """
    if item_value is None:
        return False
    
    item_str = str(item_value).lower()
    filter_str = str(filter_value).lower()
    
    match op:
        case "equals":
            return item_str == filter_str
        case "not_equals":
            return item_str != filter_str
        case "contains":
            return filter_str in item_str
        case "not_contains":
            return filter_str not in item_str
        case "starts_with":
            return item_str.startswith(filter_str)
        case "ends_with":
            return item_str.endswith(filter_str)
        case "is_empty":
            return not item_str
        case "is_not_empty":
            return bool(item_str)
        case "greater_than":
            return float(item_str) > float(filter_str)
        case "greater_than_or_equal":
            return float(item_str) >= float(filter_str)
        case "less_than":
            return float(item_str) < float(filter_str)
        case "less_than_or_equal":
            return float(item_str) <= float(filter_str)
        case _:
            return item_str == filter_str