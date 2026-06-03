"""
Embedding generation utilities for RAG using LangChain.

All embedding requests are routed through the GenAI Shared Service proxy.
"""
import logging
import asyncio
from typing import List, Optional
from core.exceptions import EmbeddingAPIException, RateLimitException, TimeoutException
from utils.retry import with_retry
from app.config.settings import settings
from config.keyvault import cfg
from domain.entities.knowledge_base import EmbeddingModel

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Client for generating embeddings through the GenAI proxy."""

    def __init__(
        self,
        model: str = EmbeddingModel.AZURE_ADA_002.api_model_id,
        api_key: Optional[str] = None,
        azure_endpoint: Optional[str] = None
    ):
        """
        Initialize embedding client via GenAI proxy.

        Args:
            model: GenAI proxy model ID (e.g. "azure.text-embedding-ada-002").
                   Callers should use ``EmbeddingModel.<member>.api_model_id``.
            api_key: Ignored (kept for signature compat); uses GENAI_PROXY_API_KEY.
            azure_endpoint: Ignored (kept for signature compat); uses GENAI_PROXY_URL.
        """
        self.model = model

        genai_proxy_url = cfg.GENAI_PROXY_URL
        genai_proxy_api_key = cfg.GENAI_PROXY_API_KEY

        if not genai_proxy_url or not genai_proxy_api_key:
            logger.error("GenAI proxy not configured — GENAI_PROXY_URL or GENAI_PROXY_API_KEY missing")
            self.embeddings = None
            return

        self.api_key = genai_proxy_api_key

        try:
            from langchain_openai import OpenAIEmbeddings

            proxy_model = model if any(model.startswith(p) for p in ['azure.', 'vertex_ai.', 'bedrock.', 'openai.']) else f"azure.{model}"

            self.embeddings = OpenAIEmbeddings(
                model=proxy_model,
                openai_api_key=genai_proxy_api_key,
                openai_api_base=genai_proxy_url
            )
            logger.debug("Initialized embeddings via GenAI proxy: %s", proxy_model)
        except Exception as e:
            logger.error("Failed to initialize GenAI proxy embeddings: %s", e)
            self.embeddings = None

    @with_retry(max_retries=3, initial_delay=1.0, exceptions=(Exception,))
    async def create_embeddings(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        max_concurrent_batches: int = 5
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts using LangChain with parallel batch processing.

        Args:
            texts: List of text strings to embed
            batch_size: Number of texts per batch (defaults to settings.EMBEDDING_BATCH_SIZE)
            max_concurrent_batches: Maximum number of batches to process concurrently

        Returns:
            List of embedding vectors
        """
        if batch_size is None:
            batch_size = settings.EMBEDDING_BATCH_SIZE

        if not self.embeddings:
            raise ValueError(
                "Embeddings client not initialized. "
                "Set GENAI_PROXY_URL and GENAI_PROXY_API_KEY in your .env file."
            )

        try:
            from app.llm.langfuse_emit import record_embedding_generation

            if len(texts) <= batch_size:
                embeddings = await record_embedding_generation(
                    model=self.model,
                    text_count=len(texts),
                    invoke=lambda: self.embeddings.aembed_documents(texts),
                )
                logger.debug("Generated %d embeddings in single batch", len(embeddings))
                return embeddings

            batches = [
                texts[i:i + batch_size]
                for i in range(0, len(texts), batch_size)
            ]

            logger.debug(
                "Processing %d texts in %d batches (batch_size=%d, max_concurrent=%d)",
                len(texts), len(batches), batch_size, max_concurrent_batches,
            )

            all_embeddings = []

            for batch_group_idx in range(0, len(batches), max_concurrent_batches):
                batch_group = batches[batch_group_idx:batch_group_idx + max_concurrent_batches]
                tasks = [
                    self._embed_batch(batch, batch_group_idx + idx)
                    for idx, batch in enumerate(batch_group)
                ]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                for idx, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        batch_idx = batch_group_idx + idx
                        logger.error("Batch %d/%d failed: %s", batch_idx + 1, len(batches), result)
                        all_embeddings.extend([None] * len(batch_group[idx]))
                    else:
                        all_embeddings.extend(result)

            successful = len([e for e in all_embeddings if e is not None])
            logger.debug("Generated %d embeddings (%d successful)", len(all_embeddings), successful)
            return all_embeddings

        except Exception as e:
            logger.error("Failed to generate embeddings: %s", e)
            raise EmbeddingAPIException(str(e))

    async def _embed_batch(self, texts: List[str], batch_idx: int) -> List[List[float]]:
        """Embed a single batch of texts."""
        from app.llm.langfuse_emit import record_embedding_generation

        logger.debug("Processing batch %d (%d texts)", batch_idx + 1, len(texts))
        embeddings = await record_embedding_generation(
            model=self.model,
            text_count=len(texts),
            invoke=lambda: self.embeddings.aembed_documents(texts),
            operation=f"embedding_batch_{batch_idx + 1}",
        )
        logger.debug("Batch %d completed (%d embeddings)", batch_idx + 1, len(embeddings))
        return embeddings

    @with_retry(max_retries=3, initial_delay=1.0, exceptions=(Exception,))
    async def create_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        try:
            from app.llm.langfuse_emit import record_embedding_generation

            embedding = await record_embedding_generation(
                model=self.model,
                text_count=1,
                invoke=lambda: self.embeddings.aembed_query(text),
                operation="embedding_query",
            )
            return embedding
        except Exception as e:
            logger.error("Failed to generate embedding: %s", e)
            raise EmbeddingAPIException(str(e))

    @staticmethod
    def get_dimension(model: str) -> int:
        """Get embedding dimension for a model.

        Accepts either an EmbeddingModel enum value (e.g. "azure_ada_002")
        or a proxy API ID (e.g. "azure.text-embedding-ada-002").
        """
        for member in EmbeddingModel:
            if model in (member.value, member.api_model_id):
                return member.dimension
        return settings.EMBEDDING_DIM_DEFAULT
