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


def strip_empty_values(data: Any, preserve_empty_lists: bool = True) -> Any:
    """
    Recursively remove empty values from API responses to reduce LLM token usage.
    
    Removes: None, empty strings, empty dicts
    Preserves: False, 0, and optionally empty lists (which may indicate "none found")
    
    Args:
        data: The data structure to clean (dict, list, or scalar)
        preserve_empty_lists: If True, keeps empty lists (clinically meaningful: 
                              "no allergies" ≠ "allergies unknown"). Default True.
    
    Returns:
        Cleaned data structure with empty values removed
    """
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            # Skip None, empty strings, and empty dicts
            if v is None or v == "" or v == {}:
                continue
            # Skip empty lists if not preserving them
            if not preserve_empty_lists and v == []:
                continue
            # Recursively clean nested structures
            cleaned_value = strip_empty_values(v, preserve_empty_lists)
            # After cleaning, check if the result became empty
            if cleaned_value is None or cleaned_value == "" or cleaned_value == {}:
                continue
            if not preserve_empty_lists and cleaned_value == []:
                continue
            cleaned[k] = cleaned_value
        return cleaned
    elif isinstance(data, list):
        return [strip_empty_values(item, preserve_empty_lists) for item in data]
    return data
