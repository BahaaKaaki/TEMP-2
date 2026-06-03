"""
Authentication middleware to store user context for later use.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from jose import jwt, JWTError
from config.settings import settings
import logging

logger = logging.getLogger(__name__)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract user from JWT and store in request state.
    
    The actual database context setting happens in dependencies after
    the database session is created.
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next):
        # Extract token and store user_id in request state
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            
            try:
                # Decode token
                payload = jwt.decode(
                    token,
                    settings.JWT_SECRET_KEY,
                    algorithms=[settings.JWT_ALGORITHM]
                )
                user_id = payload.get("sub")
                
                if user_id:
                    # Store user_id in request state for dependencies to use
                    request.state.user_id = user_id
                    
            except JWTError as e:
                logger.debug(f"JWT validation failed: {e}")
                # Continue without setting context
        
        response = await call_next(request)
        return response
