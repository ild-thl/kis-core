"""HTTP side of the direct uploads, one set of routes for every tool.

Each tool registers its rule in services.direct_upload (which files fit, who may send them)
and then accepts an upload token besides the classic file.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.dependencies import get_current_user
from src.dependencies_rbac import get_user_permissions, require_tool_access
from src.i18n import get_locale, t
from src.permissions import Permissions
from src.security.rate_limit import check_upload_limit, record_upload
from src.services import direct_upload as du

router = APIRouter(prefix="/uploads", tags=["uploads"])


def tool_access(tool: str):
    """The same check the tool's own routes run, so the upload grants nothing extra."""
    check = require_tool_access(tool)

    async def authorize(user: dict, perms: Permissions, context: dict, locale: str) -> None:
        await check(user=user, perms=perms, locale=locale)
    return authorize


def permission_access(*keys: str):
    """The same permission check an admin route runs, for uploads that belong to the admin area."""
    from src.dependencies_rbac import require_permission
    check = require_permission(*keys)

    async def authorize(user: dict, perms: Permissions, context: dict, locale: str) -> None:
        await check(user=user, locale=locale)
    return authorize


def rule_for(tool: str, locale: str) -> du.UploadRule:
    rule = du.RULES.get(tool)
    if rule is None:
        raise HTTPException(status_code=403, detail=t("auth.toolForbidden", locale))
    return rule


class StartBody(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=500)
    size: int = Field(ge=0)
    context: dict[str, str] = Field(default_factory=dict)


class PartNumbers(BaseModel):
    parts: list[int] = Field(min_length=1, max_length=du.MAX_URLS_PER_CALL)


@router.post("")
async def start_upload(
    body: StartBody,
    request: Request,
    current_user: dict = Depends(get_current_user),
    perms: Permissions = Depends(get_user_permissions),
    locale: str = Depends(get_locale),
):
    """Opens a direct upload, or answers direct False when there is no bucket."""
    rule = rule_for(body.tool, locale)
    await _maybe_await(rule.authorize(current_user, perms, body.context, locale))
    user_id = current_user["user_id"]
    check_upload_limit(user_id, locale=locale)
    await _maybe_await(rule.precheck(current_user, body.context, body.filename, body.size, locale))
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    answer = du.start(body.tool, rule, body.filename, body.size, user_id, body.context,
                      request.headers.get("origin") or "", host, locale)
    # An opened upload counts like a classic one, so the hourly limit also caps open uploads.
    if answer.get("direct"):
        record_upload(user_id)
    return answer


@router.get("/{token}")
def upload_status(token: str, current_user: dict = Depends(get_current_user), locale: str = Depends(get_locale)):
    """Which parts already arrived, so a broken upload goes on where it stopped."""
    return du.status(token, current_user["user_id"], locale)


@router.post("/{token}/urls")
def upload_urls(token: str, body: PartNumbers, current_user: dict = Depends(get_current_user),
                locale: str = Depends(get_locale)):
    """Signs a small batch of parts."""
    return du.urls(token, body.parts, current_user["user_id"], locale)


@router.post("/{token}/complete")
def complete_upload(token: str, current_user: dict = Depends(get_current_user), locale: str = Depends(get_locale)):
    """Joins the parts and checks the file, the tool then takes it by the token."""
    return du.complete(token, current_user["user_id"], locale)


@router.delete("/{token}")
def abort_upload(token: str, current_user: dict = Depends(get_current_user), locale: str = Depends(get_locale)):
    """Drops an upload and everything already sent."""
    return du.abort(token, current_user["user_id"], locale)


async def _maybe_await(value):
    """Rules may be plain functions or coroutines."""
    if hasattr(value, "__await__"):
        return await value
    return value
