"""
Submit Deliverable tool for multi-agent workflows.

Provides an explicit, tool-based mechanism for agents to signal
that their task is complete and submit structured output, rather
than relying on the LLM voluntarily populating a JSON field.

The tool validates the submitted data against the agent's output
schema and returns a DeliverableSubmission marker that the tool
loop can detect and act on.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun

logger = logging.getLogger(__name__)


class DeliverableSubmission(str):
    """String subclass that carries a validated deliverable through LangChain.

    Mirrors the CitedText pattern from deep_research so the existing
    tool-result processing pipeline can detect it by type.
    """

    data: Dict[str, Any]
    valid: bool
    errors: List[str]

    def __new__(
        cls,
        text: str,
        data: Dict[str, Any],
        valid: bool = True,
        errors: List[str] = None,
    ):
        instance = super().__new__(cls, text)
        instance.data = data
        instance.valid = valid
        instance.errors = errors or []
        return instance


class SubmitDeliverableInput(BaseModel):
    """Input schema for the submit_deliverable tool."""

    deliverable: Dict[str, Any] = Field(
        description=(
            "The structured deliverable data to submit. "
            "Must conform to the output schema defined for this agent."
        )
    )


class SubmitDeliverableTool(BaseTool):
    """Tool that agents call to explicitly submit their final deliverable.

    Created per-agent with the agent's ``output_schema`` so the tool
    can validate the submission before accepting it.
    """

    name: str = "submit_deliverable"
    description: str = (
        "Submit your final structured deliverable when your task is complete. "
        "Call this ONLY when you have gathered enough information and are "
        "ready to produce your final output. The deliverable must conform "
        "to the required output schema."
    )
    args_schema: Type[BaseModel] = SubmitDeliverableInput

    deliverable_schema: Optional[Dict[str, Any]] = Field(
        default=None, exclude=True
    )

    def __init__(self, output_schema: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(deliverable_schema=output_schema, **kwargs)
        if output_schema:
            schema_str = json.dumps(output_schema, indent=2)
            self.description = (
                f"{self.description}\n\n"
                f"Required schema for the deliverable argument:\n"
                f"```json\n{schema_str}\n```"
            )

    def _validate_against_schema(self, data: Dict[str, Any]) -> List[str]:
        """Validate deliverable data against the deliverable schema.

        Returns a list of human-readable error strings (empty if valid).
        Uses jsonschema if available, otherwise does a lightweight
        structural check.
        """
        if not self.deliverable_schema:
            return []

        errors: List[str] = []
        try:
            import jsonschema
            jsonschema.validate(instance=data, schema=self.deliverable_schema)
        except ImportError:
            errors = self._lightweight_validate(data)
        except Exception as e:
            error_msg = str(e).split("\n")[0]
            errors.append(error_msg)

        return errors

    @staticmethod
    def _lightweight_validate(data: Dict[str, Any]) -> List[str]:
        """Fallback validation when jsonschema is not installed."""
        if not isinstance(data, dict):
            return ["Deliverable must be a JSON object"]
        if not data:
            return ["Deliverable must not be empty"]
        return []

    def _run(
        self,
        deliverable: Dict[str, Any],
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> DeliverableSubmission:
        logger.info(
            "submit_deliverable called with %d top-level keys",
            len(deliverable) if isinstance(deliverable, dict) else 0,
        )

        if not isinstance(deliverable, dict):
            return DeliverableSubmission(
                "Error: deliverable must be a JSON object.",
                data={},
                valid=False,
                errors=["deliverable must be a JSON object"],
            )

        if not deliverable:
            schema_hint = ""
            if self.deliverable_schema:
                schema_hint = (
                    f"\n\nRequired schema:\n{json.dumps(self.deliverable_schema, indent=2)}"
                )
            return DeliverableSubmission(
                "Error: deliverable must not be empty. "
                "You MUST populate every field using the context available to you. "
                "Even with partial information, fill in every field with your best effort. "
                "Call submit_deliverable again with a fully populated object."
                + schema_hint,
                data={},
                valid=False,
                errors=["deliverable must not be empty"],
            )

        validation_errors = self._validate_against_schema(deliverable)

        if validation_errors:
            error_text = (
                "Schema validation failed:\n"
                + "\n".join(f"  - {e}" for e in validation_errors)
                + "\nPlease fix and call submit_deliverable again."
            )
            logger.warning("submit_deliverable rejected: %s", validation_errors)
            return DeliverableSubmission(
                error_text,
                data=deliverable,
                valid=False,
                errors=validation_errors,
            )

        summary = json.dumps(deliverable, indent=2, default=str)
        logger.info("submit_deliverable accepted (%d chars)", len(summary))
        return DeliverableSubmission(
            f"Deliverable accepted.\n{summary}",
            data=deliverable,
            valid=True,
        )

    async def _arun(
        self,
        deliverable: Dict[str, Any],
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> DeliverableSubmission:
        return self._run(deliverable, run_manager)
