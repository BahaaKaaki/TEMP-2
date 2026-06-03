"""
Azure AD / Entra ID authentication for PostgreSQL connections.

This module provides token management for Azure AD authentication using ManagedIdentityCredential,
which uses the managed identity configured for the Azure service.
Requires AZURE_CLIENT_ID environment variable to be set.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from threading import Lock
from config.keyvault import cfg
from typing import Optional

from azure.identity import ManagedIdentityCredential
from azure.core.exceptions import AzureError


class AzureTokenManager:
    """Manages Azure AD tokens with automatic refresh for PostgreSQL connections."""
    
    # PostgreSQL Azure AD scope
    POSTGRESQL_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
    
    def __init__(self):
        self._token = None
        self._token_expiry = None
        self._credential = None
        self._lock = Lock()
        self._refresh_buffer = timedelta(minutes=5)  # Refresh 5 minutes before expiry
        self._refresh_task = None
        self._should_stop = False
        self.logger = logging.getLogger(__name__)
        
        # Initialize ManagedIdentityCredential
        try:
            self._credential = ManagedIdentityCredential(
                client_id=cfg.AZURE_CLIENT_ID_PGSQL
            )
            self.logger.info("✅ ManagedIdentityCredential initialized for Azure AD authentication")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize ManagedIdentityCredential: {e}")
    
    def _is_token_expired(self) -> bool:
        """Check if current token is expired or will expire soon."""
        if self._token is None or self._token_expiry is None:
            return True
        return datetime.now() >= (self._token_expiry - self._refresh_buffer)
    
    def get_token(self) -> Optional[str]:
        """Get a valid Azure AD token, refreshing if necessary."""
        with self._lock:
            if self._is_token_expired():
                self._refresh_token()
            return self._token
    
    async def get_token_async(self) -> Optional[str]:
        """Async version of get_token for use in async contexts."""
        # Run synchronous get_token in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_token)
    
    def _refresh_token(self):
        """Refresh the Azure AD token using ManagedIdentityCredential."""
        if self._credential is None:
            self.logger.error("ManagedIdentityCredential not initialized")
            return
        
        try:
            # Get token for Azure PostgreSQL
            token_result = self._credential.get_token(self.POSTGRESQL_SCOPE)
            
            self._token = token_result.token
            # Token expiry is in Unix timestamp (seconds since epoch)
            self._token_expiry = datetime.fromtimestamp(token_result.expires_on)
            
            expires_in = (self._token_expiry - datetime.now()).total_seconds()
            self.logger.debug(f"🔐 Azure AD token refreshed successfully (expires in {expires_in/60:.1f} minutes)")
            
        except AzureError as e:
            self.logger.error(f"❌ Azure AD token refresh failed: {e}")
            self._token = None
            self._token_expiry = None
        except Exception as e:
            self.logger.error(f"❌ Unexpected error during token refresh: {e}")
            self._token = None
            self._token_expiry = None
    
    async def start_background_refresh(self):
        """Start a background task that proactively refreshes tokens."""
        if self._refresh_task is not None:
            self.logger.warning("Background token refresh task already running")
            return
        
        self._should_stop = False
        self._refresh_task = asyncio.create_task(self._background_refresh_loop())
        self.logger.info("🔄 Started background token refresh task")
    
    async def stop_background_refresh(self):
        """Stop the background token refresh task."""
        if self._refresh_task is None:
            return
        
        self._should_stop = True
        if not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        
        self._refresh_task = None
        self.logger.info("🛑 Stopped background token refresh task")
    
    async def _background_refresh_loop(self):
        """Background loop that refreshes token before it expires."""
        while not self._should_stop:
            try:
                if self._is_token_expired():
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._refresh_token)
                
                if self._token_expiry:
                    time_until_refresh = (self._token_expiry - datetime.now() - self._refresh_buffer).total_seconds() / 2
                    sleep_duration = max(60, min(time_until_refresh, 1800))
                else:
                    sleep_duration = 300
                
                await asyncio.sleep(sleep_duration)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in background token refresh: {e}")
                await asyncio.sleep(60)
