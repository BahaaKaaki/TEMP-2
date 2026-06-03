"""
Knowledge Base Researcher with multi-query decomposition.

Architecture (aligned with OpenAI File Search / Anthropic RAG patterns):
1. Decomposes complex questions into focused sub-queries (1 LLM call)
2. Searches the KB for each sub-query in parallel (0 LLM calls)
3. Deduplicates, scores, and returns actual chunk text with citations

The main LLM receives the original chunk text — no lossy intermediate
summarisation or grading. The most capable model in the pipeline does
the reasoning, not a lightweight grader.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.settings import settings
from app.tracing import TraceSpan
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.db.pgsql import get_write_db
from .kb_search_helpers import (
    generate_query_embedding,
    execute_kb_search,
    apply_reranking,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal LLM helper (used only for query decomposition)
# ---------------------------------------------------------------------------

def _get_researcher_llm():
    """Return the lightweight LLM used for query decomposition."""
    from app.config.llm_config import LLMClientManager
    return LLMClientManager.get_client_for_binding(
        "settings.kb_researcher_grader",
        temperature=0.0,
        max_tokens=1024,
        llm_role="kb_grader",
    )


async def _llm_json_call(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """Make a single LLM call and parse the response as JSON."""
    llm = _get_researcher_llm()
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    content = response.content.strip()
    return _parse_json_response(content)


def _parse_json_response(content: str) -> Dict[str, Any]:
    """Extract a JSON object from an LLM response, handling markdown fences."""
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if match:
        content = match.group(1).strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    brace = content.find("{")
    if brace != -1:
        depth, start = 0, brace
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return {}


# ---------------------------------------------------------------------------
# Prompt templates (decomposition only)
# ---------------------------------------------------------------------------

DECOMPOSE_SYSTEM = """\
You decompose a user's research question into focused sub-queries that can
each be answered by searching a document knowledge base.

Rules:
- Return 1-{max_sub} sub-queries. Prefer fewer when the question is simple.
- Each sub-query should target a distinct piece of evidence.
- Sub-queries must be self-contained (understandable without the others).
- Write sub-queries as short, keyword-rich search phrases for best retrieval.
- For simple factual questions, return just 1 sub-query (the original).

Respond with ONLY a JSON object (no markdown, no extra text):
{{"sub_queries": ["sub-query 1", "sub-query 2", ...]}}
"""

DECOMPOSE_WITH_CONTEXT_SYSTEM = """\
You are a research planner. You must generate ALL the sub-queries needed to
gather comprehensive evidence from a document knowledge base in ONE shot.

You are given:
1. The agent's task description
2. The required output schema (the sections/fields that need evidence)
3. A research question or topic

Your job: produce sub-queries that collectively cover EVERY section of the
output schema that requires evidence from documents. The agent will NOT get
a second chance to search -- this is the only research pass.

Rules:
- Return {max_sub} sub-queries maximum. Use as many as needed to cover the schema.
- Each sub-query should target a specific section or data point in the schema.
- Sub-queries must be self-contained search queries (short, keyword-rich).
- Avoid overly specific queries that won't match documents -- keep them broad enough to find results.
- Do NOT generate sub-queries for information the agent can reason about without evidence.

Respond with ONLY a JSON object (no markdown, no extra text):
{{"sub_queries": ["sub-query 1", "sub-query 2", ...]}}
"""


# ---------------------------------------------------------------------------
# Core researcher
# ---------------------------------------------------------------------------

class KBResearcher:
    """Multi-query KB researcher.

    Decomposes a question into sub-queries, searches in parallel, then
    deduplicates and returns the actual chunk text to the main LLM.

    Wrapped by ``KBResearcherTool`` for LangChain compatibility.
    """

    def __init__(
        self,
        kb_id: str,
        kb_name: str,
        search_method: str = "semantic",
        enable_reranking: bool = False,
        reranker_model: str = None,
        task_instructions: str = "",
        output_schema: str = "",
    ):
        self.kb_id = kb_id
        self.kb_name = kb_name
        self.search_method = search_method
        self.enable_reranking = enable_reranking
        self.reranker_model = reranker_model or settings.KB_RERANKER_MODEL
        self.task_instructions = task_instructions
        self.output_schema = output_schema

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def research(
        self,
        question: str,
        top_k: int = None,
        metadata_filters: Optional[list] = None,
        metadata_field_types: Optional[dict] = None,
        document_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the full research loop and return ``{"text": ..., "citations": [...]}``."""
        top_k = top_k or settings.KB_DEFAULT_TOP_K
        t0 = time.time()

        async with TraceSpan(
            "kb_research",
            label=f"KB Researcher: {self.kb_name}",
            payload={
                "kb_id": self.kb_id,
                "kb_name": self.kb_name,
                "top_k": top_k,
                "document_name": document_name,
                "question": question,
            },
        ) as span:
            doc_id = None
            if document_name:
                doc_id = await self._resolve_document_name(document_name)

            sub_queries = await self._decompose_query(question)
            logger.debug(
                "KB Researcher: decomposed into %d sub-queries for '%s'",
                len(sub_queries), question[:80],
            )

            async with TraceSpan(
                "kb_search",
                label="Parallel KB Search",
                payload={"sub_query_count": len(sub_queries), "top_k": top_k},
            ) as search_span:
                all_chunks = await self._search_all(
                    sub_queries, top_k,
                    metadata_filters=metadata_filters,
                    metadata_field_types=metadata_field_types,
                    document_id=doc_id,
                )
                search_span.add_payload(retrieved_chunks=len(all_chunks))

            logger.debug(
                "KB Researcher: retrieved %d total chunks across %d sub-queries",
                len(all_chunks), len(sub_queries),
            )

            output = self._deduplicate_and_format(all_chunks, question)
            elapsed = time.time() - t0
            span.add_payload(
                sub_query_count=len(sub_queries),
                citation_count=len(output["citations"]),
                output_chars=len(output["text"]),
            )

            logger.debug(
                "KB Researcher complete: %d sub-queries, %d unique chunks, "
                "%d citations, %d chars, %.1fs elapsed",
                len(sub_queries),
                len(output["citations"]),
                len(output["citations"]),
                len(output["text"]),
                elapsed,
            )

            await self._dump_debug_log(question, sub_queries, all_chunks, output, elapsed)
            return output

    async def _resolve_document_name(self, document_name: str) -> Optional[str]:
        """Resolve a file name to a document ID in this KB."""
        from app.repositories.knowledge_base_repository import KnowledgeBaseRepository as _KBRepo

        try:
            async for db_session in get_write_db():
                repo = _KBRepo(db_session)
                doc_id = await repo.find_document_id_by_name(self.kb_id, document_name)
                if doc_id:
                    logger.debug(
                        "🔍 Researcher: resolved document '%s' → id=%s",
                        document_name, doc_id,
                    )
                else:
                    logger.warning(
                        "⚠️ Researcher: document '%s' not found in KB %s, "
                        "searching all documents",
                        document_name, self.kb_id,
                    )
                return doc_id
        except Exception as e:
            logger.warning("Failed to resolve document_name '%s': %s", document_name, e)
            return None

    # ------------------------------------------------------------------
    # Step 1: Query decomposition
    # ------------------------------------------------------------------

    async def _decompose_query(self, question: str) -> List[str]:
        max_sub = settings.KB_RESEARCHER_MAX_SUB_QUERIES

        if self.task_instructions or self.output_schema:
            system = DECOMPOSE_WITH_CONTEXT_SYSTEM.format(max_sub=max_sub)
            user_parts = [f"## Research Topic\n{question}"]
            if self.task_instructions:
                user_parts.append(
                    f"## Task Description\n{self.task_instructions[:2000]}"
                )
            if self.output_schema:
                user_parts.append(
                    f"## Required Output Schema\n{self.output_schema[:3000]}"
                )
            user = "\n\n".join(user_parts)
        else:
            system = DECOMPOSE_SYSTEM.format(max_sub=max_sub)
            user = f"Research question: {question}"

        data = await _llm_json_call(system, user)
        sub_queries = data.get("sub_queries", [question])

        if not sub_queries or not isinstance(sub_queries, list):
            return [question]
        return sub_queries[:max_sub]

    # ------------------------------------------------------------------
    # Step 2: Parallel search across all sub-queries
    # ------------------------------------------------------------------

    async def _search_all(
        self,
        sub_queries: List[str],
        top_k: int,
        metadata_filters: Optional[list] = None,
        metadata_field_types: Optional[dict] = None,
        document_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search every sub-query in parallel, return flat list of chunk dicts."""

        async def _search_one(query: str) -> List[Dict[str, Any]]:
            chunks = await self._raw_search(
                query, top_k,
                metadata_filters=metadata_filters,
                metadata_field_types=metadata_field_types,
                document_id=document_id,
            )
            for c in chunks:
                c["sub_query"] = query
            return chunks

        results = await asyncio.gather(*[_search_one(q) for q in sub_queries])
        flat: List[Dict[str, Any]] = []
        for batch in results:
            flat.extend(batch)
        return flat

    # ------------------------------------------------------------------
    # Raw KB search (reuses existing infrastructure)
    # ------------------------------------------------------------------

    async def _raw_search(
        self,
        query: str,
        top_k: int,
        metadata_filters: Optional[list] = None,
        metadata_field_types: Optional[dict] = None,
        document_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a single KB search and return chunk dicts."""
        from app.utils.embedding import EmbeddingClient

        try:
            async for db_session in get_write_db():
                kb_repo = KnowledgeBaseRepository(db_session)
                kb = await kb_repo.get_by_id(self.kb_id)
                if not kb:
                    return []

                query_vector = await generate_query_embedding(
                    query, self.search_method, kb, EmbeddingClient
                )
                results = await execute_kb_search(
                    self.search_method, kb_repo, kb, self.kb_id,
                    query, query_vector, top_k, self.enable_reranking,
                    metadata_filters=metadata_filters,
                    metadata_field_types=metadata_field_types,
                    document_id=document_id,
                )
                results = await apply_reranking(
                    results, query, self.enable_reranking,
                    self.reranker_model, top_k,
                )

                chunks = []
                for row in results:
                    chunk_id = row[0]
                    chunk_text = row[3]
                    chunk_metadata = row[5] if len(row) > 5 else None
                    distance = row[7]
                    relevance_score = 1 / (1 + distance)

                    chunks.append({
                        "chunk_id": chunk_id,
                        "chunk_text": chunk_text,
                        "chunk_metadata": chunk_metadata,
                        "distance": distance,
                        "relevance_score": round(relevance_score, 4),
                    })
                return chunks
        except Exception as e:
            logger.error("KB Researcher raw search error: %s", e, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Step 3: Deduplicate, sort, format
    # ------------------------------------------------------------------

    def _deduplicate_and_format(
        self,
        all_chunks: List[Dict[str, Any]],
        question: str,
    ) -> Dict[str, Any]:
        """Deduplicate chunks by chunk_id, sort by score, format with citations."""
        if not all_chunks:
            return {
                "text": (
                    f"No relevant information found in the '{self.kb_name}' "
                    f"knowledge base for: {question}"
                ),
                "citations": [],
            }

        best: Dict[str, Dict[str, Any]] = {}
        for chunk in all_chunks:
            cid = chunk["chunk_id"]
            if cid not in best or chunk["relevance_score"] > best[cid]["relevance_score"]:
                best[cid] = chunk

        unique_chunks = sorted(
            best.values(), key=lambda c: c["relevance_score"], reverse=True
        )

        threshold = settings.KB_RESEARCHER_SCORE_THRESHOLD
        if threshold and threshold > 0:
            unique_chunks = [
                c for c in unique_chunks if c["relevance_score"] >= threshold
            ]

        max_chars = settings.KB_RESEARCHER_MAX_RESULT_CHARS
        total_chars = 0
        citations: List[Dict[str, Any]] = []
        formatted_chunks: List[str] = []
        citation_number = 1

        for chunk in unique_chunks:
            chunk_text = chunk["chunk_text"]
            chunk_len = len(chunk_text)

            if total_chars + chunk_len > max_chars and formatted_chunks:
                logger.debug(
                    "KB Researcher char cap reached (%d/%d) — keeping %d of %d chunks",
                    total_chars, max_chars, len(formatted_chunks), len(unique_chunks),
                )
                break

            citations.append({
                "citation_number": citation_number,
                "chunk_id": chunk["chunk_id"],
                "kb_id": self.kb_id,
                "relevance_score": chunk["relevance_score"],
                "chunk_text": chunk_text,
                "chunk_metadata": chunk.get("chunk_metadata"),
            })
            formatted_chunks.append(f"{chunk_text} [{citation_number}]")
            total_chars += chunk_len
            citation_number += 1

        response_text = "\n\n".join(formatted_chunks)

        logger.debug(
            "KB Researcher output: %d unique chunks, %d citations, %d chars (max %d)",
            len(unique_chunks), len(citations), total_chars, max_chars,
        )

        return {
            "text": response_text,
            "citations": citations,
        }

    # ------------------------------------------------------------------
    # Debug logging
    # ------------------------------------------------------------------

    async def _dump_debug_log(
        self,
        question: str,
        sub_queries: List[str],
        all_chunks: List[Dict[str, Any]],
        output: Dict[str, Any],
        elapsed: float,
    ) -> None:
        """Write a detailed debug file for inspection (only when LOG_LEVEL=DEBUG)."""
        if settings.LOG_LEVEL.upper() != "DEBUG":
            return
        try:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "logs",
            )
            os.makedirs(log_dir, exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(log_dir, f"kb_logs_{ts}.txt")

            lines: List[str] = []
            lines.append(f"{'=' * 80}")
            lines.append(f"KB RESEARCHER DEBUG LOG — {datetime.utcnow().isoformat()}Z")
            lines.append(f"KB: {self.kb_name} ({self.kb_id})")
            lines.append(f"Question: {question}")
            lines.append(f"Elapsed: {elapsed:.1f}s")
            lines.append(f"Sub-queries: {len(sub_queries)}")
            lines.append(f"Total chunks retrieved: {len(all_chunks)}")
            lines.append(f"Unique citations in output: {len(output['citations'])}")
            lines.append(f"Output text chars: {len(output['text'])}")
            lines.append(f"{'=' * 80}\n")

            for i, sq in enumerate(sub_queries, 1):
                sq_chunks = [c for c in all_chunks if c.get("sub_query") == sq]
                lines.append(f"--- Sub-query {i}: {sq}")
                lines.append(f"    Chunks found: {len(sq_chunks)}")
                for c in sq_chunks:
                    lines.append(
                        f"    chunk_id={c['chunk_id']} "
                        f"score={c['relevance_score']} "
                        f"chars={len(c['chunk_text'])}"
                    )
                lines.append("")

            lines.append(f"\n{'=' * 80}")
            lines.append(f"OUTPUT CITATIONS ({len(output['citations'])})")
            lines.append(f"{'=' * 80}")
            for c in output["citations"]:
                lines.append(
                    f"\n[{c.get('citation_number')}] chunk_id={c.get('chunk_id')} "
                    f"score={c.get('relevance_score')}"
                )
                chunk = c.get("chunk_text", "")
                lines.append(f"CHUNK TEXT ({len(chunk)} chars):")
                lines.append(chunk)

            lines.append(f"\n{'=' * 80}")
            lines.append(f"OUTPUT TEXT ({len(output['text'])} chars)")
            lines.append(f"{'=' * 80}")
            lines.append(output["text"])

            content = "\n".join(lines)
            await asyncio.to_thread(self._write_file, path, content)
            logger.debug("KB Researcher debug log written to %s", path)
        except Exception as exc:
            logger.warning("Failed to write KB debug log: %s", exc)

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


# ---------------------------------------------------------------------------
# LangChain-compatible tool wrapper
# ---------------------------------------------------------------------------

class KBResearcherTool:
    """Drop-in replacement for ``KBSearchTool`` that runs multi-query
    decomposition for broader KB coverage.

    Presents the same interface: ``.search(query)``, ``.as_langchain_tool()``,
    ``.as_openai_function()``, and returns ``{"text": ..., "citations": [...]}``.
    """

    def __init__(
        self,
        kb_id: str,
        kb_name: str = None,
        embedding_model: str = "azure_ada_002",
        search_method: str = "semantic",
        enable_reranking: bool = False,
        reranker_model: str = None,
        task_instructions: str = "",
        output_schema: str = "",
        metadata_schema: Optional[list] = None,
    ):
        self.kb_id = kb_id
        self.kb_name = kb_name or kb_id
        self.embedding_model = embedding_model
        self.search_method = search_method
        self.enable_reranking = enable_reranking
        self.reranker_model = reranker_model or settings.KB_RERANKER_MODEL
        self.task_instructions = task_instructions
        self.output_schema = output_schema
        self.metadata_schema = metadata_schema or []
        self._field_type_map: Dict[str, str] = {
            f["name"]: f["type"] for f in self.metadata_schema
        } if self.metadata_schema else {}

        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', self.kb_name.lower())
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')
        self.name = f"research_{sanitized}"[:128]

        method_desc = {
            "semantic": "semantic vector search",
            "bm25": "keyword-based BM25 search",
            "hybrid": "hybrid search (combining semantic and keyword matching)",
        }.get(search_method, "search")

        self.description = (
            f"Research the '{self.kb_name}' knowledge base using {method_desc} "
            "with multi-query decomposition for broad coverage. "
            "Use this when you need to find specific information from uploaded "
            f"documents in the {self.kb_name} knowledge base. "
            "Returns relevant document chunks with citations."
        )
        if self.metadata_schema:
            self.description += self._build_metadata_desc()

    def _build_metadata_desc(self) -> str:
        type_ops = {
            "string": "eq, like",
            "number": "eq, neq, gt, gte, lt, lte, max (highest), min (lowest)",
            "date": "eq, gt, gte, lt, lte, max (latest), min (earliest) (YYYY-MM-DD)",
            "boolean": "eq",
        }
        lines = [
            "\nAvailable metadata filters (optional AND conditions).",
            "Use max/min to find rows with the highest/lowest value (no value needed).",
            "Use gt/lt/gte/lte with a value for range comparisons (dates as YYYY-MM-DD).",
        ]
        for f in self.metadata_schema:
            ops = type_ops.get(f["type"], "eq")
            desc = f.get("description") or ""
            if desc:
                desc = f" {desc}."
            lines.append(
                f"- {f['name']} ({f['type']}, {f['scope']}): "
                f"Operators: {ops}.{desc}"
            )
        return "\n".join(lines)

    async def search(
        self, query: str, top_k: Optional[int] = None,
        metadata_filters: Optional[list] = None,
        document_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if metadata_filters and isinstance(metadata_filters, list):
            raw = []
            for mf in metadata_filters:
                if isinstance(mf, dict):
                    raw.append(mf)
                elif hasattr(mf, "model_dump"):
                    raw.append(mf.model_dump())
            metadata_filters = raw or None

        researcher = KBResearcher(
            kb_id=self.kb_id,
            kb_name=self.kb_name,
            search_method=self.search_method,
            enable_reranking=self.enable_reranking,
            reranker_model=self.reranker_model,
            task_instructions=self.task_instructions,
            output_schema=self.output_schema,
        )
        return await researcher.research(
            query, top_k,
            metadata_filters=metadata_filters,
            metadata_field_types=self._field_type_map or None,
            document_name=document_name,
        )

    def as_langchain_tool(self):
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            from langchain.tools import StructuredTool

        try:
            from pydantic import BaseModel, Field
        except ImportError:
            from pydantic.v1 import BaseModel, Field

        has_metadata = bool(self.metadata_schema)

        class ResearchInput(BaseModel):
            query: str = Field(
                ..., description="The research question to investigate"
            )
            top_k: Optional[int] = Field(
                default=None,
                description=f"Results per sub-query (default: {settings.KB_DEFAULT_TOP_K})",
            )
            metadata_filters: Optional[list] = Field(
                default=None,
                description=(
                    "Optional metadata filters (AND conditions): "
                    "list of {field, operator, value}"
                ) if has_metadata else "Not available for this KB",
            )

        return StructuredTool.from_function(
            name=self.name,
            description=self.description,
            func=self.search,
            coroutine=self.search,
            args_schema=ResearchInput,
            return_direct=False,
        )

    def as_openai_function(self) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "query": {
                "type": "string",
                "description": "The research question to investigate",
            },
            "top_k": {
                "type": "integer",
                "description": (
                    f"Results per sub-query (default: {settings.KB_DEFAULT_TOP_K})"
                ),
                "default": settings.KB_DEFAULT_TOP_K,
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
                        "field": {
                            "type": "string",
                            "description": "Metadata field name",
                        },
                        "operator": {
                            "type": "string",
                            "enum": [
                                "eq", "neq", "gt", "gte", "lt", "lte",
                                "like", "max", "min",
                            ],
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
