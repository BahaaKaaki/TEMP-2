"""
Workflow execution router for running and managing workflow executions.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
import logging
from datetime import datetime
import json

from db.pgsql import get_static_read_db
from core.dependencies import get_db_with_user_context
from db.models import ExecutionEntity, ExecutionData, WorkflowEntity, User
from core.dependencies import get_current_user
from schemas import (
    WorkflowExecutionInput,
    WorkflowExecutionResponse,
    ExecutionStatusResponse,
    ExecutionResumeInput,
    ExecutionListResponse
)
from workflow.executor import WorkflowExecutor
from utils.errors import safe_error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["Workflow Execution"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


@router.post("/workflows/{workflow_id}/execute", response_model=WorkflowExecutionResponse)
async def execute_workflow(
    workflow_id: str,
    execution_input: WorkflowExecutionInput,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Execute a workflow.
    
    Starts workflow execution and returns the execution ID.
    Use the execution ID to query status or stream results.
    
    Args:
        workflow_id: Workflow UUID
        execution_input: Execution input data
        db: Database session
        
    Returns:
        Execution response with ID and status
    """
    try:
        logger.debug("Executing workflow: %s", workflow_id)
        
        executor = WorkflowExecutor(db, user_id=str(current_user.id))
        
        # Execute workflow
        result = await executor.execute_workflow(
            workflow_id=workflow_id,
            input_data=execution_input.input_data,
            initial_message=execution_input.initial_message,
            variables=execution_input.variables
        )
        
        return WorkflowExecutionResponse(
            execution_id=result.execution_id,
            workflow_id=result.workflow_id,
            status=result.status,
            started_at=datetime.utcnow().isoformat(),
            message=f"Workflow execution {result.status}"
        )
        
    except ValueError as e:
        logger.error("Validation error executing workflow: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to execute workflow")
        ) from e


@router.get("/executions/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status(
    execution_id: int,
    db: AsyncSession = Depends(get_static_read_db)
):
    """
    Get the status and results of a workflow execution.
    
    Args:
        execution_id: Execution ID
        db: Database session
        
    Returns:
        Execution status and results
    """
    try:
        # Query execution
        exec_query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        exec_result = await db.execute(exec_query)
        execution = exec_result.scalar_one_or_none()
        
        if not execution:
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
        
        # Query workflow for name
        wf_query = select(WorkflowEntity).where(WorkflowEntity.id == execution.workflowId)
        wf_result = await db.execute(wf_query)
        workflow = wf_result.scalar_one_or_none()
        workflow_name = workflow.name if workflow else "Unknown"
        
        # Query execution data
        data_query = select(ExecutionData).where(ExecutionData.executionId == execution_id)
        data_result = await db.execute(data_query)
        execution_data = data_result.scalar_one_or_none()
        
        # Parse execution data
        output_data = None
        node_outputs = {}
        error = None
        error_node = None
        current_step = 0
        total_steps = 0
        
        if execution_data and execution_data.data:
            try:
                state = json.loads(execution_data.data)
                output_data = state.get("output_data")
                node_outputs = state.get("node_outputs", {})
                error = state.get("error")
                error_node = state.get("error_node")
                current_step = state.get("metadata", {}).get("current_step", 0)
                total_steps = state.get("metadata", {}).get("total_steps", 0)
            except json.JSONDecodeError:
                logger.warning("Failed to parse execution data for execution %d", execution_id)
        
        # Calculate duration
        duration_seconds = None
        if execution.startedAt and execution.stoppedAt:
            duration_seconds = (execution.stoppedAt - execution.startedAt).total_seconds()
        
        return ExecutionStatusResponse(
            execution_id=execution.id,
            workflow_id=execution.workflowId,
            workflow_name=workflow_name,
            status=execution.status,
            started_at=execution.startedAt.isoformat() if execution.startedAt else None,
            completed_at=execution.stoppedAt.isoformat() if execution.stoppedAt else None,
            duration_seconds=duration_seconds,
            current_step=current_step,
            total_steps=total_steps,
            output_data=output_data,
            error=error,
            error_node=error_node,
            node_outputs=node_outputs
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to get execution status")
        ) from e


@router.post("/executions/{execution_id}/resume", response_model=WorkflowExecutionResponse)
async def resume_execution(
    execution_id: int,
    resume_input: ExecutionResumeInput,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Resume a paused workflow execution with user input.
    
    Args:
        execution_id: Execution ID
        resume_input: User input to resume with
        db: Database session
        
    Returns:
        Updated execution response
    """
    try:
        logger.debug("Resuming execution: %d", execution_id)
        
        executor = WorkflowExecutor(db, user_id=str(current_user.id))
        
        # Resume execution
        result = await executor.resume_execution(
            execution_id=execution_id,
            user_input=resume_input.user_input
        )
        
        return WorkflowExecutionResponse(
            execution_id=result.execution_id,
            workflow_id=result.workflow_id,
            status=result.status,
            started_at=datetime.utcnow().isoformat(),
            message=f"Workflow execution resumed: {result.status}"
        )
        
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to resume execution")
        ) from e


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: int,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Cancel a running workflow execution.
    
    Args:
        execution_id: Execution ID
        db: Database session
        
    Returns:
        Success message
    """
    try:
        logger.debug("Cancelling execution: %d", execution_id)
        
        executor = WorkflowExecutor(db, user_id=str(current_user.id))
        
        # Cancel execution
        success = await executor.cancel_execution(execution_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
        
        return {"message": f"Execution {execution_id} cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to cancel execution")
        ) from e


@router.get("/workflows/{workflow_id}/executions", response_model=ExecutionListResponse)
async def list_workflow_executions(
    workflow_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_static_read_db)
):
    """
    List executions for a specific workflow.
    
    Args:
        workflow_id: Workflow UUID
        page: Page number
        page_size: Items per page
        status: Optional status filter
        db: Database session
        
    Returns:
        Paginated list of executions
    """
    try:
        # Build query
        query = select(ExecutionEntity).where(ExecutionEntity.workflowId == workflow_id)
        
        if status:
            query = query.where(ExecutionEntity.status == status)
        
        # Get total count
        count_query = select(func.count(ExecutionEntity.id)).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar()
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.order_by(ExecutionEntity.createdAt.desc()).offset(offset).limit(page_size)
        
        # Execute query
        result = await db.execute(query)
        executions = result.scalars().all()
        
        # Get workflow name
        wf_query = select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        wf_result = await db.execute(wf_query)
        workflow = wf_result.scalar_one_or_none()
        workflow_name = workflow.name if workflow else "Unknown"
        
        # Build response items
        items = []
        for execution in executions:
            duration_seconds = None
            if execution.startedAt and execution.stoppedAt:
                duration_seconds = (execution.stoppedAt - execution.startedAt).total_seconds()
            
            items.append(ExecutionStatusResponse(
                execution_id=execution.id,
                workflow_id=execution.workflowId,
                workflow_name=workflow_name,
                status=execution.status,
                started_at=execution.startedAt.isoformat() if execution.startedAt else None,
                completed_at=execution.stoppedAt.isoformat() if execution.stoppedAt else None,
                duration_seconds=duration_seconds,
                current_step=0,
                total_steps=0,
                output_data=None,
                error=None,
                error_node=None,
                node_outputs={}
            ))
        
        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size
        
        return ExecutionListResponse(
            total=total,
            items=items,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to list executions")
        ) from e


@router.websocket("/workflows/{workflow_id}/stream")
async def stream_workflow_execution(
    websocket: WebSocket,
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Execute a workflow with real-time event streaming via WebSocket.
    
    Client sends initial execution parameters, then receives events as workflow executes.
    
    Args:
        websocket: WebSocket connection
        workflow_id: Workflow UUID
        db: Database session
    """
    await websocket.accept()
    
    try:
        # Receive execution input from client
        input_data = await websocket.receive_json()
        
        logger.debug("Starting streaming execution for workflow: %s", workflow_id)
        
        executor = WorkflowExecutor(db, user_id=str(current_user.id))
        
        # Stream execution events
        async for event in executor.stream_workflow_execution(
            workflow_id=workflow_id,
            input_data=input_data.get("input_data", {}),
            initial_message=input_data.get("initial_message"),
            variables=input_data.get("variables", {})
        ):
            # Send event to client
            await websocket.send_json(event)
        
        # Close connection
        await websocket.close()
        
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for workflow %s", workflow_id)
    except Exception as e:
        logger.error("Error in streaming execution: %s", e, exc_info=True)
        try:
            await websocket.send_json({
                "event_type": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Internal error"
            })
            await websocket.close()
        except:
            pass

