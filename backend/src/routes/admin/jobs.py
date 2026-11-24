"""Admin jobs: global list of all jobs + admin cancel."""

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from src import database as db
from src.i18n import get_locale, t

from src.routes.admin._registries import TOOL_LABELS, tools_matching_query
from src.routes.jobs._cancel import remove_job
from src.routes.jobs._shared import _SCREENCAST_TOOLS

from src.dependencies_rbac import require_permission
from src.permissions_registry import PERM_SET_TOOLS_JOBS

router = APIRouter(tags=["admin: jobs"])

# The job list of the tools.
_require = require_permission(PERM_SET_TOOLS_JOBS)

def _compute_duration(job: dict) -> float | None:
    """Duration in seconds; for screencast tools from render_started_at, otherwise from started_at."""
    if job["status"] != "success" or not job["completed_at"]:
        return None
    if job["tool"] in _SCREENCAST_TOOLS and job["render_started_at"]:
        return (job["completed_at"] - job["render_started_at"]).total_seconds()
    if job["started_at"]:
        return (job["completed_at"] - job["started_at"]).total_seconds()
    return None


@router.get("/jobs")
def list_all_jobs(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    _admin=Depends(_require),
):
    q = q.strip()
    extra_tools = tools_matching_query(q) if q else None
    jobs, total = db.get_all_jobs(
        limit=limit, offset=offset, q=q,
        date_from=date_from.strip(), date_to=date_to.strip(),
        extra_tools=extra_tools,
    )
    result = [
        {
            "job_uuid": j["job_uuid"],
            "tool": j["tool"],
            "tool_label": TOOL_LABELS.get(j["tool"], j["tool"]),
            "original_filename": j["original_filename"],
            "status": j["status"],
            "error": j["error_message"],
            "created_at": j["created_at"],
            "completed_at": j["completed_at"],
            "duration_seconds": _compute_duration(j),
            "user_display_name": j.get("user_display_name") or j.get("username") or "Unbekannt",
        }
        for j in jobs
    ]
    return {"jobs": result, "total": total, "limit": limit, "offset": offset}


@router.delete("/jobs/{job_uuid}")
def admin_cancel_job(
    job_uuid: str,
    _admin=Depends(_require),
    locale: str = Depends(get_locale),
):
    """Admin: cancel and delete any job regardless of owner."""
    job = db.get_job(job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail=t("job.notFound", locale))

    # The same way out as the owner's own delete, so no worker and no queue is left behind.
    remove_job(job)
    logger.info("Admin cancelled job: {}", job_uuid)
    return {"ok": True}
