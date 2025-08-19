import httpx
import asyncio
import time
import os
from dotenv import load_dotenv
import logging
from typing import Optional, Dict, Any
from asyncio import Lock
from telemetry import record_api_call, start_api_call, end_api_call, set_client_context
import re
logger = logging.getLogger(__name__)

load_dotenv()


class CharmHealthAPIClient:
    _shared_token_cache: Dict[str, Dict[str, Any]] = {}
    _shared_token_locks: Dict[str, Lock] = {}

    def __init__(self, 
                 base_url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 refresh_token: Optional[str] = None,
                 client_id: Optional[str] = None,
                 client_secret: Optional[str] = None,
                 redirect_uri: Optional[str] = None,
                 token_url: Optional[str] = None,
                 max_retries: int = 3,
                 timeout: int = 30):
        self.base_url = base_url or os.getenv("CHARMHEALTH_BASE_URL")
        self.api_key = api_key or os.getenv("CHARMHEALTH_API_KEY")
        self.refresh_token = refresh_token or os.getenv("CHARMHEALTH_REFRESH_TOKEN")
        self.client_id = client_id or os.getenv("CHARMHEALTH_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CHARMHEALTH_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("CHARMHEALTH_REDIRECT_URI")
        self.token_url = token_url or os.getenv("CHARMHEALTH_TOKEN_URL")

        if not all([self.api_key, self.refresh_token, self.client_id, self.client_secret]):
            raise ValueError("Missing required CharmHealth API credentials")
        
        self.max_retries = max_retries
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._auth_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._token_lock = Lock()

    async def __aenter__(self):
        logger.info("Entering CharmHealth API client context")
        set_client_context(self.client_id)
        await self.ensure_client()
        return self
    
    async def __aexit__(self, exc_type, exc_value, traceback):
        logger.info("Exiting CharmHealth API client context")
        await self.close()
    
    async def ensure_client(self):
        logger.info("Ensuring CharmHealth API client")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "api_key": self.api_key,
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache"
                }
            )
        
        
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        logger.info("Getting auth headers")
        token = await self._get_valid_token()
        return {
            "api_key": self.api_key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache"
        }
    
    async def _get_valid_token(self) -> str:
        logger.info("Getting valid CharmHealth API token")
        current_time = time.time()

        if self._auth_token and current_time < (self._token_expires_at - 300):
            return self._auth_token

        key = self._token_cache_key()
        entry = self.__class__._shared_token_cache.get(key)
        if entry and current_time < (entry["expires_at"] - 300):
            self._auth_token = entry["token"]
            self._token_expires_at = entry["expires_at"]
            return entry["token"]

        lock = self.__class__._shared_token_locks.setdefault(key, Lock())
        async with lock:
            current_time = time.time()
            if self._auth_token and current_time < (self._token_expires_at - 300):
                return self._auth_token
            entry = self.__class__._shared_token_cache.get(key)
            if entry and current_time < (entry["expires_at"] - 300):
                self._auth_token = entry["token"]
                self._token_expires_at = entry["expires_at"]
                return entry["token"]
            return await self._refresh_token()
    

    async def _refresh_token(self) -> str:
        logger.info("Refreshing CharmHealth API token")
        headers = {'Content-Type': 'application/json'}
        params = {
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': self.redirect_uri,
            'grant_type': 'refresh_token',
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.token_url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout
                )
                current_time = time.time()
                response.raise_for_status()
                token_data = response.json()
                new_token = token_data.get('access_token')
                expires_in = token_data.get('expires_in', 3600)
                if not new_token:
                    raise ValueError(f"Failed to obtain new token with response: {response.text}")

                self._auth_token = new_token
                self._token_expires_at = current_time + expires_in

                key = self._token_cache_key()
                self.__class__._shared_token_cache[key] = {
                    "token": new_token,
                    "expires_at": self._token_expires_at,
                }

                scopes = token_data.get('scope', '')
                scope_count = len(scopes.split()) if isinstance(scopes, str) else 0
                logger.info(f"Token refreshed successfully (expires_in={expires_in}s, scopes={scope_count})")
                return new_token

            except Exception as e:
                logger.error(f"Failed to refresh token: {e} with response: {response.text}")
                raise
    
    async def _make_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None, retry_count: int = 0) -> Dict[str, Any]:
        logger.info(f"Making {method} request to {endpoint}")
        await self.ensure_client()
        headers = await self._get_auth_headers()
        start_time = time.time()
        
        # Remove any IDs from endpoint for metrics (an ID is an 18 digit number either between / and / or at the end)
        clean_endpoint = re.sub(r'/[0-9]{18}$', '', endpoint)
        clean_endpoint = re.sub(r'/[0-9]{18}/', '/', clean_endpoint)
        
        # Mark API call as starting
        start_api_call(self.client_id, clean_endpoint, method)
        
        api_success = False
        
        try:
            match method:
                case "GET":
                    response = await self._client.get(endpoint, params=params, headers=headers, timeout=self.timeout)
                case "POST":
                    response = await self._client.post(endpoint, json=data, params=params, headers=headers, timeout=self.timeout)
                case "PUT":
                    response = await self._client.put(endpoint, json=data, params=params, headers=headers, timeout=self.timeout)
                case "DELETE":
                    response = await self._client.delete(endpoint, params=params, headers=headers, timeout=self.timeout)
                case _:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
            response.raise_for_status()
            result = response.json()
            duration = time.time() - start_time
            api_success = True
            
            # Record successful API call
            record_api_call(self.client_id, True, clean_endpoint, method, duration)
            return result
            
        except httpx.HTTPStatusError as e:
            # Record failed API call
            duration = time.time() - start_time
            record_api_call(self.client_id, False, clean_endpoint, method, duration)
            
            if e.response.status_code == 401 and retry_count < self.max_retries:
                logger.warning("Received 401, forcing token refresh")
                self._auth_token = None
                self._token_expires_at = 0
                try:
                    key = self._token_cache_key()
                    self.__class__._shared_token_cache.pop(key, None)
                except Exception:
                    pass
                return await self._make_request(method, endpoint, params, data, retry_count + 1)
            logger.error(f"HTTP error {e.response.status_code}: {e}")
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
            
        except httpx.RequestError as e:
            # Record failed API call
            duration = time.time() - start_time
            record_api_call(self.client_id, False, clean_endpoint, method, duration)
            
            if retry_count < self.max_retries:
                logger.warning(f"Request failed, retrying ({retry_count + 1}/{self.max_retries}): {e}")
                await asyncio.sleep(2 ** retry_count)
                return await self._make_request(method, endpoint, params, data, retry_count + 1)
            
            logger.error(f"Request failed after {self.max_retries} retries: {e}")
            return {"error": f"Request failed: {e}"}
            
        except Exception as e:
            # Record failed API call
            duration = time.time() - start_time
            record_api_call(self.client_id, False, clean_endpoint, method, duration)
            logger.error(f"Unexpected error: {e}")
            return {"error": f"Unexpected error: {e}"}
        
        finally:
            # Mark API call as completed with duration and success status
            duration = time.time() - start_time
            end_api_call(self.client_id, clean_endpoint, method, duration, api_success)
        
    async def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request."""
        return await self._make_request('GET', endpoint, params=params)
        
    async def post(self, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a POST request."""
        return await self._make_request('POST', endpoint, data=data, params=params)
        
    async def put(self, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a PUT request."""
        return await self._make_request('PUT', endpoint, data=data, params=params)
        
    async def delete(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a DELETE request."""
        return await self._make_request('DELETE', endpoint, params=params)
    
    async def get_client_id(self) -> str:
        """Get the client ID from the API client."""
        return self.client_id
    
    def _token_cache_key(self) -> str:
        return self.client_id



