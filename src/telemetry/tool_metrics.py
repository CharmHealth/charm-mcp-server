import functools
import time
import logging
from typing import Dict, Any, Callable, Optional
from .telemetry_config import telemetry
import contextvars

logger = logging.getLogger(__name__)

# Context variable to track current client_id and API call count
current_client_id: contextvars.ContextVar[str] = contextvars.ContextVar('client_id', default='unknown')
api_call_count: contextvars.ContextVar[int] = contextvars.ContextVar('api_call_count', default=0)
successful_api_calls: contextvars.ContextVar[int] = contextvars.ContextVar('successful_api_calls', default=0)

# Track total tool calls and successes for success rate calculation
total_tool_calls: contextvars.ContextVar[int] = contextvars.ContextVar('total_tool_calls', default=0)
successful_tool_calls: contextvars.ContextVar[int] = contextvars.ContextVar('successful_tool_calls', default=0)

def with_tool_metrics(tool_name: Optional[str] = None):
    """
    Focused decorator to track:
    1. Tool name
    2. Client ID 
    3. Tool execution duration
    4. Success/failure status
    5. Gauge metrics for current status and success rates
    
    Args:
        tool_name: Override the tool name (defaults to function name)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get tool name
            actual_tool_name = tool_name or func.__name__
            
            # Start timing
            start_time = time.time()
            
            # Reset API call counters for this tool execution
            api_call_count.set(0)
            successful_api_calls.set(0)
            
            # Get client ID from context (if available)
            client_id = current_client_id.get('unknown')
            
            # Base attributes for metrics (no status at start)
            base_attributes = {
                "tool_name": actual_tool_name,
                "client_id": client_id
            }
            
            # Set tool call gauge to active (1)
            if telemetry.tool_calls_gauge:
                telemetry.tool_calls_gauge.set(1, base_attributes)
            
            try:
                # Execute the tool function
                result = await func(*args, **kwargs)
                
                # Determine overall success based on result
                is_success = _is_successful_response(result)
                status = "success" if is_success else "failure"
                
                # Update client ID after tool execution (in case it was set during execution)
                client_id = current_client_id.get('unknown')
                base_attributes["client_id"] = client_id
                
                # Record metrics
                _record_tool_completion_metrics(base_attributes, start_time, status, is_success)
                
                return result
                
            except Exception as e:
                # Update client ID for error case
                client_id = current_client_id.get('unknown')
                base_attributes["client_id"] = client_id
                
                # Record failure metrics
                _record_tool_completion_metrics(base_attributes, start_time, "error", False)
                logger.error(f"Tool {actual_tool_name} failed with exception: {e}")
                raise
            finally:
                # Calculate final duration and determine final status
                duration = time.time() - start_time
                
                # Determine final status for gauge
                try:
                    # If we got here through the success path, result exists
                    final_status = "success" if _is_successful_response(result) else "failure"
                except (NameError, UnboundLocalError):
                    # If we got here through exception path, it's an error
                    final_status = "error"
                
                # Set tool call gauge to idle (0) with duration and final status (outcome)
                if telemetry.tool_calls_gauge:
                    final_attributes = {**base_attributes, "duration": duration, "status": final_status}
                    telemetry.tool_calls_gauge.set(0, final_attributes)
        
        return wrapper
    return decorator

def _is_successful_response(response: Dict[str, Any]) -> bool:
    """Determine if a tool response indicates success"""
    if not isinstance(response, dict):
        return False
        
    # Check for explicit error indicators
    if "error" in response:
        return False
        
    # Check for API error codes
    if "code" in response:
        code = response.get("code", "")
        if isinstance(code, str) and "error" in code.lower():
            return False
        if isinstance(code, int) and code >= 400:
            return False
    
    # Check message for error indicators
    message = response.get("message", "")
    if isinstance(message, str) and any(error_word in message.lower() for error_word in ["error", "failed", "failure"]):
        return False
    
    return True

def _record_tool_completion_metrics(base_attributes: Dict[str, str], start_time: float, status: str, is_success: bool):
    """Record metrics when a tool completes"""
    try:
        duration = time.time() - start_time
        
        if not telemetry.tool_calls_counter:
            logger.warning("Telemetry not initialized, skipping metrics")
            return
        
        # Add status to attributes
        attributes = {**base_attributes, "status": status, "duration": duration}
        
        # Record tool call count
        telemetry.tool_calls_counter.add(1, attributes)
        
        # Record tool duration
        telemetry.tool_duration_histogram.record(duration, attributes)
        
        # Update success rate tracking
        current_total = total_tool_calls.get(0)
        current_successful = successful_tool_calls.get(0)
        
        total_tool_calls.set(current_total + 1)
        if is_success:
            successful_tool_calls.set(current_successful + 1)
            current_successful += 1
        
        # Calculate and update success rate gauge
        if telemetry.tool_success_rate_gauge and (current_total + 1) > 0:
            success_rate = current_successful / (current_total + 1)
            success_rate_attributes = {**base_attributes, "status": status}
            telemetry.tool_success_rate_gauge.set(success_rate, success_rate_attributes)
        
        # Get API call stats from context
        total_api_calls = api_call_count.get(0)
        successful_calls = successful_api_calls.get(0)
        failed_calls = total_api_calls - successful_calls
        
        logger.info(
            f"Tool '{base_attributes['tool_name']}' completed - "
            f"Status: {status}, Duration: {duration:.3f}s, "
            f"API calls: {total_api_calls} ({successful_calls} success, {failed_calls} failed), "
            f"Client: {base_attributes['client_id']}, Success rate: {current_successful / (current_total + 1):.3f}"
        )
        
    except Exception as e:
        logger.error(f"Failed to record tool metrics: {e}")

def record_api_call(client_id: str, success: bool, api_endpoint: str, method: str, duration: float):
    """
    Record an individual API call within a tool.
    Call this from the API client when making requests.
    
    Args:
        client_id: Client ID making the call
        success: Whether the API call was successful
        api_endpoint: The API endpoint being called
        method: HTTP method used
        duration: Duration of the API call in seconds
    """
    try:
        # Update context
        current_client_id.set(client_id)
        current_count = api_call_count.get(0)
        api_call_count.set(current_count + 1)
        
        if success:
            current_successful = successful_api_calls.get(0)
            successful_api_calls.set(current_successful + 1)
        
        # Attributes for API call metrics
        attributes = {
            "api_endpoint": api_endpoint,
            "method": method,
            "client_id": client_id,
            "status": "success" if success else "failure",
            "duration": duration
        }
        
        # Record API call metric
        if telemetry.api_calls_counter:
            telemetry.api_calls_counter.add(1, attributes)
            
        # Update API latency gauge with current call duration
        if telemetry.api_latency_gauge:
            telemetry.api_latency_gauge.set(duration, attributes)
            
        logger.info(f"API call recorded: {attributes}")
        
    except Exception as e:
        logger.error(f"Failed to record API call metric: {e}")

def start_api_call(client_id: str, api_endpoint: str, method: str):
    """
    Mark the start of an API call (sets gauge to active)
    
    Args:
        client_id: Client ID making the call
        api_endpoint: The API endpoint being called  
        method: HTTP method used
    """
    try:
        if telemetry.api_calls_gauge:
            attributes = {
                "api_endpoint": api_endpoint,
                "method": method,
                "client_id": client_id
                # No status - gauge value (1) indicates it's active
            }
            telemetry.api_calls_gauge.set(1, attributes)
            
    except Exception as e:
        logger.error(f"Failed to set API call gauge: {e}")

def end_api_call(client_id: str, api_endpoint: str, method: str, duration: float = 0.0, success: bool = True):
    """
    Mark the end of an API call (sets gauge to idle)
    
    Args:
        client_id: Client ID making the call
        api_endpoint: The API endpoint being called
        method: HTTP method used
        duration: Duration of the API call (optional)
        success: Whether the API call was successful
    """
    try:
        if telemetry.api_calls_gauge:
            attributes = {
                "api_endpoint": api_endpoint,
                "method": method,
                "client_id": client_id,
                "duration": duration,
                "status": "success" if success else "failure"  # Only include outcome status
            }
            telemetry.api_calls_gauge.set(0, attributes)
            
    except Exception as e:
        logger.error(f"Failed to unset API call gauge: {e}")

def set_client_context(client_id: str):
    """Set the client ID in context for the current execution"""
    current_client_id.set(client_id)