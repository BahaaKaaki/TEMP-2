"""
Transform node executor.

Transforms data using various operations (map, filter, format, etc.).
"""

from typing import Any, List, Dict
import json
import logging

from .base import BaseNode
from ..state import WorkflowState

logger = logging.getLogger(__name__)


class TransformNode(BaseNode):
    """
    Transform node executor.
    
    Applies data transformations like mapping, filtering, formatting, etc.
    """
    
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the transform node.
        
        Args:
            state: Current workflow state
            
        Returns:
            Transformed data
        """
        # Get input data
        input_source = self.get_config_value("inputSource")
        input_data = self.get_input_from_state(state, input_source)
        
        # Get transformation type
        transform_type = self.get_config_value("transformType", "map")
        
        if transform_type == "map":
            result = self._map_transform(input_data, state)
        elif transform_type == "filter":
            result = self._filter_transform(input_data, state)
        elif transform_type == "format":
            result = self._format_transform(input_data, state)
        elif transform_type == "extract":
            result = self._extract_transform(input_data, state)
        elif transform_type == "aggregate":
            result = self._aggregate_transform(input_data, state)
        else:
            raise ValueError(f"Unknown transform type: {transform_type}")
        
        return result
    
    def _map_transform(self, data: Any, state: WorkflowState) -> Any:
        """
        Map transformation - transform each item in a list.
        
        Args:
            data: Input data
            state: Workflow state
            
        Returns:
            Mapped data
        """
        mapping = self.get_config_value("mapping", {})
        
        if isinstance(data, list):
            return [self._apply_mapping(item, mapping, state) for item in data]
        else:
            return self._apply_mapping(data, mapping, state)
    
    def _apply_mapping(
        self,
        item: Any,
        mapping: Dict[str, str],
        state: WorkflowState
    ) -> Dict[str, Any]:
        """Apply field mapping to a single item."""
        if not isinstance(item, dict):
            return item
        
        result = {}
        for target_key, source_expr in mapping.items():
            # Simple field mapping
            if source_expr in item:
                result[target_key] = item[source_expr]
            else:
                # Try template substitution
                result[target_key] = self._substitute_template(source_expr, item, state)
        
        return result
    
    def _filter_transform(self, data: Any, state: WorkflowState) -> List[Any]:
        """
        Filter transformation - filter items in a list.
        
        Args:
            data: Input data (should be a list)
            state: Workflow state
            
        Returns:
            Filtered list
        """
        if not isinstance(data, list):
            return data
        
        filter_field = self.get_config_value("filterField")
        filter_operator = self.get_config_value("filterOperator", "equals")
        filter_value = self.get_config_value("filterValue")
        
        filtered = []
        for item in data:
            if self._evaluate_filter(item, filter_field, filter_operator, filter_value):
                filtered.append(item)
        
        return filtered
    
    def _evaluate_filter(
        self,
        item: Any,
        field: str,
        operator: str,
        value: Any
    ) -> bool:
        """Evaluate filter condition for a single item."""
        if isinstance(item, dict):
            item_value = item.get(field)
        else:
            item_value = item
        
        if operator == "equals":
            return item_value == value
        elif operator == "not_equals":
            return item_value != value
        elif operator == "contains":
            return value in str(item_value)
        elif operator == "greater_than":
            return item_value > value
        elif operator == "less_than":
            return item_value < value
        else:
            return True
    
    def _format_transform(self, data: Any, state: WorkflowState) -> str:
        """
        Format transformation - format data into a string template.
        
        Args:
            data: Input data
            state: Workflow state
            
        Returns:
            Formatted string
        """
        template = self.get_config_value("template", "{{input}}")
        
        return self._substitute_template(template, data, state)
    
    def _extract_transform(self, data: Any, state: WorkflowState) -> Any:
        """
        Extract transformation - extract specific fields from data.
        
        Args:
            data: Input data
            state: Workflow state
            
        Returns:
            Extracted data
        """
        fields = self.get_config_value("extractFields", [])
        
        if not fields:
            return data
        
        if isinstance(data, dict):
            return {field: data.get(field) for field in fields if field in data}
        elif isinstance(data, list):
            return [
                {field: item.get(field) for field in fields if field in item}
                for item in data
                if isinstance(item, dict)
            ]
        else:
            return data
    
    def _aggregate_transform(self, data: Any, state: WorkflowState) -> Any:
        """
        Aggregate transformation - aggregate list data.
        
        Args:
            data: Input data (should be a list)
            state: Workflow state
            
        Returns:
            Aggregated result
        """
        if not isinstance(data, list):
            return data
        
        operation = self.get_config_value("aggregateOperation", "count")
        field = self.get_config_value("aggregateField")
        
        if operation == "count":
            return len(data)
        
        elif operation == "sum":
            if field:
                return sum(item.get(field, 0) for item in data if isinstance(item, dict))
            else:
                return sum(data)
        
        elif operation == "average":
            if not data:
                return 0
            if field:
                values = [item.get(field, 0) for item in data if isinstance(item, dict)]
            else:
                values = data
            return sum(values) / len(values) if values else 0
        
        elif operation == "min":
            if field:
                return min((item.get(field) for item in data if isinstance(item, dict)), default=None)
            else:
                return min(data) if data else None
        
        elif operation == "max":
            if field:
                return max((item.get(field) for item in data if isinstance(item, dict)), default=None)
            else:
                return max(data) if data else None
        
        elif operation == "concat":
            if field:
                return " ".join(str(item.get(field, "")) for item in data if isinstance(item, dict))
            else:
                return " ".join(str(item) for item in data)
        
        return data
    
    def _substitute_template(
        self,
        template: str,
        data: Any,
        state: WorkflowState
    ) -> str:
        """
        Substitute variables in a template string.
        
        Supports:
        - {{field}} - field from data
        - {{var.name}} - variable from state
        - {{node.id}} - output from another node
        
        Args:
            template: Template string
            data: Current data context
            state: Workflow state
            
        Returns:
            Substituted string
        """
        result = template
        
        # Substitute data fields
        if isinstance(data, dict):
            for key, value in data.items():
                result = result.replace(f"{{{{{key}}}}}", str(value))
        else:
            result = result.replace("{{input}}", str(data))
        
        # Substitute variables
        for key, value in state.get("variables", {}).items():
            result = result.replace(f"{{{{var.{key}}}}}", str(value))
        
        # Substitute node outputs
        for node_id, output in state.get("node_outputs", {}).items():
            node_output_value = output.get("output")
            if node_output_value:
                result = result.replace(f"{{{{node.{node_id}}}}}", str(node_output_value))
        
        return result


