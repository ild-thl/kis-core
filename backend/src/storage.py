import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from loguru import logger

from src.database import get_connection, update_job_result, delete_job
from src.limits import DB_BACKUP_KEEP_DAYS, DB_BACKUP_KEEP_MONTHS, DB_BACKUP_KEEP_WEEKS

# --- Local storage paths ---
STORAGE_ROOT = Path("/app/storage")

# --- S3 config (read once at import time) ---
_S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
_S3_BUCKET = os.environ.get("S3_BUCKET", "askfrancis")
USE_S3 = bool(_S3_ENDPOINT)


# --- Object-key prefix helpers (pure, no DB) ---

def job_prefix(user_id: int, job_uuid: str) -> str:
    """S3 prefix for a job: 'users/{user_id}/jobs/{job_uuid}'. No trailing slash."""
    return f"users/{user_id}/jobs/{job_uuid}"


def aia_workspace_prefix(user_id: int, workspace_uuid: str) -> str:
    """S3 prefix for an AIA workspace: 'users/{user_id}/aia/workspaces/{workspace_uuid}'. No trailing slash."""
    return f"users/{user_id}/aia/workspaces/{workspace_uuid}"


def aia_source_key(user_id: int, workspace_uuid: str, source_uuid: str, ext: str) -> str:
    """S3 key for an AIA source file. ext must include the leading dot (or be empty)."""
    return f"{aia_workspace_prefix(user_id, workspace_uuid)}/sources/{source_uuid}{ext}"


# Derived files sit next to their source, the naming rule lives here.


def aia_source_base(file_path: str) -> str:
    """The source key without its extension: the stem every artifact hangs off."""
    return os.path.splitext(file_path)[0]


def aia_transcript_key(file_path: str) -> str:
    """Full transcript with timestamps, produced by Whisper."""
    return f"{aia_source_base(file_path)}_transcript.txt"


def aia_text_key(file_path: str) -> str:
    """The pasted text behind a text source, kept for editing."""
    return f"{aia_source_base(file_path)}_text.txt"


def aia_vtt_key(file_path: str, lang: str) -> str:
    """Subtitles for one language."""
    return f"{aia_source_base(file_path)}_transcript.{lang}.vtt"


def aia_vtt_error_key(file_path: str, lang: str) -> str:
    """Note of a failed translation, the panel polls for it."""
    return f"{aia_source_base(file_path)}_transcript.{lang}.error"


def aia_transcript_prefix(file_path: str) -> str:
    """Prefix covering every transcript artifact of one source."""
    return f"{aia_source_base(file_path)}_transcript."


def aia_provided_vtt_key(file_path: str) -> str:
    """The transcript a person pasted for a link-only source, read once by the ingest."""
    return f"{aia_source_base(file_path)}_provided.vtt"


AIA_SPEECH_PREFIX = "aia/speech"


def aia_speech_key(fingerprint: str) -> str:
    """Key of a spoken example sentence, deliberately not under users/."""
    return f"{AIA_SPEECH_PREFIX}/{fingerprint[:2]}/{fingerprint}.mp3"


def delete_prefix(prefix: str) -> int:
    """Deletes every object with this prefix and returns the count."""
    if USE_S3:
        deleted = 0
        paginator = _s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
            contents = page.get("Contents", [])
            if not contents:
                continue
            # delete_objects accepts up to 1000 keys per call; pages are already <=1000
            _s3().delete_objects(
                Bucket=_S3_BUCKET,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in contents], "Quiet": True},
            )
            deleted += len(contents)
        return deleted

    def _remove(path: Path) -> int:
        if path.is_dir():
            count = sum(1 for p in path.rglob("*") if p.is_file())
            shutil.rmtree(path, ignore_errors=True)
            return count
        if path.is_file():
            path.unlink(missing_ok=True)
            return 1
        return 0

    return sum(_remove(match) for match in _local_matches(prefix))


def _local_matches(prefix: str) -> list[Path]:
    """Local paths under a prefix: the folder itself, else every sibling whose name starts with it."""
    target = STORAGE_ROOT / prefix
    if target.is_dir():
        return [target]
    # A trailing slash names one folder, a missing one must never match its longer-named siblings.
    if prefix.endswith("/"):
        return []
    return list(target.parent.glob(target.name + "*"))


def _local_path(key: str) -> Path:
    """Map an S3 key to a local filesystem path under STORAGE_ROOT."""
    return STORAGE_ROOT / key


# The switch between S3 and disk sits in exactly one place.


def _store_bytes(key: str, data: bytes) -> str:
    """Write ``data`` at ``key``. Returns the key (S3) or the path (local)."""
    if USE_S3:
        _s3().put_object(Bucket=_S3_BUCKET, Key=key, Body=data)
        return key
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def _store_from_path(key: str, local_path: str) -> str:
    """Stores a local file by streaming and returns a key or a path."""
    if USE_S3:
        _s3().upload_file(local_path, _S3_BUCKET, key)
        return key
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(local_path, path)
    return str(path)


# Parts of an abandoned direct upload are dropped by the bucket itself after a day.
_ABORT_STALE_MULTIPART_RULE = {
    "ID": "multipart-abort-1d",
    "Filter": {"Prefix": ""},
    "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
    "Status": "Enabled",
}


def init_lifecycle_policy() -> None:
    """Sets the bucket's retention rules, both in one call."""
    if not USE_S3:
        return
    from botocore.exceptions import ClientError
    rules = [
        {
            "ID": "tmp-expire-1d",
            "Filter": {"Prefix": "tmp/"},
            "Expiration": {"Days": 1},
            "Status": "Enabled",
        },
        # Separate rules per subfolder, otherwise the tiering breaks.
        {
            "ID": "backups-daily-expire",
            "Filter": {"Prefix": "backups/daily/"},
            "Expiration": {"Days": DB_BACKUP_KEEP_DAYS},
            "Status": "Enabled",
        },
        {
            "ID": "backups-weekly-expire",
            "Filter": {"Prefix": "backups/weekly/"},
            "Expiration": {"Days": DB_BACKUP_KEEP_WEEKS * 7 + 3},
            "Status": "Enabled",
        },
        {
            "ID": "backups-monthly-expire",
            "Filter": {"Prefix": "backups/monthly/"},
            "Expiration": {"Days": DB_BACKUP_KEEP_MONTHS * 31},
            "Status": "Enabled",
        },
    ]
    try:
        _s3().put_bucket_lifecycle_configuration(
            Bucket=_S3_BUCKET,
            LifecycleConfiguration={"Rules": rules + [_ABORT_STALE_MULTIPART_RULE]},
        )
        return
    except ClientError as e:
        logger.warning("Bucket rejects the multipart cleanup rule, setting the others alone: {}", e)
    try:
        _s3().put_bucket_lifecycle_configuration(
            Bucket=_S3_BUCKET, LifecycleConfiguration={"Rules": rules},
        )
    except ClientError as e:
        logger.warning(
            "Could not set bucket lifecycle policy (continuing without): {}", e
        )


@lru_cache(maxsize=1)
def _s3():
    import boto3
    from botocore.client import Config
    return boto3.client(
        "s3",
        endpoint_url=_S3_ENDPOINT,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
        config=Config(signature_version="s3v4"),
    )


def init_storage() -> None:
    """Ensure storage is ready. For S3: create bucket + lifecycle. For local: create dirs."""
    if USE_S3:
        from botocore.exceptions import ClientError
        try:
            _s3().head_bucket(Bucket=_S3_BUCKET)
        except ClientError:
            try:
                _s3().create_bucket(Bucket=_S3_BUCKET)
            except ClientError as err:
                # Several processes start at once on a fresh install, only one wins the create.
                if err.response.get("Error", {}).get("Code") not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise
        init_lifecycle_policy()
    else:
        STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


# --- Direct browser uploads (S3 multipart, every part signed on its own) ---

# The host the browser reaches, inside Docker the bucket may answer under another name.
_S3_PUBLIC_ENDPOINT = os.environ.get("S3_PUBLIC_ENDPOINT", "") or _S3_ENDPOINT

# Origins the bucket already accepts browser uploads from, checked once per process.
_UPLOAD_CORS_READY: set[str] = set()


@lru_cache(maxsize=1)
def _s3_public():
    """Client that only signs URLs, for the host the browser talks to."""
    import boto3
    from botocore.client import Config
    return boto3.client(
        "s3",
        endpoint_url=_S3_PUBLIC_ENDPOINT,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
        # Path style, MinIO answers only to that.
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_upload_cors(origin: str) -> None:
    """Lets the bucket take PUTs from this origin, keeping every rule already there."""
    if not USE_S3 or not origin or origin in _UPLOAD_CORS_READY:
        return
    from botocore.exceptions import ClientError
    try:
        try:
            rules = _s3().get_bucket_cors(Bucket=_S3_BUCKET).get("CORSRules", [])
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "NoSuchCORSConfiguration":
                raise
            rules = []
        if not any(origin in r.get("AllowedOrigins", []) and "PUT" in r.get("AllowedMethods", []) for r in rules):
            rules.append({
                "AllowedOrigins": [origin],
                "AllowedMethods": ["PUT"],
                "AllowedHeaders": ["*"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3600,
            })
            _s3().put_bucket_cors(Bucket=_S3_BUCKET, CORSConfiguration={"CORSRules": rules})
            logger.info("Bucket accepts browser uploads from {} now", origin)
        _UPLOAD_CORS_READY.add(origin)
    except ClientError as e:
        # MinIO has no CORS API and allows every origin anyway.
        logger.warning("Bucket CORS for {} not set: {}", origin, e)
        _UPLOAD_CORS_READY.add(origin)


def multipart_start(key: str, content_type: str) -> str:
    """Opens a multipart upload and returns its id."""
    return _s3().create_multipart_upload(
        Bucket=_S3_BUCKET, Key=key, ContentType=content_type or "application/octet-stream",
    )["UploadId"]


def multipart_part_url(key: str, upload_id: str, part_number: int, expires_seconds: int,
                       content_length: int | None = None) -> str:
    """Signs one part for a PUT straight from the browser, with a length the bucket accepts only exactly."""
    params = {"Bucket": _S3_BUCKET, "Key": key, "UploadId": upload_id, "PartNumber": part_number}
    if content_length is not None:
        params["ContentLength"] = content_length
    return _s3_public().generate_presigned_url("upload_part", Params=params, ExpiresIn=expires_seconds)


def multipart_parts(key: str, upload_id: str) -> list[dict] | None:
    """Parts the bucket holds so far, None when the upload no longer exists."""
    from botocore.exceptions import ClientError
    parts: list[dict] = []
    marker = 0
    try:
        while True:
            resp = _s3().list_parts(
                Bucket=_S3_BUCKET, Key=key, UploadId=upload_id, PartNumberMarker=marker,
            )
            parts += [
                {"PartNumber": p["PartNumber"], "ETag": p["ETag"], "Size": p["Size"]}
                for p in resp.get("Parts", [])
            ]
            if not resp.get("IsTruncated"):
                return parts
            marker = resp["NextPartNumberMarker"]
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchUpload", "404"):
            return None
        raise


def multipart_complete(key: str, upload_id: str, parts: list[dict]) -> None:
    """Joins the parts into the final object."""
    _s3().complete_multipart_upload(
        Bucket=_S3_BUCKET, Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in parts]},
    )


def multipart_abort(key: str, upload_id: str) -> None:
    """Drops an open upload with all its parts, an unknown one is no error."""
    from botocore.exceptions import ClientError
    try:
        _s3().abort_multipart_upload(Bucket=_S3_BUCKET, Key=key, UploadId=upload_id)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") not in ("NoSuchUpload", "404"):
            raise


# --- Generic file operations ---

def get_file(file_path: str) -> bytes:
    if USE_S3:
        resp = _s3().get_object(Bucket=_S3_BUCKET, Key=file_path)
        return resp["Body"].read()
    return Path(file_path).read_bytes()


def get_range(file_path: str, start: int, length: int) -> bytes:
    """Reads a slice of an object without fetching all of it."""
    if USE_S3:
        from botocore.exceptions import ClientError
        end = start + length - 1
        try:
            resp = _s3().get_object(
                Bucket=_S3_BUCKET, Key=file_path, Range=f"bytes={start}-{end}"
            )
            return resp["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("InvalidRange", "416"):
                return b""
            raise
    with open(Path(file_path), "rb") as f:
        f.seek(start)
        return f.read(length)


def copy_key(src_path: str, dst_path: str) -> None:
    """Copies an object, on S3 server side instead of through this process."""
    if USE_S3:
        _s3().copy_object(
            Bucket=_S3_BUCKET,
            CopySource={"Bucket": _S3_BUCKET, "Key": src_path},
            Key=dst_path,
        )
    else:
        dst = Path(dst_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(src_path), dst)


def put_bytes(file_path: str, data: bytes) -> None:
    """Overwrites an object with bytes, for small generated content."""
    if USE_S3:
        _s3().put_object(Bucket=_S3_BUCKET, Key=file_path, Body=data)
        return
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def put_file(file_path: str, local_path: str) -> None:
    """Overwrites an object with a local file, streaming."""
    if USE_S3:
        _s3().upload_file(local_path, _S3_BUCKET, file_path)
    else:
        shutil.copyfile(local_path, Path(file_path))


def stream_s3_object(file_path: str, range_header: str | None = None):
    """Serves an S3 object in pieces, with a range header."""
    kwargs: dict = {"Bucket": _S3_BUCKET, "Key": file_path}
    if range_header:
        kwargs["Range"] = range_header
    resp = _s3().get_object(**kwargs)
    body = resp["Body"]

    def iterator():
        try:
            for chunk in body.iter_chunks(chunk_size=64 * 1024):
                yield chunk
        finally:
            body.close()

    return iterator(), resp["ContentLength"], resp.get("ContentRange")


def file_exists(file_path: str) -> bool:
    """Checks whether a file exists, True when in doubt."""
    if USE_S3:
        from botocore.exceptions import ClientError
        try:
            _s3().head_object(Bucket=_S3_BUCKET, Key=file_path)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                return False
            # Server error, permission error, network issue - assume file exists
            return True
        except Exception:
            # Connection error, timeout, etc. - assume file exists
            return True
    return Path(file_path).exists()


def list_keys(prefix: str) -> list[str]:
    """Lists the keys with this prefix in one go."""
    if USE_S3:
        keys: list[str] = []
        paginator = _s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys
    target = STORAGE_ROOT / prefix
    treffer = target.rglob("*") if target.is_dir() else _local_matches(prefix)
    return [str(f) for f in treffer if f.is_file()]


def job_file_exists(user_id: int, job_uuid: str, filename: str) -> bool:
    """Check whether a specific file inside a job's folder still exists."""
    return key_file_exists(f"{job_prefix(user_id, job_uuid)}/{filename}")


def delete_file(file_path: str) -> None:
    if USE_S3:
        _s3().delete_object(Bucket=_S3_BUCKET, Key=file_path)
        return
    path = Path(file_path)
    if path.exists():
        path.unlink()


# --- Generic operations addressed by key, not by path -----------------------
# Unlike get_file/put_bytes/file_exists/delete_file above (which take the stored path locally,
# an absolute one outside the job/user tree), these take an S3-style key and nest it under
# STORAGE_ROOT locally too, the same convention save_job_file/get_job_file use for job files.


def save_key_file(key: str, data: bytes) -> str:
    """Save bytes at a key and return the stored key or local path."""
    return _store_bytes(key, data)


def get_key_file(key: str) -> bytes:
    """Read bytes at a key, local storage resolves it under STORAGE_ROOT."""
    if USE_S3:
        return get_file(key)
    return _local_path(key).read_bytes()


def key_file_exists(key: str) -> bool:
    """Check whether a key exists, local storage resolves it under STORAGE_ROOT."""
    if USE_S3:
        return file_exists(key)
    return _local_path(key).exists()


def delete_key_file(key: str) -> None:
    """Delete a key if present, local storage resolves it under STORAGE_ROOT."""
    if USE_S3:
        delete_file(key)
    else:
        _local_path(key).unlink(missing_ok=True)


# Storage of the sources of a course room collection.


def save_aia_source_from_path(
    user_id: int, workspace_uuid: str, source_uuid: str, ext: str, local_path: str
) -> str:
    """Store an AIA source, streaming from a file on disk."""
    return _store_from_path(aia_source_key(user_id, workspace_uuid, source_uuid, ext), local_path)


def save_aia_provided_transcript(user_id: int, workspace_uuid: str, source_uuid: str, vtt: str) -> str:
    """Stores the pasted transcript of a YouTube source and returns the file_path of the source itself."""
    key = aia_source_key(user_id, workspace_uuid, source_uuid, ".youtube")
    _store_bytes(aia_provided_vtt_key(key), vtt.encode("utf-8"))
    return key if USE_S3 else str(_local_path(key))


# Attachments of a feedback entry, deliberately not under users/.


def feedback_prefix(feedback_id: int) -> str:
    """S3 prefix for one feedback entry's attachments. No trailing slash."""
    return f"feedback/{feedback_id}"


def feedback_attachment_key(feedback_id: int, attachment_uuid: str, ext: str) -> str:
    """S3 key for one feedback attachment. ext must include the leading dot."""
    return f"{feedback_prefix(feedback_id)}/{attachment_uuid}{ext}"


def save_feedback_attachment_from_path(
    feedback_id: int, attachment_uuid: str, ext: str, local_path: str
) -> str:
    """Store a feedback attachment, streaming from a file on disk."""
    return _store_from_path(feedback_attachment_key(feedback_id, attachment_uuid, ext), local_path)


def delete_feedback_attachments(feedback_id: int) -> int:
    """Delete every attachment of one feedback entry, returns the count."""
    # The slash keeps entry 1 from taking the folders of entries 10, 11 and so on with it.
    return delete_prefix(f"{feedback_prefix(feedback_id)}/")


# Storage of a job folder.

# --- Job file I/O ---

def queue_file_key(user_id: int, job_uuid: str, ext: str) -> str:
    """Key of the input file of a job, a direct upload writes straight to it."""
    return f"{job_prefix(user_id, job_uuid)}/input{ext}"


def save_queue_file(user_id: int, job_uuid: str, ext: str, data: bytes) -> str:
    return _store_bytes(queue_file_key(user_id, job_uuid, ext), data)


def save_queue_file_from_path(user_id: int, job_uuid: str, ext: str, local_path: str) -> str:
    """Same as :func:`save_queue_file`, but takes a path instead of bytes."""
    return _store_from_path(queue_file_key(user_id, job_uuid, ext), local_path)


def save_job_file_from_path(user_id: int, job_uuid: str, filename: str, local_path: str) -> str:
    """Like :func:`save_job_file`, but streams from a local file."""
    return _store_from_path(f"{job_prefix(user_id, job_uuid)}/{filename}", local_path)


def save_job_file(user_id: int, job_uuid: str, filename: str, data: bytes) -> str:
    """Save an arbitrary named file into the job's folder."""
    return _store_bytes(f"{job_prefix(user_id, job_uuid)}/{filename}", data)


def delete_job_file(user_id: int, job_uuid: str, filename: str) -> None:
    """Drop one named file of a job's folder, for working material nobody needs any more."""
    delete_key_file(f"{job_prefix(user_id, job_uuid)}/{filename}")


def is_missing(exc: BaseException) -> bool:
    """Whether a read failed only because the file does not exist, every other failure is a real error."""
    if isinstance(exc, FileNotFoundError):
        return True
    response = getattr(exc, "response", None)
    return isinstance(response, dict) and response.get("Error", {}).get("Code", "") in ("404", "NoSuchKey")


def get_job_file(user_id: int, job_uuid: str, filename: str) -> bytes:
    """Read an arbitrary named file from a job's folder."""
    return get_key_file(f"{job_prefix(user_id, job_uuid)}/{filename}")


def save_result_file(user_id: int, job_uuid: str, ext: str, data: bytes) -> str:
    return _store_bytes(f"{job_prefix(user_id, job_uuid)}/output{ext}", data)


def save_result_json(user_id: int, job_uuid: str, data: dict) -> str:
    key = f"{job_prefix(user_id, job_uuid)}/result.json"
    return _store_bytes(key, json.dumps(data).encode())


def save_result_meta(user_id: int, job_uuid: str, data: dict) -> None:
    """Save a meta.json file for a job (subtitles, audio info, etc.)."""
    key = f"{job_prefix(user_id, job_uuid)}/meta.json"
    _store_bytes(key, json.dumps(data).encode())


def load_result_meta(user_id: int, job_uuid: str) -> dict | None:
    """Load the meta.json for a job. Returns None if not found."""
    key = f"{job_prefix(user_id, job_uuid)}/meta.json"
    if USE_S3:
        from botocore.exceptions import ClientError
        try:
            resp = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
            return json.loads(resp["Body"].read())
        except ClientError:
            return None
    meta_path = _local_path(key)
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def download_to_path(key: str, local_path: str) -> None:
    """Copies an object to a local file, streamed so a large file never sits in memory."""
    if USE_S3:
        _s3().download_file(_S3_BUCKET, key, local_path)
    else:
        shutil.copyfile(_local_path(key), local_path)


@contextmanager
def open_input_file(input_path: str, suffix: str = ""):
    """Returns a local path, on S3 via a temp file."""
    if USE_S3:
        # Streams to disk, a long video must never sit in the worker's memory as a whole.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            tmp_path = f.name
        try:
            _s3().download_file(_S3_BUCKET, input_path, tmp_path)
            yield tmp_path
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    else:
        yield input_path


def load_result_json(result_path: str) -> dict:
    if USE_S3:
        resp = _s3().get_object(Bucket=_S3_BUCKET, Key=result_path)
        return json.loads(resp["Body"].read())
    return json.loads(Path(result_path).read_text(encoding="utf-8"))


# --- Per-slide audio cache ---


def _slide_number(key_or_name: str) -> int:
    """Slide number from the file name, unreadable ones sort to the front."""
    name = key_or_name.rsplit("/", 1)[-1]
    digits = name[len("slide_"):].split(".", 1)[0]
    return int(digits) if digits.isdigit() else -1


def save_audio_cache(user_id: int, job_uuid: str, audio_files: list[bytes | None]) -> None:
    """Stores the MP3s per slide, None leaves a slot untouched."""
    base = f"{job_prefix(user_id, job_uuid)}/audio"
    zu_schreiben = [(i, d) for i, d in enumerate(audio_files) if d is not None]
    if not zu_schreiben:
        return
    if USE_S3:
        from concurrent.futures import ThreadPoolExecutor

        def _put(i_data: tuple[int, bytes]) -> None:
            i, data = i_data
            _s3().put_object(Bucket=_S3_BUCKET, Key=f"{base}/slide_{i:03d}.mp3", Body=data)

        with ThreadPoolExecutor(max_workers=min(len(zu_schreiben), 10)) as pool:
            list(pool.map(_put, zu_schreiben))
        return
    audio_dir = _local_path(base)
    audio_dir.mkdir(parents=True, exist_ok=True)
    for i, data in zu_schreiben:
        (audio_dir / f"slide_{i:03d}.mp3").write_bytes(data)


def get_audio_slide(user_id: int, job_uuid: str, slide_index: int) -> bytes | None:
    key = f"{job_prefix(user_id, job_uuid)}/audio/slide_{slide_index:03d}.mp3"
    if USE_S3:
        from botocore.exceptions import ClientError
        try:
            resp = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
            return resp["Body"].read()
        except ClientError:
            return None
    path = _local_path(key)
    return path.read_bytes() if path.exists() else None


def get_audio_slide_count(user_id: int, job_uuid: str) -> int:
    prefix = f"{job_prefix(user_id, job_uuid)}/audio/"
    if USE_S3:
        # list_keys paginates; a plain KeyCount would cap a long deck at 1000.
        return len(list_keys(prefix))
    audio_dir = _local_path(prefix)
    if not audio_dir.exists():
        return 0
    return len(list(audio_dir.glob("slide_*.mp3")))


def audio_folien_mit_ton(user_id: int, job_uuid: str) -> set[int]:
    """Which slides have audio, in one query instead of one per slide."""
    prefix = f"{job_prefix(user_id, job_uuid)}/audio/"
    dabei: set[int] = set()
    if USE_S3:
        paginator = _s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Size"] > 0:
                    dabei.add(_slide_number(obj["Key"]))
        return dabei - {-1}
    audio_dir = _local_path(prefix)
    if not audio_dir.exists():
        return dabei
    for pfad in audio_dir.glob("slide_*.mp3"):
        if pfad.stat().st_size > 0:
            dabei.add(_slide_number(pfad.name))
    return dabei - {-1}


def get_all_audio_slides(user_id: int, job_uuid: str) -> list[tuple[str, bytes]]:
    """Fetches all slide MP3s in slide order."""
    prefix = f"{job_prefix(user_id, job_uuid)}/audio/"
    if USE_S3:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        keys = [k for k in list_keys(prefix) if k.endswith(".mp3")]
        if not keys:
            return []

        def _fetch(key: str) -> tuple[str, bytes]:
            data = _s3().get_object(Bucket=_S3_BUCKET, Key=key)["Body"].read()
            return (key.split("/")[-1], data)

        # The final sort decides, sorting the keys would be wasted.
        with ThreadPoolExecutor(max_workers=min(len(keys), 10)) as pool:
            results = [f.result() for f in as_completed([pool.submit(_fetch, k) for k in keys])]
        return sorted(results, key=lambda x: _slide_number(x[0]))

    audio_dir = _local_path(prefix)
    if not audio_dir.exists():
        return []
    slides = sorted(audio_dir.glob("slide_*.mp3"), key=lambda p: _slide_number(p.name))
    return [(f.name, f.read_bytes()) for f in slides]


# Spoken example sentences, retention follows the last use.


def save_speech_audio(fingerprint: str, data: bytes) -> None:
    """Store the MP3 for one spoken sentence."""
    _store_bytes(aia_speech_key(fingerprint), data)


def get_speech_audio(fingerprint: str) -> bytes | None:
    """Loads a spoken sentence, None really means missing."""
    key = aia_speech_key(fingerprint)
    if USE_S3:
        from botocore.exceptions import ClientError
        try:
            resp = _s3().get_object(Bucket=_S3_BUCKET, Key=key)
            return resp["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code", "") in ("404", "NoSuchKey"):
                return None
            raise
    path = _local_path(key)
    return path.read_bytes() if path.exists() else None


def delete_speech_audio(fingerprints) -> None:
    """Delete the sounds for the given fingerprints. Used by the nightly cleanup."""
    keys = [aia_speech_key(f) for f in fingerprints]
    if not keys:
        # S3 rejects delete_objects with an empty list, and most nights are empty.
        return
    if USE_S3:
        # delete_objects takes at most 1000 keys per call.
        for i in range(0, len(keys), 1000):
            _s3().delete_objects(
                Bucket=_S3_BUCKET,
                Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True},
            )
        return
    for key in keys:
        _local_path(key).unlink(missing_ok=True)


# --- Folder deletion ---

def delete_job_folder(user_id: int, job_uuid: str) -> int:
    """Delete all files for a job. Returns number of objects deleted."""
    return delete_prefix(job_prefix(user_id, job_uuid))


def clear_render_cache(user_id: int, job_uuid: str) -> int:
    """Delete render-cache (TTS audio + alignments). Called before re-render."""
    return delete_prefix(f"{job_prefix(user_id, job_uuid)}/render_cache/")


def clear_audio_cache(user_id: int, job_uuid: str) -> int:
    """Deletes the finished audio, needed as soon as slides or scripts are replaced."""
    return delete_prefix(f"{job_prefix(user_id, job_uuid)}/audio/")


def delete_aia_source_files(file_path: str) -> int:
    """Deletes a source with everything derived from it."""
    return delete_prefix(aia_source_base(file_path))


def delete_aia_workspace_folder(user_id: int, workspace_uuid: str) -> int:
    """Delete an AIA workspace with all its sources and derived artifacts."""
    return delete_prefix(aia_workspace_prefix(user_id, workspace_uuid))


def delete_user_folder(user_id: int) -> int:
    """All files of a user, the trailing slash is mandatory."""
    return delete_prefix(f"users/{user_id}/")


# --- Result saving with eviction ---

def evict_jobs_over_cap(user_id: int) -> int:
    """Deletes everything above the pool, row and folder."""
    from src.database import get_jobs_for_user_newest_first, select_jobs_to_evict

    entfernt = 0
    for job in select_jobs_to_evict(get_jobs_for_user_newest_first(user_id)):
        geloescht = delete_job(job["job_uuid"])
        if geloescht:
            delete_job_folder(geloescht["user_id"], job["job_uuid"])
            entfernt += 1
    return entfernt


def save_result_and_evict(user_id: int, job_uuid: str, result_path: str, result_filename: str) -> None:
    """Save job result + delete oldest jobs beyond the configured cap."""
    update_job_result(job_uuid, result_path, result_filename)
    evict_jobs_over_cap(user_id)


# --- Cleanup ---

def cleanup_expired_files() -> int:
    """Delete storage folders + DB records for all expired jobs."""
    import psycopg2.extras
    affected = 0
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT job_uuid, user_id FROM jobs WHERE expires_at IS NOT NULL AND expires_at <= NOW()",
            )
            rows = cur.fetchall()
            for row in rows:
                delete_job_folder(row["user_id"], row["job_uuid"])
                cur.execute("DELETE FROM jobs WHERE job_uuid = %s", (row["job_uuid"],))
                affected += 1
        conn.commit()
    return affected
