"""
Condition node executor.

Evaluates a condition and determines the next path in the workflow.
Supports multiple branches (if/else if/else) with expression-based routing.
"""

from typing import Any, Dict, List, Optional
import ast
import logging
import operator
import re

from .base import BaseNode
from ..state import WorkflowState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safe AST-based expression evaluator (replaces eval())
# ---------------------------------------------------------------------------

_SAFE_BUILTINS = {
    "True": True,
    "False": False,
    "None": None,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
}

_ALLOWED_CALL_NAMES = frozenset(_SAFE_BUILTINS.keys()) - {"True", "False", "None"}

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}


def _safe_eval(expr: str, context: dict) -> Any:
    """Evaluate *expr* against *context* using a strict AST whitelist."""
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body, context)


def _eval_node(node: ast.AST, ctx: dict) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, ctx)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in _SAFE_BUILTINS:
            return _SAFE_BUILTINS[node.id]
        if node.id in ctx:
            return ctx[node.id]
        raise NameError(f"Name '{node.id}' is not defined")

    if isinstance(node, ast.Attribute):
        value = _eval_node(node.value, ctx)
        return getattr(value, node.attr)

    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, ctx)
        sl = _eval_node(node.slice, ctx)
        return value[sl]

    if isinstance(node, ast.Index):  # Python 3.8 compat
        return _eval_node(node.value, ctx)

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for v in node.values:
                result = _eval_node(v, ctx)
                if not result:
                    return result
            return result
        result = False
        for v in node.values:
            result = _eval_node(v, ctx)
            if result:
                return result
        return result

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, ctx)
        for op_node, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, ctx)
            op_func = _CMP_OPS.get(type(op_node))
            if op_func is None:
                raise ValueError(f"Unsupported comparison operator: {type(op_node).__name__}")
            if not op_func(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, ctx)
        right = _eval_node(node.right, ctx)
        op_func = _BIN_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
        return op_func(left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, ctx)
        op_func = _UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(operand)

    if isinstance(node, ast.IfExp):
        test = _eval_node(node.test, ctx)
        return _eval_node(node.body, ctx) if test else _eval_node(node.orelse, ctx)

    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _ALLOWED_CALL_NAMES:
            args = [_eval_node(a, ctx) for a in node.args]
            return _SAFE_BUILTINS[func.id](*args)
        raise ValueError(f"Function calls are restricted to: {', '.join(sorted(_ALLOWED_CALL_NAMES))}")

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(e, ctx) for e in node.elts]

    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


class DotDict:
    """
    Dictionary wrapper that allows dot notation access to nested fields.
    
    Enables expressions like: obj.field.subfield instead of obj['field']['subfield']
    
    Example:
        data = {"output_parsed": {"classification": "return_item"}}
        wrapper = DotDict(data)
        wrapper.output_parsed.classification  # Returns "return_item"
    """
    
    def __init__(self, data: Any):
        self._data = data
    
    def __getattr__(self, name: str) -> Any:
        """Allow dot notation access."""
        if name.startswith("_"):
            # Private attributes
            return object.__getattribute__(self, name)
        
        if isinstance(self._data, dict):
            value = self._data.get(name)
            if isinstance(value, (dict, list)):
                return DotDict(value)
            return value
        elif isinstance(self._data, list):
            # For list access by index
            try:
                index = int(name)
                value = self._data[index]
                if isinstance(value, (dict, list)):
                    return DotDict(value)
                return value
            except (ValueError, IndexError):
                return None
        return None
    
    def __getitem__(self, key: Any) -> Any:
        """Allow bracket notation access."""
        if isinstance(self._data, dict):
            value = self._data.get(key)
            if isinstance(value, (dict, list)):
                return DotDict(value)
            return value
        elif isinstance(self._data, list):
            value = self._data[key]
            if isinstance(value, (dict, list)):
                return DotDict(value)
            return value
        return None
    
    def __repr__(self) -> str:
        return f"DotDict({self._data})"
    
    def __str__(self) -> str:
        return str(self._data)
    
    def __eq__(self, other: Any) -> bool:
        """Support equality comparison."""
        if isinstance(other, DotDict):
            return self._data == other._data
        return self._data == other
    
    def __ne__(self, other: Any) -> bool:
        """Support inequality comparison."""
        return not self.__eq__(other)
    
    def __bool__(self) -> bool:
        """Support boolean conversion."""
        return bool(self._data)


class ConditionNode(BaseNode):
    """
    Condition node executor.
    
    Evaluates a condition and sets the next node based on the result.
    """
    
    # Supported operators
    OPERATORS = {
        "equals": operator.eq,
        "not_equals": operator.ne,
        "greater_than": operator.gt,
        "less_than": operator.lt,
        "greater_or_equal": operator.ge,
        "less_or_equal": operator.le,
        "contains": lambda a, b: b in a if isinstance(a, (str, list, dict)) else False,
        "not_contains": lambda a, b: b not in a if isinstance(a, (str, list, dict)) else False,
        "is_empty": lambda a, b: len(a) == 0 if hasattr(a, '__len__') else not bool(a),
        "is_not_empty": lambda a, b: len(a) > 0 if hasattr(a, '__len__') else bool(a),
    }
    
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the condition node with multiple branch support.
        
        Evaluates conditions in order (if, else if, else) and determines
        the next node based on the first matching condition.
        
        Args:
            state: Current workflow state
            
        Returns:
            Condition evaluation result with routing information
        """
        # Get conditions configuration (array of condition objects)
        conditions = self.get_config_value("conditions", [])
        
        if not conditions:
            logger.warning("No conditions configured for node %s", self.node_id)
            return {
                "condition_result": False,
                "matched_condition": None,
                "error": "No conditions configured"
            }
        
        logger.info("📊 Evaluating %d condition(s) for node %s", len(conditions), self.label)
        
        matched_condition_id = None
        matched_expression = None
        evaluation_result = False
        
        # Evaluate conditions in order
        for idx, condition in enumerate(conditions):
            condition_id = condition.get("id", f"condition_{idx}")
            condition_type = condition.get("type", "if")  # "if", "else_if", or "else"
            expression = condition.get("expression", "")
            case_name = condition.get("caseName", "")
            
            logger.debug("🔍 Evaluating condition %s (%s): %s", 
                         condition_id, condition_type, expression[:100])
            
            # "else" branches always match if reached
            if condition_type == "else":
                logger.debug("✅ Matched ELSE branch")
                matched_condition_id = condition_id
                matched_expression = "else (default)"
                evaluation_result = True
                break
            
            # Evaluate expression for "if" and "else_if"
            try:
                result = self._evaluate_expression(expression, state)
                logger.debug("   Result: %s", result)
                
                if result:
                    matched_condition_id = condition_id
                    matched_expression = expression
                    evaluation_result = True
                    logger.info("✅ Matched condition: %s", case_name or condition_id)
                    break
                    
            except Exception as e:
                logger.error("❌ Error evaluating condition %s: %s", condition_id, e)
                # Continue to next condition on error
                continue
        
        if not matched_condition_id:
            logger.warning("⚠️ No condition matched - workflow may have undefined behavior")
        
        return {
            "condition_result": evaluation_result,
            "matched_condition": matched_condition_id,
            "matched_expression": matched_expression,
            "output": {
                "matched_condition_id": matched_condition_id,
                "matched_expression": matched_expression
            }
        }
    
    def _evaluate_expression(self, expression: str, state: WorkflowState) -> bool:
        """
        Evaluate an expression with support for nested field access and logical operators.
        
        Supports:
        - input.output_parsed.field - Access input data
        - node.{node_id}.output_parsed.field - Access previous node outputs
        - variables.field - Access workflow variables
        - Comparison operators: ==, !=, >, <, >=, <=
        - Logical operators: && (AND), || (OR), ! (NOT)
        - Grouping with parentheses: ( )
        - String literals with quotes: "value" or 'value'
        
        For security, uses restricted evaluation with safe builtins.
        
        Args:
            expression: The expression to evaluate
            state: Current workflow state
            
        Returns:
            Expression result (True/False)
        """
        if not expression or not expression.strip():
            return False
        
        try:
            # Build evaluation context with safe builtins
            safe_context = self._build_evaluation_context(state)
            
            # Normalize expression: convert && to 'and', || to 'or', ! to 'not'
            # This allows CEL-like syntax while using Python's evaluation
            normalized_expr = self._normalize_expression(expression)
            
            # Log context for debugging
            logger.debug("=" * 80)
            logger.debug("🔍 CONDITION EVALUATION DEBUG")
            logger.debug("=" * 80)
            logger.debug("Original expression: %s", expression)
            logger.debug("Normalized expression: %s", normalized_expr)
            logger.debug("Available context keys: %s", list(safe_context.keys()))
            
            # Log the FULL input data structure for debugging
            if "input" in safe_context:
                input_obj = safe_context["input"]
                if hasattr(input_obj, '_data'):
                    import json
                    logger.debug("📦 FULL Input Data:")
                    try:
                        logger.debug(json.dumps(input_obj._data, indent=2, default=str))
                    except:
                        logger.debug(str(input_obj._data))
                    
                    logger.debug("\n📋 Input data structure keys: %s", list(input_obj._data.keys()) if isinstance(input_obj._data, dict) else type(input_obj._data))
                    
                    if isinstance(input_obj._data, dict) and "deliverable" in input_obj._data:
                        logger.debug("   ✅ deliverable EXISTS")
                        deliverable_data = input_obj._data["deliverable"]
                        logger.debug("   └─ deliverable type: %s", type(deliverable_data))
                        if isinstance(deliverable_data, dict):
                            logger.debug("   └─ deliverable keys: %s", list(deliverable_data.keys()))
                            for key, value in deliverable_data.items():
                                if isinstance(value, dict):
                                    logger.debug("      └─ %s (dict): %s", key, list(value.keys()))
                                else:
                                    logger.debug("      └─ %s (%s): %s", key, type(value).__name__, str(value)[:100])
                    else:
                        logger.debug("   ❌ deliverable NOT FOUND in input data")
            logger.debug("=" * 80)
            
            result = _safe_eval(normalized_expr, safe_context)
            logger.debug("Expression result: %s", result)
            
            return bool(result)
            
        except AttributeError as e:
            # Provide helpful error message for common path issues
            logger.error("❌ Error evaluating expression '%s': %s", expression, e)
            logger.error("💡 Hint: Check your path format. Common formats:")
            logger.error("   • input.deliverable.fieldName (for structured output)")
            logger.error("   • input.response (for chat response)")
            logger.error("   • Check the actual output structure in workflow logs")
            return False
        except Exception as e:
            logger.error("Error evaluating expression '%s': %s", expression, e, exc_info=True)
            return False
    
    def _normalize_expression(self, expression: str) -> str:
        """
        Normalize expression syntax from CEL-like to Python.
        
        Converts:
        - && to 'and'
        - || to 'or'
        - ! to 'not ' (with space)
        
        Args:
            expression: Original expression
            
        Returns:
            Normalized Python expression
        """
        # Replace logical operators (order matters!)
        # Use regex to avoid replacing within strings
        import re
        
        # Track whether we're inside a string
        result = []
        i = 0
        in_string = False
        string_char = None
        
        while i < len(expression):
            char = expression[i]
            
            # Handle string boundaries
            if char in ('"', "'") and (i == 0 or expression[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
                result.append(char)
                i += 1
                continue
            
            # If inside string, just copy character
            if in_string:
                result.append(char)
                i += 1
                continue
            
            # Replace && with and
            if i + 1 < len(expression) and expression[i:i+2] == '&&':
                result.append(' and ')
                i += 2
                continue
            
            # Replace || with or
            if i + 1 < len(expression) and expression[i:i+2] == '||':
                result.append(' or ')
                i += 2
                continue
            
            # Replace ! with not (but not != which is handled separately)
            if char == '!' and (i + 1 >= len(expression) or expression[i+1] != '='):
                result.append(' not ')
                i += 1
                continue
            
            # Copy character as-is
            result.append(char)
            i += 1
        
        normalized = ''.join(result)
        
        # Clean up extra spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _build_evaluation_context(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Build the evaluation context from workflow state.
        
        Creates objects that support dot notation for accessing nested fields:
        - input.output_parsed.field
        - node.{node_id}.output_parsed.field
        - variables.field
        
        Args:
            state: Current workflow state
            
        Returns:
            Dictionary with evaluation context
        """
        # Get connected source nodes (nodes that connect to this condition node)
        # For now, we'll look at the most recent node output as "input"
        node_outputs = state.get("node_outputs", {})
        
        # Find the most recent node output (highest execution order)
        input_data = None
        if node_outputs:
            # Get the last executed node's output
            last_node_id = max(node_outputs.keys(), 
                              key=lambda k: node_outputs[k].get("timestamp", ""))
            last_output = node_outputs[last_node_id].get("output", {})
            input_data = last_output
        
        # Fallback to input_data if no node outputs
        if input_data is None:
            input_data = state.get("input_data", {})
        
        # Wrap input_data with deliverable parent if it has the deliverable structure
        # This allows both input.deliverable.output_parsed.field and input.output_parsed.field to work
        if input_data and "deliverable" in input_data:
            # Agent output structure: { deliverable: { output_text, output_parsed, ... } }
            input_wrapper = DotDict(input_data)
        elif input_data:
            # For backwards compatibility, wrap input_data itself
            input_wrapper = DotDict(input_data)
        else:
            input_wrapper = DotDict({})
        
        # Create node wrappers for accessing specific node outputs
        node_wrapper = {}
        for node_id, node_output in node_outputs.items():
            output_data = node_output.get("output", {})
            node_wrapper[node_id] = DotDict(output_data)
        
        # Create variables wrapper
        variables_wrapper = DotDict(state.get("variables", {}))
        
        context = {
            "input": input_wrapper,
            "node": node_wrapper,
            "variables": variables_wrapper,
        }
        
        return context


