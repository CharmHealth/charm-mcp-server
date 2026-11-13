import re
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


def read_failure(response: Any) -> Optional[str]:
    """Why a CharmHealthAPIClient read failed, or None when it succeeded.

    The client returns {"error": "HTTP 503: ..."} instead of raising, so a
    caller that goes straight to `response.get("allergies", [])` turns a failed
    read into "no allergies". Check this first. A bare list (some endpoints
    answer with one) is a success. The text is capped because it is the
    backend's own message and can be long.
    """
    if response is None:
        return "no response"
    if isinstance(response, dict) and response.get("error"):
        return str(response["error"])[:200]
    return None


def failed_read_result(what: str, reason: str) -> Dict[str, Any]:
    """The error a list read returns when its only read failed.

    A top-level "error" makes `@with_tool_metrics()` raise ToolError, so the
    caller sees a failure instead of an empty list (CH-1902).
    """
    # A 4xx other than 429 fails the same way on retry: it is a wrong id or a
    # missing parameter. Only a 5xx, a 429 or a network error is worth retrying.
    match = re.match(r"HTTP (\d{3})", reason)
    status = int(match.group(1)) if match else None
    if status is not None and 400 <= status < 500 and status != 429:
        advice = (
            "The request was rejected, so retrying won't help. Check the ids and "
            "parameters (findPatients or getPracticeInfo can confirm them)."
        )
    else:
        advice = "This is likely temporary. Retry; don't treat this as none."
    return {
        "error": f"Could not read {what}: {reason}",
        "guidance": f"The {what} read failed, so it is not known what is there. {advice}",
    }
