"""
Deep Research tool using OpenAI o3-deep-research via the Responses API.

This tool performs autonomous deep web research on any topic.
It always uses o3-deep-research regardless of the agent's configured model.
The Responses API background mode is used to avoid timeouts (research takes 5-15 min).

When an ``output_schema`` is provided at creation time the tool instructs o3
to return a JSON object matching that schema.  After o3 responds the tool
recursively walks every string value, converts ``[title](url)`` links to
numbered ``[N]`` markers, and builds a global citations list.  The caller
receives structured data ready to be used as a deliverable — no Phase 2
LLM call is needed.
"""

import os
import json
import asyncio
import time
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from config.keyvault import cfg
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from app.tracing import emit_trace_event, get_trace_context

logger = logging.getLogger(__name__)

# Model ids resolved via unified catalog (config/llm_models_inventory.yaml)
def _deep_research_model() -> str:
    from app.llm.registry import LlmModelRegistry
    return LlmModelRegistry.get_primary("tool.deep_research.primary")


def _query_planner_model() -> str:
    from app.llm.registry import LlmModelRegistry
    return LlmModelRegistry.get_primary("tool.deep_research.query_planner")

QUERY_PLANNER_PROVIDER = "bedrock"
QUERY_PLANNER_TEMPERATURE = 0.0
QUERY_PLANNER_MAX_TOKENS = 2048


class CitedText(str):
    """String subclass that carries structured citation data through LangChain.

    Also used in structured mode: ``deliverable`` holds the parsed JSON
    object so the executor can extract it without re-parsing.
    """

    citations: List[Dict[str, Any]]
    deliverable: Optional[Dict[str, Any]]

    def __new__(
        cls,
        text: str,
        citations: List[Dict[str, Any]] = None,
        deliverable: Dict[str, Any] = None,
    ):
        instance = super().__new__(cls, text)
        instance.citations = citations or []
        instance.deliverable = deliverable
        return instance


POLL_INITIAL_INTERVAL = 10   # seconds
POLL_MAX_INTERVAL = 15       # seconds
POLL_MAX_DURATION = 1400      # 15 minutes max


class DeepResearchInput(BaseModel):
    """Input schema for deep research tool."""
    query: str = Field(description="The research topic or question to investigate in depth")


class DeepResearchTool(BaseTool):
    """
    Perform deep, autonomous web research using OpenAI o3-deep-research.

    When ``output_schema`` is set the model is instructed to return JSON
    matching that schema.  Citations are extracted from every string value
    in the JSON, converted to ``[N]`` markers, and returned alongside the
    structured deliverable so that Phase 2 (re-invoke LLM for formatting)
    can be skipped entirely.
    """

    name: str = "deep_research"
    description: str = (
        "Perform deep, autonomous web research on a topic. "
        "Returns a comprehensive, citation-rich report. "
        "Use this for complex questions requiring multiple sources, "
        "current events, comparative analysis, or literature review. "
        "Takes several minutes to complete — only use when thorough research is needed."
    )
    args_schema: Type[BaseModel] = DeepResearchInput

    output_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="When set, o3 is asked to return JSON matching this schema.",
        exclude=True,
    )
    deliverable_context: Optional[str] = Field(
        default=None,
        description="Formatted previous agent deliverables this agent has access to.",
        exclude=True,
    )
    agent_chat_summary: Optional[str] = Field(
        default=None,
        description="Summary of the agent's conversation so far.",
        exclude=True,
    )
    agent_instructions: Optional[str] = Field(
        default=None,
        description="The agent's system and task instructions describing its goal.",
        exclude=True,
    )

    async def _build_research_query(self, original_query: str) -> str:
        """Build a rich, decomposed research query from deliverable context
        and agent chat, ignoring the Tool Caller's generic query.

        Falls back to *original_query* when no context is available or the
        planner LLM call fails.
        """
        if not self.deliverable_context and not self.agent_chat_summary:
            logger.debug("No deliverable/chat context — using original query")
            return original_query

        context_parts: List[str] = []
        if self.agent_instructions:
            context_parts.append(
                f"## Agent Instructions (what this agent is tasked to do)\n{self.agent_instructions}"
            )
        if self.deliverable_context:
            context_parts.append(
                f"## Previous Agent Deliverables\n{self.deliverable_context}"
            )
        if self.agent_chat_summary:
            context_parts.append(
                f"## Agent Conversation So Far\n{self.agent_chat_summary}"
            )
        context_block = "\n\n".join(context_parts)

        prompt = (
            "You are a research query planner. An autonomous web researcher will "
            "receive ONLY the query you write — it has no other context.\n\n"
            "Using the deliverables and conversation below, produce a detailed, "
            "self-contained research query (3-5 sentences).\n\n"
            "Rules:\n"
            "- Extract the key subject, domain, and objectives from the context\n"
            "- Describe characteristics and criteria explicitly — the researcher "
            "knows nothing about prior work\n"
            "- Do NOT reference 'the deliverable', 'the previous agent'"
            "— state everything explicitly\n"
            "- Do NOT repeat data as presented — focus on "
            "what NEW information is needed\n\n"
            f"{context_block}\n\n"
            "Respond with ONLY the research query, nothing else."
        )

        try:
            from config.llm_config import LLMClientManager
            from langchain_core.messages import HumanMessage

            llm = LLMClientManager.get_client(
                provider=QUERY_PLANNER_PROVIDER,
                model=_query_planner_model(),
                temperature=QUERY_PLANNER_TEMPERATURE,
                max_tokens=QUERY_PLANNER_MAX_TOKENS,
                binding_key="tool.deep_research.query_planner",
                llm_role="query_planner",
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            enriched = response.content.strip() if response.content else ""
            if enriched:
                logger.info(
                    "🔬 Deep research query enriched (%d chars):\n%s",
                    len(enriched), enriched,
                )
                return enriched
        except Exception as exc:
            logger.warning(
                "⚠️ Query planner failed, using original query: %s", exc,
            )

        return original_query

    def _get_client(self):
        """Get OpenAI client configured for the GenAI proxy Responses API."""
        from openai import OpenAI

        proxy_url = cfg.GENAI_PROXY_URL
        proxy_key = cfg.GENAI_PROXY_API_KEY

        if not proxy_url or not proxy_key:
            raise RuntimeError(
                "GENAI_PROXY_URL and GENAI_PROXY_API_KEY must be set for deep research"
            )

        return OpenAI(
            base_url=f"{proxy_url}/v1",
            api_key=proxy_key,
            default_headers={"API-Key": proxy_key},
            timeout=120.0,
        )

    def _build_system_message(self) -> str:
        """Build the system/developer message for the research model."""
        base = (
            "You are a professional researcher. Produce a structured, citation-rich report.\n\n"
            "Requirements:\n"
            "- Include specific figures, dates, paper titles, and source URLs\n"
            "- Add inline citations as markdown links [title](url) throughout\n"
            "- Be analytical and data-driven, avoid generalities\n"
            "- Prioritize reliable, up-to-date sources: peer-reviewed research, "
            "official reports, reputable news outlets\n"
        )

        if self.output_schema:
            schema_str = json.dumps(self.output_schema, indent=2, default=str)
            base += (
                "\nCRITICAL — Output format:\n"
                "Return your research as a **single JSON object** matching the "
                "schema below.  Do NOT wrap it in markdown code fences.  Every "
                "text/content field MUST contain inline citations as markdown "
                "links [title](url).\n\n"
                f"{schema_str}\n\n"
                "Return ONLY the JSON object, nothing else.\n"
            )
        else:
            base += (
                "- Organize into clear sections with headings\n"
                "- End with a ## Sources section listing all unique sources used\n"
            )

        return base

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Synchronous execution — delegates to async."""
        return asyncio.get_event_loop().run_until_complete(
            self._arun(query, run_manager=run_manager)
        )

    async def _arun(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Execute deep research asynchronously."""
        logger.info("Deep research tool called with original query: %s", query[:100])
        if self.output_schema:
            logger.debug("📋 Structured mode: will ask o3 to return JSON matching output schema")
        t0 = time.time()
        span_id = f"deep_research:{uuid.uuid4().hex[:12]}"
        parent_span_id = get_trace_context().get("span_id")
        await emit_trace_event(
            "deep_research.started",
            status="running",
            span_id=span_id,
            parent_span_id=parent_span_id,
            payload={
                "model": _deep_research_model(),
                "structured": bool(self.output_schema),
                "query": query,
            },
        )

        research_query = await self._build_research_query(query)
        logger.info(
            "🔬 Deep research final query (%d chars):\n%s",
            len(research_query), research_query,
        )

        try:
            client = self._get_client()
        except Exception as e:
            logger.error("Failed to create deep research client: %s", e)
            await emit_trace_event(
                "deep_research.failed",
                status="error",
                span_id=span_id,
                parent_span_id=parent_span_id,
                duration_ms=(time.time() - t0) * 1000,
                payload={"error": str(e)},
            )
            return f"Deep research unavailable: {e}"

        # ── Step 1: Send background request ──────────────────────────────
        try:
            logger.debug("Sending background request to %s", _deep_research_model())
            resp = client.responses.create(
                model=_deep_research_model(),
                input=[
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": self._build_system_message()}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": research_query}],
                    },
                ],
                tools=[{"type": "web_search_preview"}],
                reasoning={"summary": "auto"},
                background=True,
            )
            logger.debug(
                "Deep research queued: id=%s status=%s (%.1fs)",
                resp.id, resp.status, time.time() - t0,
            )
            await emit_trace_event(
                "deep_research.queued",
                status="running",
                span_id=span_id,
                parent_span_id=parent_span_id,
                payload={
                    "response_id": resp.id,
                    "provider_status": resp.status,
                    "query": query,
                },
            )
        except Exception as e:
            logger.error("Failed to send deep research request: %s", e)
            await emit_trace_event(
                "deep_research.failed",
                status="error",
                span_id=span_id,
                parent_span_id=parent_span_id,
                duration_ms=(time.time() - t0) * 1000,
                payload={"error": str(e)},
            )
            return f"Deep research request failed: {e}"

        # ── Step 2: Poll until terminal state ────────────────────────────
        poll_interval = POLL_INITIAL_INTERVAL
        poll_count = 0

        while resp.status in ("queued", "in_progress"):
            elapsed = time.time() - t0
            if elapsed > POLL_MAX_DURATION:
                logger.warning("Deep research timed out after %.0fs", elapsed)
                await emit_trace_event(
                    "deep_research.failed",
                    status="error",
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    duration_ms=elapsed * 1000,
                    payload={"error": "timeout", "poll_count": poll_count},
                )
                return (
                    f"Deep research timed out after {int(elapsed)}s. "
                    "The research is still running on the server but took too long to complete. "
                    "Please try a more focused query."
                )

            poll_count += 1
            logger.debug(
                "Deep research poll #%d | status=%s | elapsed=%.0fs",
                poll_count, resp.status, elapsed,
            )

            await asyncio.sleep(poll_interval)
            if poll_interval < POLL_MAX_INTERVAL:
                poll_interval = min(poll_interval + 2, POLL_MAX_INTERVAL)

            try:
                resp = client.responses.retrieve(resp.id)
            except Exception as e:
                logger.warning("Poll failed (will retry): %s", e)
                await asyncio.sleep(5)
                continue

        elapsed = time.time() - t0
        logger.debug("Deep research finished: status=%s elapsed=%.0fs", resp.status, elapsed)

        if resp.status != "completed":
            await emit_trace_event(
                "deep_research.failed",
                status="error",
                span_id=span_id,
                parent_span_id=parent_span_id,
                duration_ms=elapsed * 1000,
                payload={"provider_status": resp.status, "poll_count": poll_count},
            )
            return f"Deep research ended with status '{resp.status}' after {int(elapsed)}s."

        # ── Step 3: Extract raw text from response ───────────────────────
        text = ""
        for item in resp.output:
            if hasattr(item, "content") and item.content is not None:
                for c in item.content:
                    if hasattr(c, "text"):
                        text += c.text

        if not text:
            await emit_trace_event(
                "deep_research.failed",
                status="error",
                span_id=span_id,
                parent_span_id=parent_span_id,
                duration_ms=elapsed * 1000,
                payload={"error": "empty_output", "poll_count": poll_count},
            )
            return "Deep research completed but returned no text output."

        if hasattr(resp, "usage") and resp.usage:
            logger.debug(
                "Deep research tokens: in=%s out=%s",
                getattr(resp.usage, "input_tokens", "?"),
                getattr(resp.usage, "output_tokens", "?"),
            )

        # ── Step 4: Structured vs free-form processing ───────────────────
        if self.output_schema:
            result = self._process_structured_response(text, elapsed)
        else:
            result = self._process_freeform_response(text, elapsed)

        await emit_trace_event(
            "deep_research.completed",
            status="success",
            span_id=span_id,
            parent_span_id=parent_span_id,
            duration_ms=elapsed * 1000,
            payload={
                "provider_status": resp.status,
                "poll_count": poll_count,
                "citation_count": len(getattr(result, "citations", []) or []),
                "output_chars": len(str(result)),
            },
        )
        return result

    # ------------------------------------------------------------------
    # Response processing
    # ------------------------------------------------------------------

    def _process_structured_response(self, text: str, elapsed: float) -> "CitedText":
        """Parse JSON from o3, walk all strings to extract citations."""
        parsed = self._extract_json(text)

        if parsed is None:
            logger.warning("⚠️ Structured mode: JSON parsing failed, falling back to free-form")
            return self._process_freeform_response(text, elapsed)

        converted, citations = self._convert_structured_citations(parsed)
        logger.debug(
            "Deep research complete (structured): %d citations, %.0fs",
            len(citations), elapsed,
        )

        summary = json.dumps(converted, indent=2, default=str)
        return CitedText(summary, citations=citations, deliverable=converted)

    def _process_freeform_response(self, text: str, elapsed: float) -> "CitedText":
        """Convert markdown links to [N] markers in free-form text."""
        result = self._convert_links_to_citations(text)
        logger.debug(
            "Deep research complete (free-form): %d chars, %d sources, %.0fs",
            len(result["text"]), len(result["citations"]), elapsed,
        )
        return CitedText(result["text"], citations=result["citations"])

    # ------------------------------------------------------------------
    # JSON extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Try to parse a JSON object from *text*.

        Handles both raw JSON and JSON wrapped in markdown code fences.
        """
        stripped = text.strip()

        # Strip markdown code fences if present
        if stripped.startswith("```"):
            match = re.search(r'```(?:json)?\s*\n(.*?)\n```', stripped, re.DOTALL)
            if match:
                stripped = match.group(1).strip()

        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # Last resort: find the first { ... } block
        brace_match = re.search(r'\{', stripped)
        if brace_match:
            depth, start = 0, brace_match.start()
            for i in range(start, len(stripped)):
                if stripped[i] == '{':
                    depth += 1
                elif stripped[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(stripped[start:i + 1])
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            pass
                        break

        return None

    # ------------------------------------------------------------------
    # Citation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_structured_citations(
        data: Any,
    ) -> tuple[Any, List[Dict[str, Any]]]:
        """Recursively walk *data*, converting ``[title](url)`` in every
        string value to ``[N]`` markers.  Returns ``(converted_data, citations)``
        with globally unique citation numbers.
        """
        url_to_number: Dict[str, int] = {}
        citations: List[Dict[str, Any]] = []
        counter = [0]

        link_re = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')

        def _replace(match: re.Match) -> str:
            title = match.group(1)
            url = match.group(2)
            if url not in url_to_number:
                counter[0] += 1
                url_to_number[url] = counter[0]
                citations.append({
                    "citation_number": counter[0],
                    "type": "web",
                    "title": title,
                    "url": url,
                    "chunk_text": "",
                })
            return f"{title} [{url_to_number[url]}]"

        def walk(obj: Any) -> Any:
            if isinstance(obj, str):
                return link_re.sub(_replace, obj)
            if isinstance(obj, dict):
                return {k: walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [walk(item) for item in obj]
            return obj

        converted = walk(data)
        return converted, citations

    @staticmethod
    def _convert_links_to_citations(text: str) -> Dict[str, Any]:
        """Replace ``[title](url)`` with ``[N]`` markers in free-form text."""
        url_to_number: Dict[str, int] = {}
        unique_citations: List[Dict[str, Any]] = []
        counter = 0

        def _replace(match: re.Match) -> str:
            nonlocal counter
            title = match.group(1)
            url = match.group(2)

            if url not in url_to_number:
                counter += 1
                url_to_number[url] = counter
                unique_citations.append({
                    "citation_number": counter,
                    "type": "web",
                    "title": title,
                    "url": url,
                    "chunk_text": "",
                })
            return f"{title} [{url_to_number[url]}]"

        converted = re.sub(
            r'\[([^\]]+)\]\((https?://[^\)]+)\)',
            _replace,
            text,
        )

        converted = re.sub(
            r'\n+---\s*\n+## Sources\b.*',
            '',
            converted,
            flags=re.DOTALL,
        )

        if unique_citations:
            converted += "\n\n---\n\n## Sources\n\n"
            for c in unique_citations:
                title = c["title"] or "Untitled"
                converted += f"[{c['citation_number']}] [{title}]({c['url']})\n\n"

        return {"text": converted, "citations": unique_citations}
