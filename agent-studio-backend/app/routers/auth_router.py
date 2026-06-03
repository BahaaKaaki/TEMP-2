"""
Authentication router for user registration, login, and token management.

Provides endpoints for:
- User registration
- User login
- Token refresh (cookie-based rotation)
- OAuth login via Microsoft Entra ID (code-exchange flow)
- Logout with server-side token revocation
- Get/update current user profile
- Change password
"""
import logging
import secrets
import hmac
import hashlib
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from msal import ConfidentialClientApplication

from schemas import (
    RegisterRequest,
    LoginRequest,
    RefreshTokenRequest,
    OAuthCodeExchangeRequest,
    TokenResponse,
    UserResponse,
    ChangePasswordRequest,
    UpdateProfileRequest
)
from services.auth_service import (
    AuthService,
    EmailAlreadyExistsException,
    InvalidCredentialsException,
    DisabledAccountException,
    InvalidTokenException
)
from core.dependencies import get_auth_service, get_current_user
from db.models import User
from config.settings import settings
from utils.rate_limit import limiter

logger = logging.getLogger(__name__)

REFRESH_COOKIE_NAME = "refresh_token"
COOKIE_MAX_AGE = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
    responses={
        401: {"description": "Unauthorized - Invalid or missing credentials"},
        403: {"description": "Forbidden - Account disabled or insufficient permissions"}
    }
)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/api/auth",
        domain=settings.COOKIE_DOMAIN,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/api/auth",
        domain=settings.COOKIE_DOMAIN,
    )


def _sign_state(state: str) -> str:
    """Create an HMAC signature for the OAuth state parameter."""
    return hmac.new(
        settings.JWT_SECRET_KEY.encode(),
        state.encode(),
        hashlib.sha256,
    ).hexdigest()


# ============================================================================
# Registration & Login
# ============================================================================

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account with email and password"
)
@limiter.limit(f"{settings.RATE_LIMIT_AUTH_PER_MINUTE}/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        user = await auth_service.register(
            email=body.email,
            password=body.password,
            first_name=body.firstName,
            last_name=body.lastName
        )
        access_token, refresh_token = await auth_service.create_tokens(user)

        resp = JSONResponse(
            status_code=201,
            content=TokenResponse(
                access_token=access_token,
                token_type="bearer",
                expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            ).model_dump(),
        )
        _set_refresh_cookie(resp, refresh_token)
        return resp

    except EmailAlreadyExistsException as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.exception("Registration failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login user",
    description="Authenticate user with email and password"
)
@limiter.limit(f"{settings.RATE_LIMIT_AUTH_PER_MINUTE}/minute")
async def login(
    request: Request,
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        user = await auth_service.authenticate(
            email=body.email,
            password=body.password
        )
        access_token, refresh_token = await auth_service.create_tokens(user)

        resp = JSONResponse(
            content=TokenResponse(
                access_token=access_token,
                token_type="bearer",
                expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            ).model_dump(),
        )
        _set_refresh_cookie(resp, refresh_token)
        return resp

    except (InvalidCredentialsException, DisabledAccountException) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )


# ============================================================================
# Token Refresh (cookie-based with rotation)
# ============================================================================

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Get a new access token using the refresh token cookie"
)
@limiter.limit(f"{settings.RATE_LIMIT_REFRESH_PER_MINUTE}/minute")
async def refresh_token(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    old_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if not old_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        new_access, new_refresh = await auth_service.refresh_access_token(old_refresh)

        resp = JSONResponse(
            content=TokenResponse(
                access_token=new_access,
                token_type="bearer",
                expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            ).model_dump(),
        )
        _set_refresh_cookie(resp, new_refresh)
        return resp

    except (InvalidTokenException, DisabledAccountException) as e:
        resp = JSONResponse(
            status_code=401,
            content={"detail": str(e)},
        )
        _clear_refresh_cookie(resp)
        return resp


# ============================================================================
# Logout (server-side revocation)
# ============================================================================

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout user",
    description="Revoke refresh token and clear auth cookie"
)
async def logout(request: Request):
    old_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if old_refresh:
        from services.auth_service import AuthService as _AS
        try:
            from utils.security import verify_token
            payload = verify_token(old_refresh, token_type="refresh")
            jti = payload.get("jti")
            if jti:
                from db.redis import get_redis
                redis = await get_redis()
                await redis.delete(f"refresh_jti:{jti}")
        except Exception:
            pass

    resp = Response(status_code=204)
    _clear_refresh_cookie(resp)
    return resp


# ============================================================================
# Profile endpoints (protected)
# ============================================================================

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get profile information for the currently authenticated user"
)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update user profile",
    description="Update profile information for the currently authenticated user"
)
async def update_user_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    updated_user = await auth_service.update_profile(
        user_id=current_user.id,
        first_name=request.firstName,
        last_name=request.lastName
    )
    return UserResponse.model_validate(updated_user)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change password",
    description="Change password for the currently authenticated user"
)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        await auth_service.update_password(
            user_id=current_user.id,
            current_password=request.current_password,
            new_password=request.new_password
        )
    except InvalidCredentialsException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ============================================================================
# Microsoft Entra ID OAuth Endpoints
# ============================================================================

def _get_msal_app() -> ConfidentialClientApplication:
    if not settings.MICROSOFT_CLIENT_ID or not settings.MICROSOFT_TENANT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Microsoft SSO is not configured on this server"
        )
    return ConfidentialClientApplication(
        client_id=settings.MICROSOFT_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}",
        client_credential=settings.MICROSOFT_CLIENT_SECRET,
    )


# Delegated Microsoft Graph scopes. All three require admin consent at the
# tenant level, but they are far less invasive than the equivalent
# Application permissions (the app can only do what the *signed-in user*
# could already do in the regular Graph UI).
#
#   User.Read              -- profile (givenName, surname, mail)
#   GroupMember.Read.All   -- /me/getMemberObjects (flattened group list,
#                             handles nested groups, no 200-group token cap)
#   Group.Read.All         -- /groups?$filter=startswith(displayName,…) for
#                             the share-dialog typeahead (so admins can pick
#                             *any* group in the tenant, not just ones we've
#                             cached)
MICROSOFT_SCOPES = ["User.Read", "GroupMember.Read.All", "Group.Read.All"]
CALLBACK_PATH = "/api/auth/microsoft/callback"


async def _fetch_user_group_ids(
    client: httpx.AsyncClient, ms_access_token: str
) -> list[str]:
    """
    Return the flattened list of AD group GUIDs the user is a (transitive)
    member of, via Microsoft Graph /me/getMemberObjects.

    Returns an empty list if the call fails (e.g. tenant hasn't granted the
    scope yet). Logs at WARN so admins can spot a misconfigured app
    registration without breaking the login flow.
    """
    try:
        resp = await client.post(
            "https://graph.microsoft.com/v1.0/me/getMemberObjects",
            headers={
                "Authorization": f"Bearer {ms_access_token}",
                "Content-Type": "application/json",
            },
            # securityEnabledOnly=False returns ALL groups (security + M365 +
            # distribution). Set to True if you only want security groups.
            json={"securityEnabledOnly": False},
        )
    except Exception as exc:
        logger.warning("MS Graph getMemberObjects failed (network): %s", exc)
        return []

    if resp.status_code != 200:
        logger.warning(
            "MS Graph getMemberObjects failed (HTTP %s): %s",
            resp.status_code, resp.text[:300],
        )
        return []

    return list(resp.json().get("value", []))


async def _fetch_groups_metadata(
    client: httpx.AsyncClient, ms_access_token: str, group_ids: list[str]
) -> list[tuple[str, "str | None"]]:
    """
    Resolve a list of AD group GUIDs to ``(id, displayName)`` tuples via
    Microsoft Graph /directoryObjects/getByIds. Falls back to ``(id, None)``
    for any id we can't resolve.
    """
    if not group_ids:
        return []
    try:
        # Graph caps the batch at 1000 ids per call.
        resolved: dict[str, "str | None"] = {gid: None for gid in group_ids}
        for i in range(0, len(group_ids), 1000):
            batch = group_ids[i : i + 1000]
            resp = await client.post(
                "https://graph.microsoft.com/v1.0/directoryObjects/getByIds",
                headers={
                    "Authorization": f"Bearer {ms_access_token}",
                    "Content-Type": "application/json",
                },
                json={"ids": batch, "types": ["group"]},
            )
            if resp.status_code != 200:
                logger.warning(
                    "MS Graph getByIds failed (HTTP %s): %s",
                    resp.status_code, resp.text[:300],
                )
                continue
            for obj in resp.json().get("value", []):
                gid = obj.get("id")
                if gid:
                    resolved[gid] = obj.get("displayName")
        return [(gid, resolved.get(gid)) for gid in group_ids]
    except Exception as exc:
        logger.warning("MS Graph getByIds failed: %s", exc)
        return [(gid, None) for gid in group_ids]


def _build_redirect_uri(request: Request) -> str:
    """Build the OAuth callback URL that must match the one registered in
    Microsoft Entra ID.

    When AUTHENTICATION_REDIRECTION is configured (gateway / production), use it
    directly so the redirect URI is deterministic regardless of which
    internal host handles the request.

    When it is empty (local dev, simple docker-compose), fall back to
    auto-detection from X-Forwarded-* headers or the raw request URL.
    """
    if settings.AUTHENTICATION_REDIRECTION:
        base = settings.AUTHENTICATION_REDIRECTION.rstrip("/")
        return f"{base}{CALLBACK_PATH}"
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host"))
    return f"{scheme}://{host}{CALLBACK_PATH}"


@router.get(
    "/microsoft/login",
    summary="Initiate Microsoft SSO login",
    description="Redirects the browser to Microsoft Entra ID for authentication",
)
async def microsoft_login(request: Request, return_to: str = Query(None)):
    msal_app = _get_msal_app()
    redirect_uri = _build_redirect_uri(request)

    state = secrets.token_urlsafe(32)
    sig = _sign_state(state)

    import json as _json
    from db.redis import get_redis
    redis = await get_redis()
    state_data = _json.dumps({"sig": sig, "return_to": return_to or ""})
    await redis.set(f"oauth_state:{state}", state_data, ex=300)

    auth_url = msal_app.get_authorization_request_url(
        scopes=MICROSOFT_SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )
    return RedirectResponse(url=auth_url)


@router.get(
    "/microsoft/callback",
    summary="Microsoft SSO callback",
    description="Handles the redirect from Microsoft after authentication",
)
async def microsoft_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(None),
    auth_service: AuthService = Depends(get_auth_service),
):
    # Validate OAuth state via Redis (domain-independent, works through gateways)
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    import json as _json
    from db.redis import get_redis
    redis = await get_redis()
    raw = await redis.get(f"oauth_state:{state}")
    if not raw:
        raise HTTPException(status_code=400, detail="OAuth state expired or invalid")
    await redis.delete(f"oauth_state:{state}")
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        state_data = _json.loads(raw)
        stored_sig = state_data["sig"]
        return_to = state_data.get("return_to", "")
    except (ValueError, KeyError):
        raise HTTPException(status_code=400, detail="OAuth state corrupted")
    if not hmac.compare_digest(_sign_state(state), stored_sig):
        raise HTTPException(status_code=400, detail="OAuth state signature invalid")

    # Resolve post-login redirect: use return_to if it matches an allowed origin
    frontend_url = settings.FRONTEND_URL
    if return_to:
        allowed = {o.strip().rstrip("/") for o in settings.CORS_ALLOWED_ORIGINS.split(",")}
        if return_to.rstrip("/") in allowed:
            frontend_url = return_to.rstrip("/")

    msal_app = _get_msal_app()
    redirect_uri = _build_redirect_uri(request)

    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=MICROSOFT_SCOPES,
        redirect_uri=redirect_uri,
    )

    if "error" in result:
        logger.error("Microsoft token exchange failed: %s", result.get("error_description"))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.get("error_description", "Microsoft authentication failed"),
        )

    ms_access_token = result["access_token"]
    # MSAL only returns a refresh_token if our scope set includes
    # "offline_access" (added implicitly when MSAL sees a confidential
    # client) AND the user actually consented. We tolerate it being
    # missing — group typeahead just falls back to the local cache.
    ms_refresh_token = result.get("refresh_token")

    async with httpx.AsyncClient() as client:
        graph_resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {ms_access_token}"},
        )
        if graph_resp.status_code != 200:
            logger.error("MS Graph /me call failed: %s", graph_resp.text)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch user profile from Microsoft Graph",
            )
        profile = graph_resp.json()

        # Fetch flattened group memberships so RLS can evaluate group shares.
        # These calls degrade to "empty" rather than failing the login, so a
        # missing scope at the tenant level won't lock users out — they just
        # won't see group-shared resources until the admin grants the scope.
        group_ids = await _fetch_user_group_ids(client, ms_access_token)
        groups_with_names = await _fetch_groups_metadata(
            client, ms_access_token, group_ids
        )

    email = profile.get("mail") or profile.get("userPrincipalName")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft account has no email address",
        )

    try:
        user = await auth_service.find_or_create_microsoft_user(
            external_id=profile["id"],
            email=email,
            first_name=profile.get("givenName"),
            last_name=profile.get("surname"),
            groups=groups_with_names,
        )
    except DisabledAccountException:
        params = urlencode({"error": "Account is disabled. Contact your administrator."})
        return RedirectResponse(url=f"{frontend_url}?{params}")

    # Persist the refresh token so we can call Graph "as the user" later
    # (e.g. typeahead group search). RLS on ms_oauth_token is owner-only
    # without an admin override — we set the context to this user's id
    # so the INSERT/UPDATE policy passes. Failures here are logged and
    # ignored; they don't block login (group search will just fall back
    # to the local cache).
    if ms_refresh_token:
        try:
            from db.pgsql import set_user_context
            await set_user_context(auth_service.db, user.id)
            await auth_service.upsert_ms_refresh_token(
                user_id=user.id,
                refresh_token=ms_refresh_token,
                scopes=MICROSOFT_SCOPES,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to persist MS refresh token for user %s: %s",
                user.id, exc,
            )

    from utils.security import generate_oauth_code
    oauth_code = await generate_oauth_code(user.id)

    return RedirectResponse(url=f"{frontend_url}?code={oauth_code}")


@router.post(
    "/exchange-code",
    response_model=TokenResponse,
    summary="Exchange OAuth code for tokens",
    description="Exchange a one-time authorization code from OAuth callback for access token (+ refresh cookie)",
)
async def exchange_oauth_code(
    body: OAuthCodeExchangeRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    from utils.security import exchange_oauth_code as _exchange
    user_id = await _exchange(body.code)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authorization code",
        )

    user = await auth_service.get_user_by_id(user_id)
    access_token, refresh_token = await auth_service.create_tokens(user)

    resp = JSONResponse(
        content=TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ).model_dump(),
    )
    _set_refresh_cookie(resp, refresh_token)
    return resp
