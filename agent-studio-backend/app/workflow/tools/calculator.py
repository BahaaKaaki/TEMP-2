"""
Calculator tool implementation.

Provides mathematical calculation capabilities.
"""

from typing import Optional, Type, ClassVar, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
import logging
import ast
import operator

logger = logging.getLogger(__name__)


class CalculatorInput(BaseModel):
    """Input schema for calculator tool."""
    expression: str = Field(description="The mathematical expression to evaluate")


class CalculatorTool(BaseTool):
    """
    Calculator tool.
    
    Evaluates mathematical expressions safely.
    """
    
    name: str = "calculator"
    description: str = (
        "Calculate mathematical expressions. "
        "Supports basic arithmetic operations: +, -, *, /, **, (), and numbers. "
        "Example: '(5 + 3) * 2'"
    )
    args_schema: Type[BaseModel] = CalculatorInput
    
    # Safe operators - ClassVar for Pydantic compatibility
    SAFE_OPERATORS: ClassVar[Dict[Any, Any]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }
    
    def _run(
        self,
        expression: str,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """
        Execute calculation.
        
        Args:
            expression: Mathematical expression
            run_manager: Callback manager
            
        Returns:
            Calculation result as string
        """
        try:
            logger.info("Calculating: %s", expression)
            result = self._safe_eval(expression)
            return f"{expression} = {result}"
        except Exception as e:
            logger.error("Calculation error: %s", e)
            return f"Error calculating '{expression}': {str(e)}"
    
    async def _arun(
        self,
        expression: str,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """
        Async execution of calculation.
        
        Args:
            expression: Mathematical expression
            run_manager: Callback manager
            
        Returns:
            Calculation result as string
        """
        return self._run(expression, run_manager)
    
    def _safe_eval(self, expression: str) -> float:
        """
        Safely evaluate a mathematical expression.
        
        Uses AST parsing to only allow safe operations.
        
        Args:
            expression: Mathematical expression
            
        Returns:
            Evaluation result
            
        Raises:
            ValueError: If expression contains unsafe operations
        """
        try:
            node = ast.parse(expression, mode='eval').body
            return self._eval_node(node)
        except Exception as e:
            raise ValueError(f"Invalid expression: {str(e)}") from e
    
    def _eval_node(self, node):
        """
        Recursively evaluate an AST node.
        
        Args:
            node: AST node
            
        Returns:
            Evaluation result
        """
        if isinstance(node, ast.Constant):
            return node.value
        
        elif isinstance(node, ast.Num):  # Backwards compatibility
            return node.n
        
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)
            
            if op_type not in self.SAFE_OPERATORS:
                raise ValueError(f"Unsupported operation: {op_type.__name__}")
            
            return self.SAFE_OPERATORS[op_type](left, right)
        
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_type = type(node.op)
            
            if op_type not in self.SAFE_OPERATORS:
                raise ValueError(f"Unsupported operation: {op_type.__name__}")
            
            return self.SAFE_OPERATORS[op_type](operand)
        
        else:
            raise ValueError(f"Unsupported node type: {type(node).__name__}")


