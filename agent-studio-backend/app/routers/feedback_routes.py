"""
User feedback routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid
import logging

from db.pgsql import get_write_db
from db.models import User, UserFeedback, FeedbackCategory
from core.dependencies import get_current_user
from schemas import SubmitFeedbackRequest, FeedbackResponse, FeedbackListResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/feedback",
    tags=["Feedback"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)

VALID_CATEGORIES = {e.value for e in FeedbackCategory}


@router.post("", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    payload: SubmitFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_write_db),
):
    """Submit new feedback."""
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
        )

    feedback = UserFeedback(
        id=str(uuid.uuid4()),
        userId=current_user.id,
        category=FeedbackCategory(payload.category),
        subject=payload.subject,
        message=payload.message,
        rating=payload.rating,
        pageUrl=payload.pageUrl,
        status="new",
    )

    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    logger.info("Feedback submitted by user %s: [%s] %s", current_user.id, payload.category, payload.subject)

    return FeedbackResponse(
        id=feedback.id,
        userId=feedback.userId,
        category=feedback.category.value,
        subject=feedback.subject,
        message=feedback.message,
        rating=feedback.rating,
        status=feedback.status,
        createdAt=feedback.createdAt,
    )


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_write_db),
):
    """List feedback submitted by the current user."""
    query = (
        select(UserFeedback)
        .where(UserFeedback.userId == current_user.id)
        .order_by(UserFeedback.createdAt.desc())
    )
    result = await db.execute(query)
    items = result.scalars().all()

    count_query = select(func.count()).select_from(UserFeedback).where(UserFeedback.userId == current_user.id)
    total = (await db.execute(count_query)).scalar() or 0

    return FeedbackListResponse(
        feedback=[
            FeedbackResponse(
                id=f.id,
                userId=f.userId,
                category=f.category.value,
                subject=f.subject,
                message=f.message,
                rating=f.rating,
                status=f.status,
                createdAt=f.createdAt,
            )
            for f in items
        ],
        total=total,
    )
