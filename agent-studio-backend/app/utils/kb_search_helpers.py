"""
Helper functions for knowledge base search operations.

Contains reusable logic for embedding generation, search execution, and citation building.
"""

from typing import Dict, Any, Optional, List
import logging
from app.config.settings import settings
from domain.entities.knowledge_base import EmbeddingModel

logger = logging.getLogger(__name__)


async def generate_query_embedding(
    query: str,
    search_method: str,
    kb,
    embedding_client_class
) -> Optional[List[float]]:
    """
    Generate query embedding if needed for the search method.
    
    Args:
        query: Search query
        search_method: Search method (semantic, bm25, hybrid)
        kb: Knowledge base entity
        embedding_client_class: Class to create embedding client
        
    Returns:
        Query vector or None if not needed
    """
    # Generate embeddings ONLY if needed (semantic or hybrid)
    query_vector = None
    if search_method in ("semantic", "hybrid"):
        embedding_enum = (
            kb.embedding_model
            if isinstance(kb.embedding_model, EmbeddingModel)
            else EmbeddingModel.from_value_or_default(str(kb.embedding_model))
        )
        actual_model = embedding_enum.api_model_id
        logger.debug("🔍 Using KB embedding model: %s -> %s", embedding_enum.value, actual_model)

        embedding_client = embedding_client_class(model=actual_model)
        query_embeddings = await embedding_client.create_embeddings([query])
        if not query_embeddings:
            raise ValueError("Failed to generate query embedding")
        
        query_vector = query_embeddings[0]
        logger.debug("✅ Generated query embedding with %d dimensions", len(query_vector))
        logger.debug("🔍 EMBEDDING DEBUG - query: '%s', first 5 values: %s", query[:60], query_vector[:5])
    else:
        logger.debug("ℹ️  Skipping embedding generation for BM25-only search")
    
    return query_vector


async def execute_kb_search(
    search_method: str,
    kb_repo,
    kb,
    kb_id: str,
    query: str,
    query_vector: Optional[List[float]],
    top_k: int,
    enable_reranking: bool,
    metadata_filters: Optional[list] = None,
    metadata_field_types: Optional[dict] = None,
    document_id: Optional[str] = None,
) -> List:
    """
    Execute knowledge base search using the specified method.

    ``metadata_filters`` is an optional list of ``{field, operator, value}``
    dicts that are applied as AND conditions on the JSONB metadata column.
    ``metadata_field_types`` maps field names to their declared type so the
    repository can apply the correct SQL cast.
    ``document_id`` optionally restricts the search to a single document.
    """
    result_limit = top_k * settings.KB_RERANK_MULTIPLIER if enable_reranking else top_k

    meta_kw: dict = {}
    if metadata_filters:
        meta_kw["metadata_filters"] = metadata_filters
        meta_kw["metadata_field_types"] = metadata_field_types
    if document_id:
        meta_kw["document_id"] = document_id

    if search_method == "bm25":
        logger.debug("🔎 Executing BM25 search on table '%s' with query: '%s'",
                   kb.chunk_table_name, query[:100])
        results = await kb_repo.bm25_search(
            table_name=kb.chunk_table_name,
            kb_id=kb_id,
            query_text=query,
            limit=result_limit,
            **meta_kw,
        )
        logger.debug("✅ BM25 search returned %d results", len(results) if results else 0)
    elif search_method == "hybrid":
        results = await kb_repo.hybrid_search(
            table_name=kb.chunk_table_name,
            kb_id=kb_id,
            query_text=query,
            query_embedding=query_vector,
            limit=result_limit,
            semantic_weight=settings.KB_HYBRID_SEMANTIC_WEIGHT,
            rrf_k=settings.KB_HYBRID_RRF_K,
            **meta_kw,
        )
    else:
        results = await kb_repo.similarity_search(
            table_name=kb.chunk_table_name,
            kb_id=kb_id,
            query_embedding=query_vector,
            limit=result_limit,
            use_sphere=False,
            **meta_kw,
        )

    return results


async def apply_reranking(
    results: List,
    query: str,
    enable_reranking: bool,
    reranker_model: str,
    top_k: int
) -> List:
    """
    Apply reranking to search results if enabled.
    
    Args:
        results: Search results
        query: Original query
        enable_reranking: Whether to rerank
        reranker_model: Reranker model name
        top_k: Number of top results to keep
        
    Returns:
        Reranked results (or original if reranking disabled)
    """
    if enable_reranking and results:
        from app.utils.reranker import get_reranker
        reranker = get_reranker(reranker_model)
        results = await reranker.rerank(query, results, top_k=top_k)
        logger.debug("✅ Reranked %d results to top %d", len(results), top_k)
    
    return results


def build_citations_and_response(
    results: List,
    kb_id: str,
    kb_name: str,
    query: str
) -> Dict[str, Any]:
    """
    Build citations and formatted response from search results.

    Respects ``settings.KB_MAX_SEARCH_CHARS`` — stops adding chunks once
    the total character budget is exhausted so downstream LLM context
    stays manageable.
    """
    if not results:
        return {
            "text": f"No relevant information found in the '{kb_name}' knowledge base for query: '{query}'",
            "citations": []
        }

    max_chars = settings.KB_MAX_SEARCH_CHARS
    max_chunk = settings.KB_MAX_CHUNK_CHARS
    total_chars = 0

    citations = []
    formatted_chunks = []
    citation_number = 1

    for result in results:
        chunk_id = result[0]
        chunk_text = result[3]
        distance = result[7]
        relevance_score = 1 / (1 + distance)

        if len(chunk_text) > max_chunk:
            chunk_text = chunk_text[:max_chunk] + "…"

        chunk_len = len(chunk_text)
        if total_chars + chunk_len > max_chars and formatted_chunks:
            logger.debug(
                "✂️ KB search char cap reached (%d/%d) — skipping remaining %d chunks",
                total_chars, max_chars, len(results) - (citation_number - 1),
            )
            break

        chunk_metadata = result[5] if len(result) > 5 else None
        if chunk_metadata and isinstance(chunk_metadata, str):
            try:
                import json as _json
                chunk_metadata = _json.loads(chunk_metadata)
            except (ValueError, TypeError):
                chunk_metadata = None

        citation = {
            "citation_number": citation_number,
            "chunk_id": chunk_id,
            "kb_id": kb_id,
            "relevance_score": round(relevance_score, 4),
            "chunk_text": chunk_text,
            "chunk_metadata": chunk_metadata,
        }
        citations.append(citation)
        formatted_chunks.append(f"{chunk_text} [{citation_number}]")

        total_chars += chunk_len
        citation_number += 1

    response_text = "\n\n".join(formatted_chunks)

    logger.info(
        "✅ KB search returned %d results with %d citations (%d chars / %d max)",
        len(results), len(citations), total_chars, max_chars,
    )

    return {
        "text": response_text,
        "citations": citations,
    }

