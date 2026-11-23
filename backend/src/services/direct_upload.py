"""Direct uploads: the browser sends a file in parts straight into the bucket.

One core for every tool and the AI assistant. Each request stays small (one part), so a
proxy with a low body limit never sees the whole file. Flow: start, urls per part,
complete (join and check), then a tool route takes the finished file by its token.
"""
import json
import math
import uuid
from dataclasses import dataclass, field
from typing import Callable, Collection
from urllib.parse import urlsplit

from fastapi import HTTPException
from loguru import logger

from src.core.redis_url import REDIS_URL
from src.i18n import t
from src.storage import (
    USE_S3,
    delete_file,
    ensure_upload_cors,
    get_range,
    multipart_abort,
    multipart_complete,
    multipart_part_url,
    multipart_parts,
    multipart_start,
)
from src.utils.file_validation import validate_or_raise

# The smallest part S3 allows, a broken line loses little and progress moves often.
PART_SIZE = 5 * 1024 * 1024
# An open upload can be resumed this long, the bucket drops leftovers after a day too.
SESSION_SECONDS = 24 * 60 * 60
# A signed part stays valid this long, slow lines fetch new ones in small batches.
PART_URL_SECONDS = 60 * 60
MAX_URLS_PER_CALL = 20
# Bytes of the joined file that are checked against the file type.
HEAD_BYTES = 65536
_SESSION_PREFIX = "kis:upload:"


@dataclass(frozen=True)
class UploadRule:
    """What one tool accepts through the direct route and who may use it."""
    extensions: Collection[str]
    max_bytes: Callable[[], int]
    # Raises when this person may not upload for this tool, gets user, permissions, context, locale.
    authorize: Callable = field(default=lambda *a: None)
    # Raises when the file does not fit, gets user, context, filename, size, locale.
    precheck: Callable = field(default=lambda *a: None)
    # Endings whose content the tool checks itself instead of the leading bytes check here.
    self_checked: Collection[str] = ()


# Every tool that takes large files registers its rule here, its own module does that on import.
RULES: dict[str, UploadRule] = {}


def register(tool: str, rule: UploadRule) -> None:
    """Makes a tool known to the direct upload, a second call replaces the rule."""
    RULES[tool] = rule


# --- pure helpers --------------------------------------------------------------

def part_count(size: int) -> int:
    """How many parts a file of this size is cut into, an empty file still has one."""
    return max(1, math.ceil(size / PART_SIZE))


def part_length(number: int, size: int) -> int:
    """Exact bytes of one part, every part is full except the last."""
    count = part_count(size)
    return PART_SIZE if number < count else size - PART_SIZE * (count - 1)


def done_parts(parts: list[dict], size: int) -> list[int]:
    """Numbers of the parts that arrived completely, a cut-off last attempt is sent again."""
    count = part_count(size)
    return sorted(p["PartNumber"] for p in parts
                  if 1 <= p["PartNumber"] <= count and p["Size"] == part_length(p["PartNumber"], size))


def parts_complete(parts: list[dict], size: int) -> bool:
    """True when every part is there once and together they add up to the announced size."""
    numbers = sorted(p["PartNumber"] for p in parts)
    return numbers == list(range(1, part_count(size) + 1)) and sum(p["Size"] for p in parts) == size


def same_site_origin(origin: str, host: str) -> str:
    """The page's own origin, only when the browser's Origin matches the host it called."""
    host = (host or "").split(",")[0].strip()
    parts = urlsplit(origin or "")
    if parts.scheme in ("http", "https") and parts.netloc and parts.netloc == host:
        return f"{parts.scheme}://{parts.netloc}"
    return ""


def staging_key(user_id: int, token: str, ext: str) -> str:
    """Where a direct upload lands, the bucket expires everything under tmp/ after a day."""
    return f"tmp/uploads/{user_id}/{token}{ext}"


def extension_of(filename: str) -> str:
    """The lower-case ending with its dot, empty when there is none."""
    name = filename or ""
    return name[name.rfind("."):].lower() if "." in name else ""


# --- session in Redis ----------------------------------------------------------

def _redis():
    """Redis client with short timeouts, same pattern as the other upload routes."""
    import redis as _redis_lib
    return _redis_lib.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


def _save(token: str, session: dict) -> None:
    _redis().set(_SESSION_PREFIX + token, json.dumps(session), ex=SESSION_SECONDS)


def _drop(token: str) -> None:
    try:
        _redis().delete(_SESSION_PREFIX + token)
    except Exception as e:  # noqa: BLE001 - the entry runs out by itself
        logger.warning("Upload session {} not removed: {}", token, e)


def load(token: str, user_id: int, locale: str) -> dict:
    """An upload belongs to the person who started it, anyone else gets a not found."""
    raw = _redis().get(_SESSION_PREFIX + (token or ""))
    session = json.loads(raw) if raw else None
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail=t("ai.source.uploadExpired", locale))
    return session


# --- the steps -----------------------------------------------------------------

def start(tool: str, rule: UploadRule, filename: str, size: int, user_id: int, context: dict,
          origin: str, host: str, locale: str) -> dict:
    """Opens a direct upload, or answers direct False when the classic route fits better."""
    ext = extension_of(filename)
    if not USE_S3 or ext not in rule.extensions:
        return {"direct": False}
    if size == 0:
        raise HTTPException(status_code=400, detail=t("file.empty", locale))
    max_bytes = rule.max_bytes()
    if size > max_bytes:
        raise HTTPException(status_code=413, detail=t("file.tooLargeMb", locale, max=max_bytes // (1024 * 1024)))

    ensure_upload_cors(same_site_origin(origin, host))

    token = uuid.uuid4().hex
    key = staging_key(user_id, token, ext)
    upload_id = multipart_start(key, "")
    _save(token, {
        "tool": tool, "user_id": user_id, "context": context or {}, "key": key, "upload_id": upload_id,
        "filename": filename, "ext": ext, "size": size, "done": False,
    })
    logger.info("{}: direct upload {} opened for {} ({} bytes)", tool, token, filename, size)
    return {"direct": True, "token": token, "part_size": PART_SIZE, "part_count": part_count(size), "uploaded": []}


def status(token: str, user_id: int, locale: str) -> dict:
    """Which parts already arrived, so a broken upload goes on where it stopped."""
    session = load(token, user_id, locale)
    count = part_count(session["size"])
    if session["done"]:
        return {"direct": True, "token": token, "part_size": PART_SIZE, "part_count": count,
                "uploaded": list(range(1, count + 1)), "done": True}
    parts = multipart_parts(session["key"], session["upload_id"])
    if parts is None:
        _drop(token)
        raise HTTPException(status_code=404, detail=t("ai.source.uploadExpired", locale))
    return {"direct": True, "token": token, "part_size": PART_SIZE, "part_count": count,
            "uploaded": done_parts(parts, session["size"]), "done": False}


def urls(token: str, numbers: list[int], user_id: int, locale: str) -> dict:
    """Signs a small batch of parts, each URL accepts exactly one PUT of that part."""
    session = load(token, user_id, locale)
    count = part_count(session["size"])
    if session["done"] or any(n < 1 or n > count for n in numbers):
        raise HTTPException(status_code=400, detail=t("ai.source.uploadPartInvalid", locale))
    return {"urls": {str(n): multipart_part_url(session["key"], session["upload_id"], n, PART_URL_SECONDS,
                                                part_length(n, session["size"]))
                     for n in numbers}}


def abort(token: str, user_id: int, locale: str) -> dict:
    """Drops an upload, the parts or the finished file alike."""
    session = load(token, user_id, locale)
    if session["done"]:
        delete_file(session["key"])
    else:
        multipart_abort(session["key"], session["upload_id"])
    _drop(token)
    return {"ok": True}


def complete(token: str, user_id: int, locale: str) -> dict:
    """Joins the parts and checks the file, a second call on a finished upload changes nothing."""
    session = load(token, user_id, locale)
    if session["done"]:
        return _public(token, session)
    key, upload_id = session["key"], session["upload_id"]
    parts = multipart_parts(key, upload_id)
    if parts is None:
        _drop(token)
        raise HTTPException(status_code=404, detail=t("ai.source.uploadExpired", locale))
    if not parts_complete(parts, session["size"]):
        raise HTTPException(status_code=409, detail=t("ai.source.uploadIncomplete", locale))
    multipart_complete(key, upload_id, sorted(parts, key=lambda p: p["PartNumber"]))
    rule = RULES.get(session["tool"])
    try:
        if rule is None or session["ext"] not in rule.self_checked:
            validate_or_raise(get_range(key, 0, HEAD_BYTES), session["ext"], locale)
    except HTTPException:
        delete_file(key)
        _drop(token)
        raise
    session["done"] = True
    _save(token, session)
    return _public(token, session)


def _public(token: str, session: dict) -> dict:
    return {"token": token, "filename": session["filename"], "size": session["size"], "done": True}


def take(token: str, tool: str | Collection[str], user_id: int, locale: str) -> dict:
    """A finished upload of this person for this tool, the file sits at session['key']."""
    session = load(token, user_id, locale)
    tools = {tool} if isinstance(tool, str) else set(tool)
    if session["tool"] not in tools or not session["done"]:
        raise HTTPException(status_code=404, detail=t("ai.source.uploadExpired", locale))
    return session


def claim(token: str, tool: str | Collection[str], user_id: int, locale: str) -> dict:
    """Takes a finished upload for good in one step, a second caller with the same token gets a not found."""
    session = take(token, tool, user_id, locale)
    pipe = _redis().pipeline(transaction=True)
    pipe.get(_SESSION_PREFIX + token)
    pipe.delete(_SESSION_PREFIX + token)
    raw, _ = pipe.execute()
    if not raw:
        raise HTTPException(status_code=404, detail=t("ai.source.uploadExpired", locale))
    return session


def unclaim(token: str, session: dict) -> None:
    """Puts a claimed upload back when the tool refused it, so the person can try again."""
    _save(token, session)


def release(token: str, session: dict) -> None:
    """Forgets a used upload and deletes its file, the tool keeps its own copy."""
    delete_file(session["key"])
    _drop(token)


# --- receiving a file in a tool route -----------------------------------------

def _token(upload_token) -> str | None:
    """Only a real text counts as a token, a route called directly passes FastAPI's empty default."""
    return upload_token if isinstance(upload_token, str) and upload_token else None


def input_name(file, upload_token: str | None, tools, user_id: int, locale: str) -> str | None:
    """Name of the incoming file, from the classic upload or from a finished direct upload."""
    upload_token = _token(upload_token)
    if upload_token:
        return take(upload_token, tools, user_id, locale)["filename"]
    return getattr(file, "filename", None) or None


async def stage_input(file, upload_token: str | None, tools, user_id: int, dest_path: str,
                      max_bytes: int, locale: str, keep: bool = False) -> tuple[int, bytes]:
    """Puts the incoming file at dest_path and returns its size and leading bytes.

    A classic upload is streamed, a direct upload is fetched from the bucket and then released,
    so every tool route continues the same way after this call. With keep the upload stays for
    a later request, a measurement before the start uses that.
    """
    import asyncio

    from src.utils.upload_stream import HEAD_BYTES, stream_upload_to_path
    upload_token = _token(upload_token)
    if not upload_token:
        return await stream_upload_to_path(file, dest_path, max_bytes, locale)

    from src.storage import download_to_path
    session = take(upload_token, tools, user_id, locale)
    if session["size"] > max_bytes:
        raise HTTPException(status_code=413, detail=t("file.tooLargeMb", locale, max=max_bytes // (1024 * 1024)))
    if keep:
        await asyncio.to_thread(download_to_path, session["key"], dest_path)
    else:
        # Claimed in one step, two requests with the same token never both get the file.
        session = await asyncio.to_thread(claim, upload_token, tools, user_id, locale)
        try:
            await asyncio.to_thread(download_to_path, session["key"], dest_path)
        except Exception:
            unclaim(upload_token, session)
            raise
        await asyncio.to_thread(delete_file, session["key"])
    with open(dest_path, "rb") as f:
        head = f.read(HEAD_BYTES)
    return session["size"], head


def total_size(tokens, tools, user_id: int, locale: str) -> int:
    """Bytes of several finished uploads together, for limits that apply to all files at once."""
    return sum(take(tok, tools, user_id, locale)["size"] for tok in tokens or [])
