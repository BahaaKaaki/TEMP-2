"""
Schema Generator Service

Uses LLM to analyze agent prompts and generate multi-section output schemas.
Each section has a title, description, and free-form content schema.
"""

import json
import logging
from typing import Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage
import os
from .visualization_prompts import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


async def generate_output_schema(
    prompt: str, 
    task_instructions: Optional[str] = None,
    user_requirements: Optional[str] = None,
    output_schema: Optional[str] = None
) -> Dict[str, Any]:
    """
    Use LLM to generate a multi-section output schema for an agent.
    
    Args:
        prompt: The agent's main prompt/instructions
        task_instructions: Additional task-specific instructions
        user_requirements: User's additional requirements for the schema
        output_schema: Existing output schema (if any)
        
    Returns:
        Dictionary containing:
        - reasoning: Explanation of the schema design
        - suggestedSchema: JSON schema with sections array
    """
    try:
        from app.config.llm_config import LLMClientManager
        llm = LLMClientManager.get_client_for_binding(
            "service.visualization_analyzer",
            temperature=0,
            max_tokens=4096,
            timeout=120,
        )
        
        # Build prompts using templates
        system_prompt = build_system_prompt()
        user_content = build_user_prompt(prompt, task_instructions, user_requirements, output_schema)
        
        # Call LLM
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content)
        ]
        
        logger.debug("Generating multi-section output schema with LLM...")
        response = await llm.ainvoke(messages)
        
        # Extract content from response
        content = ""
        if hasattr(response, 'content') and response.content:
            content = response.content if isinstance(response.content, str) else str(response.content)
        elif hasattr(response, 'content_blocks') and response.content_blocks:
            blocks = response.content_blocks
            if isinstance(blocks, list):
                text_parts = []
                for block in blocks:
                    if isinstance(block, dict) and 'text' in block:
                        text_parts.append(block['text'])
                    elif isinstance(block, str):
                        text_parts.append(block)
                    elif hasattr(block, 'text'):
                        text_parts.append(block.text)
                content = "\n".join(text_parts)
        elif hasattr(response, 'text') and response.text:
            content = response.text
        
        if not content:
            logger.warning(f"LLM returned empty content. Response type: {type(response).__name__}")
            return _fallback_analysis(prompt, task_instructions)
        
        content = content.strip()
        logger.debug(f"Raw LLM response (first 500 chars): {content[:500]}")
        
        # Strip markdown fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        
        result = json.loads(content)
        
        # Log section count from the parsed schema
        try:
            items = result.get('suggestedSchema', {}).get('properties', {}).get('sections', {}).get('items', [])
            section_count = len(items) if isinstance(items, list) else 1
            logger.debug(f"Schema generation complete with {section_count} section(s)")
        except Exception:
            logger.debug("Schema generation complete")
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response: {e}")
        logger.error(f"Raw content was: {content[:1000] if content else '(empty)'}")
        return _fallback_analysis(prompt, task_instructions)
    except Exception as e:
        logger.error(f"Error generating output schema: {e}")
        return _fallback_analysis(prompt, task_instructions)


def _fallback_analysis(prompt: str, task_instructions: Optional[str]) -> Dict[str, Any]:
    """
    Fallback heuristic analysis if LLM fails.
    Produces a reasonable multi-section schema based on keyword detection.
    Uses token-efficient formats (columns+rows for tables).
    """
    combined_text = f"{prompt} {task_instructions or ''}".lower()
    
    sections_schema = []
    
    analytical_keywords = [
        'data', 'analyze', 'analysis', 'pattern', 'visualization', 'visualize',
        'metrics', 'kpi', 'performance', 'statistics', 'insight', 'compare',
        'comparison', 'sales', 'revenue', 'business'
    ]
    hierarchical_keywords = [
        'organization', 'hierarchy', 'org chart', 'structure', 'tree', 'reporting'
    ]
    timeseries_keywords = [
        'trend', 'over time', 'historical', 'timeline', 'growth', 'monthly', 'daily'
    ]
    tabular_keywords = [
        'taxonomy', 'capability', 'catalog', 'inventory', 'mapping', 'matrix',
        'table', 'csv', 'record', 'list of', 'roster', 'registry', 'directory',
        'benchmark', 'scorecard', 'assessment'
    ]
    report_keywords = ['report', 'dashboard', 'summary', 'comprehensive']
    
    has_analytical = any(word in combined_text for word in analytical_keywords)
    has_hierarchical = any(word in combined_text for word in hierarchical_keywords)
    has_timeseries = any(word in combined_text for word in timeseries_keywords)
    has_tabular = any(word in combined_text for word in tabular_keywords)
    has_report = any(word in combined_text for word in report_keywords)
    
    if has_tabular:
        sections_schema.append({
            "type": "object",
            "properties": {
                "section_title": {"type": "string"},
                "description": {"type": "string"},
                "content": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "object",
                            "description": "Columns listed once, rows as value arrays.",
                            "properties": {
                                "columns": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "rows": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                }
                            },
                            "required": ["columns", "rows"]
                        }
                    },
                    "required": ["table"]
                }
            },
            "required": ["section_title", "description", "content"]
        })
    
    if has_analytical or has_timeseries:
        sections_schema.append({
            "type": "object",
            "properties": {
                "section_title": {"type": "string"},
                "description": {"type": "string"},
                "content": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {"type": "string"},
                                    "value": {"type": "number"}
                                },
                                "required": ["category", "value"]
                            }
                        }
                    },
                    "required": ["data"]
                }
            },
            "required": ["section_title", "description", "content"]
        })
    
    if has_hierarchical:
        sections_schema.append({
            "type": "object",
            "properties": {
                "section_title": {"type": "string"},
                "description": {"type": "string"},
                "content": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "children": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "children": {"type": "array", "items": {"type": "object"}}
                                },
                                "required": ["name"]
                            }
                        }
                    },
                    "required": ["name"]
                }
            },
            "required": ["section_title", "description", "content"]
        })
    
    sections_schema.append({
        "type": "object",
        "properties": {
            "section_title": {"type": "string"},
            "description": {"type": "string"},
            "content": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {"type": "array", "items": {"type": "string"}},
                    "recommendation": {"type": "string"}
                },
                "required": ["summary"]
            }
        },
        "required": ["section_title", "description", "content"]
    })
    
    if not (has_analytical or has_hierarchical or has_timeseries or has_report or has_tabular):
        sections_schema.insert(0, {
            "type": "object",
            "properties": {
                "section_title": {"type": "string"},
                "description": {"type": "string"},
                "content": {
                    "type": "object",
                    "properties": {
                        "result": {"type": "string"}
                    },
                    "required": ["result"]
                }
            },
            "required": ["section_title", "description", "content"]
        })
    
    detected = []
    if has_tabular:
        detected.append("tabular")
    if has_analytical:
        detected.append("analytical")
    if has_hierarchical:
        detected.append("hierarchical")
    if has_timeseries:
        detected.append("time-series")
    if has_report:
        detected.append("report/dashboard")
    
    reasoning = (
        f"Fallback analysis detected patterns: {', '.join(detected) if detected else 'general'}. "
        f"Generated {len(sections_schema)} sections."
    )
    
    # Use a single shared section schema instead of oneOf (which violates LLM compatibility)
    shared_content = {
        "type": "object",
        "properties": {
            "section_title": {"type": "string"},
            "description": {"type": "string"},
            "content": {"type": "object"}
        },
        "required": ["section_title", "description", "content"]
    }
    
    return {
        "reasoning": reasoning,
        "suggestedSchema": {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": shared_content
                }
            },
            "required": ["sections"]
        }
    }
