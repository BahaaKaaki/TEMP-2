"""
Simple Web Search tool backed by OpenAI's built-in ``web_search_preview``.

All traffic is routed through the GenAI Shared Service proxy, so no
third-party search vendor (Tavily, Google CSE, …) is needed. The tool is
a thin wrapper around ``client.responses.create(...)`` with the
``web_search_preview`` built-in tool forced via ``tool_choice``. The
response is parsed into the ``{"text", "citations"}`` shape the citation
pipeline expects, so the Tool Caller / Standard-mode executors don't
need any changes.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun

from config.keyvault import cfg

logger = logging.getLogger(__name__)

def _web_search_model() -> str:
    from app.llm.registry import LlmModelRegistry
    return LlmModelRegistry.get_primary("tool.web_search")

SYSTEM_INSTRUCTIONS = (
    "You are a concise web research assistant. The user will give you a "
    "query. Use the web_search_preview tool to gather up-to-date "
    "information, then produce a short synthesized answer (5-10 sentences) "
    "that cites sources inline. Prefer authoritative, recent sources. Do "
    "not invent URLs — rely only on what the tool returns."
)


class SimpleWebSearchInput(BaseModel):
    """Input schema for the simple web search tool."""

    query: str = Field(description="The search query to look up on the web")


class SimpleWebSearchTool(BaseTool):
    """Search the web using OpenAI's built-in ``web_search_preview`` tool.

    The call is routed through the GenAI Shared Service proxy. The OpenAI
    model (``openai.gpt-5.4-mini`` by default) is forced to invoke
    ``web_search_preview`` via ``tool_choice``, then synthesises a short
    answer with inline URL citations. The tool returns the standard
    ``{"text": "...", "citations": [...]}`` dict so downstream citation
    and UI logic stays unchanged.

    Environment variables (via GenAI proxy):
        GENAI_PROXY_URL       — required
        GENAI_PROXY_API_KEY   — required
    """

    name: str = "simple_web_search"
    description: str = (
        "Search the web for current information on any topic. "
        "Returns a short synthesized answer with cited source URLs. "
        "Use this for quick factual lookups, recent events, or when you "
        "need up-to-date information that may not be in your training data."
    )
    args_schema: Type[BaseModel] = SimpleWebSearchInput

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        return asyncio.get_event_loop().run_until_complete(
            self._arun(query, run_manager=run_manager)
        )

    async def _arun(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """Execute a web search asynchronously via the OpenAI Responses API."""
        if not query or not query.strip():
            return {
                "text": "Error: search query must not be empty.",
                "citations": [],
            }

        try:
            client = self._get_client()
        except Exception as e:
            logger.error("Failed to create web search client: %s", e)
            return {
                "text": f"Web search unavailable: {e}",
                "citations": [],
            }

        logger.info("simple_web_search: query=%s", query[:120])

        try:
            response = await asyncio.to_thread(
                client.responses.create,
                model=_web_search_model(),
                input=[
                    {
                        "role": "developer",
                        "content": [
                            {"type": "input_text", "text": SYSTEM_INSTRUCTIONS}
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": query}],
                    },
                ],
                tools=[{"type": "web_search_preview"}],
                tool_choice={"type": "web_search_preview"},
            )
        except Exception as e:
            logger.error("OpenAI web search failed: %s", e, exc_info=True)
            return {
                "text": f"Web search failed: {e}",
                "citations": [],
            }

        return self._format_results(query, response)

    @staticmethod
    def _get_client():
        """Return an OpenAI client pointed at the GenAI Shared Service proxy."""
        from openai import OpenAI

        proxy_url = cfg.GENAI_PROXY_URL
        proxy_key = cfg.GENAI_PROXY_API_KEY

        if not proxy_url or not proxy_key:
            raise RuntimeError(
                "GENAI_PROXY_URL and GENAI_PROXY_API_KEY must be set for "
                "web search"
            )

        return OpenAI(
            base_url=f"{proxy_url}/v1",
            api_key=proxy_key,
            default_headers={"API-Key": proxy_key},
            timeout=60.0,
        )

    @staticmethod
    def _format_results(query: str, response: Any) -> Dict[str, Any]:
        """Convert the Responses API output into ``{"text", "citations"}``.

        Walks ``response.output``, grabs the assistant message's text, and
        collects ``url_citation`` annotations as numbered citations. Final
        markdown links like ``[title](url)`` in the text are rewritten to
        ``title [N]`` so the existing citation renderer in the frontend
        picks them up the same way Tavily results did.
        """
        citations: List[Dict[str, Any]] = []
        url_to_number: Dict[str, int] = {}
        text_parts: List[str] = []

        output_items = getattr(response, "output", []) or []
        for item in output_items:
            if getattr(item, "type", None) != "message":
                continue
            for block in getattr(item, "content", []) or []:
                block_type = getattr(block, "type", None)
                if block_type not in ("output_text", "text"):
                    continue
                text = getattr(block, "text", "") or ""
                for ann in getattr(block, "annotations", []) or []:
                    if getattr(ann, "type", None) != "url_citation":
                        continue
                    url = getattr(ann, "url", "") or ""
                    if not url:
                        continue
                    if url not in url_to_number:
                        number = len(citations) + 1
                        url_to_number[url] = number
                        citations.append({
                            "citation_number": number,
                            "type": "web",
                            "title": getattr(ann, "title", "") or url,
                            "url": url,
                            "chunk_text": "",
                        })
                text_parts.append(text)

        body = "".join(text_parts).strip()

        if not body and not citations:
            return {
                "text": f"Web search for '{query}' returned no results.",
                "citations": [],
            }

        body = SimpleWebSearchTool._rewrite_markdown_links(
            body, url_to_number, citations,
        )

        header = f"Web search results for: '{query}'\n\n"
        footer = ""
        if citations:
            sources = "\n".join(
                f"[{c['citation_number']}] {c['title']} — {c['url']}"
                for c in citations
            )
            footer = f"\n\nSources:\n{sources}"

        return {
            "text": f"{header}{body}{footer}",
            "citations": citations,
        }

    @staticmethod
    def _rewrite_markdown_links(
        text: str,
        url_to_number: Dict[str, int],
        citations: List[Dict[str, Any]],
    ) -> str:
        """Replace ``[title](url)`` with ``title [N]`` for every link.

        Markdown links whose URL is already in ``url_to_number`` reuse the
        existing number; unknown links are appended to *citations* so no
        source is lost when the Responses API omits an annotation.
        """
        import re

        link_re = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

        def _replace(match: "re.Match") -> str:
            title = match.group(1).strip()
            url = match.group(2).strip()
            if url not in url_to_number:
                number = len(citations) + 1
                url_to_number[url] = number
                citations.append({
                    "citation_number": number,
                    "type": "web",
                    "title": title or url,
                    "url": url,
                    "chunk_text": "",
                })
            return f"{title} [{url_to_number[url]}]"

        return link_re.sub(_replace, text)
