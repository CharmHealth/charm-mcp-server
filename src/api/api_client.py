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
                 access_token: Optional[str] = None,
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

        # Flexible validation: require refresh_token and client_id (allow env vars OR passed credentials)
        if not self.refresh_token:
            raise ValueError("Missing refresh_token (required for token refresh)")
        if not self.client_id:
            raise ValueError("Missing client_id")
        
        self.max_retries = max_retries
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._token_lock = Lock()
        
        # Initialize with provided access token if available
        if access_token:
            self._auth_token = access_token
            # Set expiry to 1 hour from now (typical access token lifetime)
            # This allows the token to be used before attempting refresh
            self._token_expires_at = time.time() + 3600
            logger.info("API client initialized with provided access token (expires in ~1 hour)")
        else:
            self._auth_token = None
            self._token_expires_at = 0

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
            # "Authorization": f"Bearer {token}",
            "Authorization": f"Zoho-oauthtoken {token}",
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
        logger.info(f"Token URL: {self.token_url}")
        logger.info(f"Client ID: {self.client_id}")
        logger.info(f"Client secret present: {bool(self.client_secret)} (length: {len(self.client_secret) if self.client_secret else 0})")
        logger.info(f"Refresh token present: {bool(self.refresh_token)} (prefix: {self.refresh_token[:20] if self.refresh_token else 'None'}...)")
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        }
        form = {
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': self.redirect_uri,
            'grant_type': 'refresh_token',
        }

        async with httpx.AsyncClient() as client:
            response = None
            try:
                response = await client.post(
                    self.token_url,
                    data=form,
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
                # `response` can still be None here — client.post() itself can raise
                # (connection refused, DNS failure, timeout) before it's ever assigned,
                # and referencing response.text unconditionally would replace that real
                # error with an UnboundLocalError, undermining the "a failed refresh
                # returns a clean error" goal this whole retry path exists for.
                response_detail = response.text if response is not None else "no response received"
                logger.error(f"Failed to refresh token: {e} with response: {response_detail}")
                raise
    
    async def _make_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None, retry_count: int = 0, auth_retried: bool = False) -> Dict[str, Any]:
        logger.info(f"Making {method} request to {endpoint}")
        await self.ensure_client()
        start_time = time.time()

        # Remove any IDs from endpoint for metrics (an ID is an 18 digit number either between / and / or at the end)
        clean_endpoint = re.sub(r'/[0-9]{18}$', '', endpoint)
        clean_endpoint = re.sub(r'/[0-9]{18}/', '/', clean_endpoint)

        # Mark API call as starting
        start_api_call(self.client_id, clean_endpoint, method)

        api_success = False

        # Fetching headers is deliberately in its own try/except, separate from the
        # request try/except below. _get_auth_headers() -> _refresh_token() can raise
        # httpx.HTTPStatusError if the OAuth TOKEN endpoint itself returns a non-2xx
        # (e.g. a 401 for a bad/rotated client_secret) — if that were allowed to reach
        # the request try/except's `except httpx.HTTPStatusError as e:` clause below,
        # `e.response` would be the OAuth server's response, not the target API's, and
        # the status_code==401-triggers-a-refresh-and-retry logic there would wrongly
        # fire a second, unwanted refresh for a problem a second refresh cannot fix
        # (bad client_secret), plus mislabel the OAuth server's error as the target
        # endpoint's. Catching it here first, before that logic ever sees it, avoids both.
        try:
            headers = await self._get_auth_headers()
        except Exception as e:
            duration = time.time() - start_time
            record_api_call(self.client_id, False, clean_endpoint, method, duration)
            # start_api_call() above set the gauge active — this early return skips
            # the `finally` below (it belongs to the second try), so without this the
            # gauge for this (endpoint, method, client_id) sticks at "in flight"
            # forever. A dead refresh token sends every call down this path, so the
            # dashboard would read as permanently stuck mid-request during the exact
            # incident this code exists to handle.
            end_api_call(self.client_id, clean_endpoint, method, duration, False)
            logger.error(f"Token refresh failed while preparing request to {endpoint}: {e}")
            return {"error": f"Token refresh failed: {e}"}

        auth_header = headers.get("Authorization", "")
        auth_preview = f"{auth_header[:20]}...({len(auth_header)} chars)" if auth_header else "MISSING"

        try:
            match method:
                case "GET":
                    response = await self._client.get(endpoint, params=params, headers=headers, timeout=self.timeout)
                case "POST":
                    response = await self._client.post(endpoint, json=data, params=params, headers=headers, timeout=self.timeout)
                case "POST_FORM":
                    # Some endpoints (e.g. billing statement send) bind their body as a named
                    # request parameter (<param type="JSONObject">), not a raw JSON body
                    # (<inputstream>) — those need application/x-www-form-urlencoded, not
                    # application/json, or the framework never resolves the parameter.
                    form_headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
                    response = await self._client.post(endpoint, data=data, params=params, headers=form_headers, timeout=self.timeout)
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
            logger.info(f"Received {result} from {endpoint} with status code {response.status_code}")
            # Record successful API call
            record_api_call(self.client_id, True, clean_endpoint, method, duration)
            return result
            
        except httpx.HTTPStatusError as e:
            # Record failed API call
            duration = time.time() - start_time
            record_api_call(self.client_id, False, clean_endpoint, method, duration)
            
            if e.response.status_code == 401 and not auth_retried:
                # Refresh and retry exactly once per request, regardless of max_retries.
                # A 401 that survives a *freshly refreshed* token means the token was
                # never the problem (e.g. the account's OAuth grant lacks the scope this
                # endpoint needs) — retrying up to max_retries times would just repeat
                # that same failure while repeatedly wiping the shared token cache
                # (_shared_token_cache is keyed by client_id+refresh_token, so it's shared
                # by every other in-flight call using the same credentials) for no benefit,
                # and risks compounding a real refresh-token problem if the one refresh
                # this does perform also fails.
                logger.warning("Received 401, forcing a single token refresh and retry")
                self._auth_token = None
                self._token_expires_at = 0
                try:
                    key = self._token_cache_key()
                    self.__class__._shared_token_cache.pop(key, None)
                except Exception:
                    pass
                return await self._make_request(method, endpoint, params, data, retry_count, auth_retried=True)
            logger.error(f"HTTP error {e.response.status_code}: {e}")
            logger.error(f"Response body: {e.response.text}")
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

        except httpx.RequestError as e:
            # Record failed API call
            duration = time.time() - start_time
            record_api_call(self.client_id, False, clean_endpoint, method, duration)

            if retry_count < self.max_retries:
                logger.warning(f"Request failed, retrying ({retry_count + 1}/{self.max_retries}): {e}")
                await asyncio.sleep(2 ** retry_count)
                return await self._make_request(method, endpoint, params, data, retry_count + 1, auth_retried)

            logger.error(f"Request failed after {self.max_retries} retries: {e}")
            return {"error": f"Request failed: {e}"}

        except Exception as e:
            # Record failed API call. Token-refresh failures are caught by their
            # own isolated try/except above (since 96731d7) and never reach here —
            # this branch is for genuinely unexpected errors in the request/response
            # handling above (e.g. an httpx internal error, a bad response.json()).
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

    async def post_form(self, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a POST request with an application/x-www-form-urlencoded body."""
        return await self._make_request('POST_FORM', endpoint, data=data, params=params)
        
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
        # Create user-specific cache key using hash of refresh token
        # This prevents token collision between different users
        import hashlib
        token_hash = hashlib.sha256(self.refresh_token.encode()).hexdigest()[:16]
        return f"{self.client_id}:{token_hash}"



