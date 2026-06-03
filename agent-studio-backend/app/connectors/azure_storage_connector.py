"""
Azure Storage connector for blob operations.
"""
import logging
from typing import Optional, List, Dict, Any, BinaryIO
from io import BytesIO
from datetime import datetime, timedelta
import asyncio
from functools import partial

from azure.storage.blob.aio import BlobServiceClient, ContainerClient, BlobClient
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel
from core.exceptions import StorageException, TimeoutException
from utils.retry import with_retry
from config.settings import settings


logger = logging.getLogger(__name__)


class BlobMetadata(BaseModel):
    """Blob metadata model."""
    name: str
    size: int
    content_type: Optional[str] = None
    created_at: datetime
    modified_at: datetime
    metadata: Dict[str, str] = {}
    etag: Optional[str] = None


class AzureStorageConnector:
    """
    Azure Blob Storage connector with async operations.
    Provides methods for uploading, downloading, and managing blobs.
    
    Supports two authentication methods:
    1. Connection String (for local dev with Azurite)
    2. Managed Identity (for Azure cloud deployments - more secure)
    
    All operations have configurable timeouts to prevent hanging indefinitely
    on network issues or slow Azure Storage responses.
    """
    
    def __init__(
        self,
        container_name: str,
        connection_string: Optional[str] = None,
        account_name: Optional[str] = None,
        use_managed_identity: bool = False,
        managed_identity_client_id: Optional[str] = None,
        create_container: bool = True,
        timeout: int = None
    ):
        """
        Initialize Azure Storage connector.
        
        Args:
            container_name: Default container name
            connection_string: Azure Storage connection string (for local dev)
            account_name: Storage account name (required if using managed identity)
            use_managed_identity: Use Azure AD Managed Identity authentication
            managed_identity_client_id: Client ID of specific UAMI (optional, for multiple UAMIs)
            create_container: Create container if it doesn't exist
            timeout: Operation timeout in seconds (defaults to settings.STORAGE_TIMEOUT)
        """
        if not use_managed_identity and not connection_string:
            raise ValueError("Either connection_string or use_managed_identity must be provided")
        
        if use_managed_identity and not account_name:
            raise ValueError("account_name is required when use_managed_identity is True")
        
        self.connection_string = connection_string
        self.account_name = account_name
        self.use_managed_identity = use_managed_identity
        self.managed_identity_client_id = managed_identity_client_id
        self.container_name = container_name
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._container_client: Optional[ContainerClient] = None
        self._credential: Optional[DefaultAzureCredential] = None
        self._create_container = create_container
        self._initialized = False
        self.timeout = timeout or settings.STORAGE_TIMEOUT
        
        auth_method = "Managed Identity" if use_managed_identity else "Connection String"
        if use_managed_identity and managed_identity_client_id:
            logger.debug(f"Azure Storage connector with {auth_method} (client_id: {managed_identity_client_id[:8]}...), timeout: {self.timeout}s")
        else:
            logger.debug(f"Azure Storage connector initialized with {auth_method}, timeout: {self.timeout}s")
    
    async def initialize(self) -> None:
        """Initialize blob service and container clients."""
        if self._initialized:
            return
        
        try:
            # Initialize blob service client based on authentication method
            if self.use_managed_identity:
                # Use Azure AD Managed Identity (secure, no keys)
                if self.managed_identity_client_id:
                    # Specify which UAMI to use (for multiple UAMIs)
                    self._credential = DefaultAzureCredential(
                        managed_identity_client_id=self.managed_identity_client_id
                    )
                    logger.debug(f"Using Managed Identity (client_id: {self.managed_identity_client_id[:8]}...) for {self.account_name}")
                else:
                    # Use default UAMI or System-Assigned MI
                    self._credential = DefaultAzureCredential()
                    logger.debug(f"Using Managed Identity authentication for {self.account_name}")
                
                account_url = f"https://{self.account_name}.blob.core.windows.net"
                self._blob_service_client = BlobServiceClient(
                    account_url=account_url,
                    credential=self._credential
                )
            else:
                # Use connection string (local dev with Azurite)
                self._blob_service_client = BlobServiceClient.from_connection_string(
                    self.connection_string
                )
                logger.debug("Using connection string authentication")
            
            self._container_client = self._blob_service_client.get_container_client(
                self.container_name
            )
            
            if self._create_container:
                try:
                    await self._container_client.create_container()
                    logger.debug("Created container: %s", self.container_name)
                except ResourceExistsError:
                    logger.debug("Container already exists: %s", self.container_name)
            
            self._initialized = True
            logger.info("Azure Storage connector initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Azure Storage connector: {e}")
            raise
    
    async def close(self) -> None:
        """Close blob service client connections."""
        if self._blob_service_client:
            await self._blob_service_client.close()
        if self._credential:
            await self._credential.close()
        # Give aiohttp time to clean up connections
        await asyncio.sleep(0.25)
        self._initialized = False
        logger.info("Azure Storage connector closed")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        return False
    
    async def _with_timeout(self, operation, operation_name: str):
        """
        Execute operation with timeout.
        
        Args:
            operation: Coroutine to execute
            operation_name: Name of operation (for error messages)
        
        Returns:
            Result of operation
        
        Raises:
            TimeoutException: If operation exceeds timeout
        """
        try:
            return await asyncio.wait_for(operation, timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.error(f"Azure Storage {operation_name} timed out after {self.timeout}s")
            raise TimeoutException(
                operation=f"Azure Storage {operation_name}",
                timeout=self.timeout
            )
    
    @with_retry(max_retries=3, initial_delay=1.0, exceptions=(Exception,))
    async def upload_blob(
        self,
        blob_name: str,
        data: bytes,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        overwrite: bool = True
    ) -> str:
        """
        Upload blob to Azure Storage with timeout.
        
        Args:
            blob_name: Name of the blob
            data: Blob data as bytes
            content_type: MIME type of the blob
            metadata: Custom metadata key-value pairs
            overwrite: Whether to overwrite existing blob
        
        Returns:
            Blob URL
        
        Raises:
            StorageException: If upload fails after retries
            TimeoutException: If upload exceeds timeout
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            
            content_settings = None
            if content_type:
                from azure.storage.blob import ContentSettings
                content_settings = ContentSettings(content_type=content_type)
            
            # Wrap upload with timeout
            await self._with_timeout(
                blob_client.upload_blob(
                    data,
                    overwrite=overwrite,
                    content_settings=content_settings,
                    metadata=metadata or {}
                ),
                operation_name=f"upload {blob_name}"
            )
            
            blob_url = blob_client.url
            logger.info("Uploaded blob: %s (%d bytes)", blob_name, len(data))
            return blob_url
            
        except TimeoutException:
            raise  # Re-raise timeout exceptions
        except Exception as e:
            logger.error(f"Failed to upload blob {blob_name}: {e}")
            raise StorageException("upload", str(e))
    
    async def upload_stream(
        self,
        blob_name: str,
        stream: BinaryIO,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        overwrite: bool = True
    ) -> str:
        """
        Upload blob from stream to Azure Storage.
        
        Args:
            blob_name: Name of the blob
            stream: Binary stream
            content_type: MIME type of the blob
            metadata: Custom metadata key-value pairs
            overwrite: Whether to overwrite existing blob
        
        Returns:
            Blob URL
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            
            content_settings = None
            if content_type:
                from azure.storage.blob import ContentSettings
                content_settings = ContentSettings(content_type=content_type)
            
            await blob_client.upload_blob(
                stream,
                overwrite=overwrite,
                content_settings=content_settings,
                metadata=metadata or {}
            )
            
            blob_url = blob_client.url
            logger.info("Uploaded blob from stream: %s", blob_name)
            return blob_url
            
        except Exception as e:
            logger.error(f"Failed to upload blob from stream {blob_name}: {e}")
            raise
    
    @with_retry(max_retries=3, initial_delay=1.0, exceptions=(Exception,))
    async def download_blob(self, blob_name: str) -> bytes:
        """
        Download blob from Azure Storage with timeout.
        
        Args:
            blob_name: Name of the blob
        
        Returns:
            Blob data as bytes
        
        Raises:
            ResourceNotFoundError: If blob doesn't exist
            StorageException: If download fails after retries
            TimeoutException: If download exceeds timeout
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            
            # Wrap download with timeout
            download_stream = await self._with_timeout(
                blob_client.download_blob(),
                operation_name=f"download {blob_name}"
            )
            data = await self._with_timeout(
                download_stream.readall(),
                operation_name=f"read {blob_name}"
            )
            
            logger.info("Downloaded blob: %s (%d bytes)", blob_name, len(data))
            return data
            
        except ResourceNotFoundError:
            logger.error(f"Blob not found: {blob_name}")
            raise
        except TimeoutException:
            raise  # Re-raise timeout exceptions
        except Exception as e:
            logger.error(f"Failed to download blob {blob_name}: {e}")
            raise StorageException("download", str(e))
    
    async def download_blob_to_stream(self, blob_name: str, stream: BinaryIO) -> int:
        """
        Download blob to stream from Azure Storage.
        
        Args:
            blob_name: Name of the blob
            stream: Binary stream to write to
        
        Returns:
            Number of bytes downloaded
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            download_stream = await blob_client.download_blob()
            bytes_downloaded = await download_stream.readinto(stream)
            
            logger.info("Downloaded blob to stream: %s (%d bytes)", blob_name, bytes_downloaded)
            return bytes_downloaded
            
        except ResourceNotFoundError:
            logger.error(f"Blob not found: {blob_name}")
            raise
        except Exception as e:
            logger.error(f"Failed to download blob to stream {blob_name}: {e}")
            raise
    
    async def delete_blob(self, blob_name: str) -> None:
        """
        Delete blob from Azure Storage with timeout.
        
        Args:
            blob_name: Name of the blob
        
        Raises:
            TimeoutException: If delete exceeds timeout
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            await self._with_timeout(
                blob_client.delete_blob(),
                operation_name=f"delete {blob_name}"
            )
            
            logger.info("Deleted blob: %s", blob_name)
            
        except ResourceNotFoundError:
            logger.warning(f"Blob not found for deletion: {blob_name}")
        except TimeoutException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete blob {blob_name}: {e}")
            raise
    
    async def blob_exists(self, blob_name: str) -> bool:
        """
        Check if blob exists in Azure Storage with timeout.
        
        Args:
            blob_name: Name of the blob
        
        Returns:
            True if blob exists, False otherwise
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            exists = await self._with_timeout(
                blob_client.exists(),
                operation_name=f"check existence of {blob_name}"
            )
            return exists
            
        except TimeoutException:
            logger.error(f"Timeout checking blob existence: {blob_name}")
            return False
        except Exception as e:
            logger.error(f"Failed to check blob existence {blob_name}: {e}")
            return False
    
    async def get_blob_metadata(self, blob_name: str) -> BlobMetadata:
        """
        Get blob metadata from Azure Storage.
        
        Args:
            blob_name: Name of the blob
        
        Returns:
            BlobMetadata object
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            properties = await blob_client.get_blob_properties()
            
            return BlobMetadata(
                name=blob_name,
                size=properties.size,
                content_type=properties.content_settings.content_type,
                created_at=properties.creation_time,
                modified_at=properties.last_modified,
                metadata=properties.metadata or {},
                etag=properties.etag
            )
            
        except ResourceNotFoundError:
            logger.error(f"Blob not found: {blob_name}")
            raise
        except Exception as e:
            logger.error(f"Failed to get blob metadata {blob_name}: {e}")
            raise
    
    async def list_blobs(
        self,
        prefix: Optional[str] = None,
        max_results: Optional[int] = None
    ) -> List[BlobMetadata]:
        """
        List blobs in container.
        
        Args:
            prefix: Filter blobs by prefix
            max_results: Maximum number of results
        
        Returns:
            List of BlobMetadata objects
        """
        await self.initialize()
        
        try:
            blobs = []
            async for blob in self._container_client.list_blobs(
                name_starts_with=prefix,
                results_per_page=max_results
            ):
                blobs.append(BlobMetadata(
                    name=blob.name,
                    size=blob.size,
                    content_type=blob.content_settings.content_type if blob.content_settings else None,
                    created_at=blob.creation_time,
                    modified_at=blob.last_modified,
                    metadata=blob.metadata or {},
                    etag=blob.etag
                ))
                
                if max_results and len(blobs) >= max_results:
                    break
            
            logger.info("Listed %d blobs with prefix: %s", len(blobs), prefix)
            return blobs
            
        except Exception as e:
            logger.error(f"Failed to list blobs: {e}")
            raise
    
    async def generate_sas_url(
        self,
        blob_name: str,
        expiry_hours: int = 24,
        permissions: str = "r"
    ) -> str:
        """
        Generate SAS URL for blob access.
        
        Args:
            blob_name: Name of the blob
            expiry_hours: URL expiry time in hours
            permissions: Permissions string (r=read, w=write, d=delete)
        
        Returns:
            SAS URL
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            
            # Extract account name and key from connection string
            conn_parts = dict(part.split('=', 1) for part in self.connection_string.split(';') if '=' in part)
            account_name = conn_parts.get('AccountName')
            account_key = conn_parts.get('AccountKey')
            
            if not account_name or not account_key:
                raise ValueError("Unable to extract account credentials from connection string")
            
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.container_name,
                blob_name=blob_name,
                account_key=account_key,
                permission=BlobSasPermissions.from_string(permissions),
                expiry=datetime.utcnow() + timedelta(hours=expiry_hours)
            )
            
            sas_url = f"{blob_client.url}?{sas_token}"
            logger.info("Generated SAS URL for blob: %s", blob_name)
            return sas_url
            
        except Exception as e:
            logger.error(f"Failed to generate SAS URL for {blob_name}: {e}")
            raise
    
    async def generate_scoped_sas(
        self,
        blob_name: str,
        permissions: str = "r",
        expiry_minutes: int = 15,
    ) -> str:
        """Generate a short-lived, narrowly-scoped SAS token for a single blob.

        Used for defense-in-depth when injecting session files into a sandbox
        (read-only, specific blob, short expiry).
        """
        await self.initialize()

        try:
            blob_client = self._container_client.get_blob_client(blob_name)

            if self.connection_string:
                conn_parts = dict(
                    part.split("=", 1) for part in self.connection_string.split(";") if "=" in part
                )
                account_name = conn_parts.get("AccountName")
                account_key = conn_parts.get("AccountKey")

                if not account_name or not account_key:
                    raise ValueError("Cannot extract credentials from connection string")

                sas_token = generate_blob_sas(
                    account_name=account_name,
                    container_name=self.container_name,
                    blob_name=blob_name,
                    account_key=account_key,
                    permission=BlobSasPermissions.from_string(permissions),
                    expiry=datetime.utcnow() + timedelta(minutes=expiry_minutes),
                )
            else:
                from azure.storage.blob import UserDelegationKey
                from azure.identity.aio import DefaultAzureCredential as AsyncDefaultCred
                from azure.storage.blob.aio import BlobServiceClient as AsyncBlobService

                credential = AsyncDefaultCred()
                svc = AsyncBlobService(
                    account_url=f"https://{self.account_name}.blob.core.windows.net",
                    credential=credential,
                )
                delegation_key = await svc.get_user_delegation_key(
                    key_start_time=datetime.utcnow(),
                    key_expiry_time=datetime.utcnow() + timedelta(minutes=expiry_minutes + 5),
                )
                from azure.storage.blob import generate_blob_sas as _gen
                sas_token = _gen(
                    account_name=self.account_name,
                    container_name=self.container_name,
                    blob_name=blob_name,
                    user_delegation_key=delegation_key,
                    permission=BlobSasPermissions.from_string(permissions),
                    expiry=datetime.utcnow() + timedelta(minutes=expiry_minutes),
                )
                await credential.close()
                await svc.close()

            sas_url = f"{blob_client.url}?{sas_token}"
            logger.info(
                "Generated scoped SAS for %s (permissions=%s, expiry=%dm)",
                blob_name, permissions, expiry_minutes,
            )
            return sas_url

        except Exception as e:
            logger.error("Failed to generate scoped SAS for %s: %s", blob_name, e)
            raise

    async def copy_blob(
        self,
        source_blob_name: str,
        destination_blob_name: str,
        destination_container: Optional[str] = None
    ) -> None:
        """
        Copy blob within or across containers.
        
        Args:
            source_blob_name: Source blob name
            destination_blob_name: Destination blob name
            destination_container: Destination container (uses same if not specified)
        """
        await self.initialize()
        
        try:
            source_blob = self._container_client.get_blob_client(source_blob_name)
            
            if destination_container and destination_container != self.container_name:
                dest_container_client = self._blob_service_client.get_container_client(
                    destination_container
                )
                dest_blob = dest_container_client.get_blob_client(destination_blob_name)
            else:
                dest_blob = self._container_client.get_blob_client(destination_blob_name)
            
            await dest_blob.start_copy_from_url(source_blob.url)
            logger.info("Copied blob from %s to %s", source_blob_name, destination_blob_name)
            
        except Exception as e:
            logger.error(f"Failed to copy blob {source_blob_name}: {e}")
            raise
    
    async def update_blob_metadata(
        self,
        blob_name: str,
        metadata: Dict[str, str]
    ) -> None:
        """
        Update blob metadata.
        
        Args:
            blob_name: Name of the blob
            metadata: Metadata to update
        """
        await self.initialize()
        
        try:
            blob_client = self._container_client.get_blob_client(blob_name)
            await blob_client.set_blob_metadata(metadata)
            
            logger.info("Updated metadata for blob: %s", blob_name)
            
        except ResourceNotFoundError:
            logger.error(f"Blob not found: {blob_name}")
            raise
        except Exception as e:
            logger.error(f"Failed to update blob metadata {blob_name}: {e}")
            raise
    
    async def get_container_properties(self) -> Dict[str, Any]:
        """
        Get container properties.
        
        Returns:
            Dictionary of container properties
        """
        await self.initialize()
        
        try:
            properties = await self._container_client.get_container_properties()
            
            return {
                "name": self.container_name,
                "created_at": properties.get("creation_time"),
                "last_modified": properties.get("last_modified"),
                "etag": properties.get("etag"),
                "metadata": properties.get("metadata", {})
            }
            
        except Exception as e:
            logger.error(f"Failed to get container properties: {e}")
            raise
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

