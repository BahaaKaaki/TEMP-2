"""
Knowledge Base RAG tool for agents.
Allows agents to search knowledge bases and retrieve relevant context.
"""
from typing import Optional, Dict, Any, List
import logging
import re

try:
    from pydantic import BaseModel, Field
except ImportError:
    from pydantic.v1 import BaseModel, Field

from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.db.pgsql import get_write_db
from app.config.settings import settings
from .kb_search_helpers import (
    generate_query_embedding,
    execute_kb_search,
    apply_reranking,
    build_citations_and_response
)

logger = logging.getLogger(__name__)


class MetadataFilterItem(BaseModel):
    field: str = Field(..., description="Metadata field name")
    operator: str = Field(..., description="Comparison operator: eq, neq, gt, gte, lt, lte, like, max, min")
    value: Optional[str] = Field(None, description="Value to compare against (not needed for max/min)")


class KBSearchInput(BaseModel):
    """Input schema for KB search tool."""
    query: str = Field(..., description="The search query to find relevant information")
    top_k: Optional[int] = Field(
        default=None, 
        description=f"Number of results to return (default: {settings.KB_DEFAULT_TOP_K})"
    )
    document_name: Optional[str] = Field(
        default=None,
        description="Optional file name to restrict the search to a single document (e.g. 'report.pdf'). Leave empty to search all documents.",
    )
    metadata_filters: Optional[List[MetadataFilterItem]] = Field(
        default=None,
        description="Optional metadata filters applied as AND conditions on search results",
    )


class KBSearchTool:
    """
    Tool that enables agents to search a knowledge base for relevant context.
    """
    
    def __init__(
        self, 
        kb_id: str, 
        kb_name: str = None, 
        embedding_model: str = "azure_ada_002",
        search_method: str = "semantic",
        enable_reranking: bool = False,
        reranker_model: str = None,
        metadata_schema: Optional[list] = None,
    ):
        self.kb_id = kb_id
        self.kb_name = kb_name or kb_id
        self.embedding_model = embedding_model
        self.search_method = search_method
        self.enable_reranking = enable_reranking
        self.reranker_model = reranker_model or settings.KB_RERANKER_MODEL
        self.metadata_schema = metadata_schema or []
        self._field_type_map: Dict[str, str] = {
            f["name"]: f["type"] for f in self.metadata_schema
        } if self.metadata_schema else {}

        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', self.kb_name.lower())
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')
        self.name = f"search_{sanitized}"[:128]

        method_desc = {
            "semantic": "semantic vector search",
            "bm25": "keyword-based BM25 search",
            "hybrid": "hybrid search (combining semantic and keyword matching)"
        }.get(search_method, "search")

        rerank_desc = " Results are reranked for optimal relevance." if enable_reranking else ""

        self.description = (
            f"Search the '{self.kb_name}' knowledge base using {method_desc}.{rerank_desc} "
            "Use this when you need to retrieve specific information from uploaded documents. "
            f"This tool searches only the {self.kb_name} knowledge base."
        )

        if self.metadata_schema:
            self.description += self._build_metadata_desc()
    
    def _build_metadata_desc(self) -> str:
        """Build a human-readable description of available metadata filters."""
        type_operators = {
            "string": "eq, like",
            "number": "eq, neq, gt, gte, lt, lte, max (highest), min (lowest)",
            "date": "eq, gt, gte, lt, lte, max (latest), min (earliest)",
            "boolean": "eq",
        }
        lines = [
            "\n\nAvailable metadata filters (optional, AND conditions).",
            "Use max/min to find rows with the highest/lowest value (no value needed).",
            "Use gt/lt/gte/lte with a value for range comparisons (dates as YYYY-MM-DD).",
        ]
        for f in self.metadata_schema:
            ops = type_operators.get(f["type"], "eq")
            desc = f.get("description") or ""
            if desc:
                desc = f" {desc}."
            lines.append(f"- {f['name']} ({f['type']}, {f['scope']}): Operators: {ops}.{desc}")
        return "\n".join(lines)

    async def search(
        self, query: str, top_k: Optional[int] = None,
        document_name: Optional[str] = None,
        metadata_filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Search knowledge base for relevant chunks."""
        if top_k is None:
            top_k = settings.KB_DEFAULT_TOP_K

        raw_filters = None
        if metadata_filters:
            raw_filters = [
                mf.dict() if hasattr(mf, "dict") else (mf.model_dump() if hasattr(mf, "model_dump") else mf)
                for mf in metadata_filters
            ]

        try:
            from app.utils.embedding import EmbeddingClient

            async for db_session in get_write_db():
                kb_repo = KnowledgeBaseRepository(db_session)

                kb = await kb_repo.get_by_id(self.kb_id)
                if not kb:
                    logger.warning("Knowledge base %s not found", self.kb_id)
                    return {"text": f"Error: Knowledge base '{self.kb_name}' not found.", "citations": []}

                # Resolve document_name to document_id for filtering
                doc_id = None
                if document_name:
                    doc_id = await kb_repo.find_document_id_by_name(self.kb_id, document_name)
                    if doc_id:
                        logger.debug("🔍 Filtering search to document '%s' (id=%s)", document_name, doc_id)
                    else:
                        logger.warning("⚠️ Document '%s' not found in KB, searching all documents", document_name)

                logger.debug(
                    "🔍 Using search method: %s, reranking: %s, metadata_filters: %s, document_filter: %s",
                    self.search_method, self.enable_reranking,
                    len(raw_filters) if raw_filters else 0,
                    document_name or "none",
                )

                query_vector = await generate_query_embedding(
                    query, self.search_method, kb, EmbeddingClient
                )

                results = await execute_kb_search(
                    self.search_method, kb_repo, kb, self.kb_id,
                    query, query_vector, top_k, self.enable_reranking,
                    metadata_filters=raw_filters,
                    metadata_field_types=self._field_type_map,
                    document_id=doc_id,
                )

                results = await apply_reranking(
                    results, query, self.enable_reranking,
                    self.reranker_model, top_k,
                )

                return build_citations_and_response(results, self.kb_id, self.kb_name, query)

        except Exception as e:
            logger.error("KB search tool error: %s", e, exc_info=True)
            return {
                "text": f"Error searching knowledge base '{self.kb_name}': {str(e)}",
                "citations": [],
            }

    def as_langchain_tool(self):
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            from langchain.tools import StructuredTool

        return StructuredTool.from_function(
            name=self.name,
            description=self.description,
            func=self.search,
            coroutine=self.search,
            args_schema=KBSearchInput,
            return_direct=False,
        )

    def as_openai_function(self) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "query": {
                "type": "string",
                "description": "The search query to find relevant information",
            },
            "top_k": {
                "type": "integer",
                "description": f"Number of results to return (default: {settings.KB_DEFAULT_TOP_K})",
                "default": settings.KB_DEFAULT_TOP_K,
            },
            "document_name": {
                "type": "string",
                "description": "Optional file name to restrict the search to a single document (e.g. 'report.pdf'). Omit to search all documents.",
            },
        }
        if self.metadata_schema:
            props["metadata_filters"] = {
                "type": "array",
                "description": (
                    "Optional metadata filters (AND conditions). "
                    "Use max/min for highest/lowest value (no value needed). "
                    "Use gt/lt/gte/lte with a value for range comparisons."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "Metadata field name"},
                        "operator": {
                            "type": "string",
                            "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "like", "max", "min"],
                        },
                        "value": {
                            "type": "string",
                            "description": "Value to compare against (omit for max/min)",
                        },
                    },
                    "required": ["field", "operator"],
                },
            }
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": ["query"],
            },
        }


async def create_kb_tool(
    kb_id: str, 
    embedding_model: str = "azure_ada_002",
    search_method: str = "semantic",
    enable_reranking: bool = False,
    reranker_model: Optional[str] = None
) -> Optional[KBSearchTool]:
    """
    Factory function to create KB search tool.
    
    Args:
        kb_id: KB ID to enable search for
        embedding_model: Embedding model to use
        search_method: Search method (semantic, bm25, hybrid)
        enable_reranking: Whether to rerank results
        reranker_model: Cross-encoder model for reranking
        
    Returns:
        KBSearchTool instance or None if KB not found
    """
    if not kb_id:
        return None
    
    # Fetch KB details to get the name
    from app.db.pgsql import get_write_db
    from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
    
    result_tool = None
    
    try:
        async for db_session in get_write_db():
            try:
                kb_repo = KnowledgeBaseRepository(db_session)
                kb = await kb_repo.get_by_id(kb_id)
                if kb:
                    logger.info("✅ Found KB '%s' (ID: %s)", kb.name, kb_id)
                    meta_schema_raw = (
                        [f.to_dict() for f in kb.metadata_schema]
                        if kb.metadata_schema else None
                    )
                    result_tool = KBSearchTool(
                        kb_id=kb_id,
                        kb_name=kb.name,
                        embedding_model=embedding_model,
                        search_method=search_method,
                        enable_reranking=enable_reranking,
                        reranker_model=reranker_model,
                        metadata_schema=meta_schema_raw,
                    )
                    logger.info("✅ Created KB tool: %s (method=%s, rerank=%s)", 
                               result_tool.name, search_method, enable_reranking)
                else:
                    logger.warning("KB %s not found when creating tool", kb_id)
            finally:
                break  # Only need one DB session
        
    except Exception as e:
        logger.error("Error creating KB tool: %s", e, exc_info=True)
        return None
    
    if result_tool:
        logger.debug("✅ Returning KB tool: %s", result_tool.name)
        return result_tool
    else:
        logger.error("Failed to create KB tool for KB ID: %s", kb_id)
        return None


async def create_kb_researcher_tool(
    kb_id: str,
    embedding_model: str = "azure_ada_002",
    search_method: str = "semantic",
    enable_reranking: bool = False,
    reranker_model: Optional[str] = None,
    task_instructions: str = "",
    output_schema: str = "",
    metadata_schema: Optional[list] = None,
):
    """Factory function to create the agentic KB researcher tool.

    Returns a ``KBResearcherTool`` that performs query decomposition,
    CRAG-style relevance grading, and progressive memo synthesis.
    Falls back to ``None`` if the KB is not found.

    When ``task_instructions`` and/or ``output_schema`` are provided, the
    researcher uses them to plan comprehensive sub-queries that cover all
    required output sections in a single research pass.
    """
    if not kb_id:
        return None

    from app.utils.kb_researcher import KBResearcherTool
    from app.db.pgsql import get_write_db
    from app.repositories.knowledge_base_repository import KnowledgeBaseRepository

    result_tool = None
    try:
        async for db_session in get_write_db():
            try:
                kb_repo = KnowledgeBaseRepository(db_session)
                kb = await kb_repo.get_by_id(kb_id)
                if kb:
                    logger.info("✅ Found KB '%s' (ID: %s) for researcher", kb.name, kb_id)
                    meta_schema = metadata_schema
                    if meta_schema is None and kb.metadata_schema:
                        meta_schema = [f.to_dict() for f in kb.metadata_schema]
                    result_tool = KBResearcherTool(
                        kb_id=kb_id,
                        kb_name=kb.name,
                        embedding_model=embedding_model,
                        search_method=search_method,
                        enable_reranking=enable_reranking,
                        reranker_model=reranker_model,
                        task_instructions=task_instructions,
                        output_schema=output_schema,
                        metadata_schema=meta_schema,
                    )
                    logger.info(
                        "✅ Created KB researcher tool: %s (method=%s, rerank=%s)",
                        result_tool.name, search_method, enable_reranking,
                    )
                else:
                    logger.warning("KB %s not found when creating researcher tool", kb_id)
            finally:
                break
    except Exception as e:
        logger.error("Error creating KB researcher tool: %s", e, exc_info=True)
        return None

    if result_tool:
        logger.debug("✅ Returning KB researcher tool: %s", result_tool.name)
        return result_tool
    else:
        logger.error("Failed to create KB researcher tool for KB ID: %s", kb_id)
        return None

