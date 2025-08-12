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