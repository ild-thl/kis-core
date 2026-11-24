"""The tool routes stream the upload to disk instead of buffering it."""
import asyncio
import os

import pytest
from fastapi import HTTPException


class _ChunkOnlyUpload:
    """An upload stand-in that refuses an unbounded read."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0
        self.max_chunk_seen = 0

    async def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            raise AssertionError("unbounded read() would buffer the whole body in RAM")
        self.max_chunk_seen = max(self.max_chunk_seen, n)
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


def test_streams_body_to_disk_without_unbounded_read(tmp_path):
    from src.utils.upload_stream import stream_upload_to_path

    data = b"ID3\x04\x00" + b"a" * 300_000
    dest = str(tmp_path / "input.mp3")
    src = _ChunkOnlyUpload(data)

    total, head = asyncio.run(stream_upload_to_path(src, dest, max_bytes=10 * 1024 * 1024, locale="de"))

    assert total == len(data)
    assert os.path.getsize(dest) == len(data)
    with open(dest, "rb") as f:
        assert f.read() == data
    # Head keeps enough for magic-byte validation, and no more.
    assert head[:5] == b"ID3\x04\x00"
    assert len(head) == 65536


def test_head_is_whole_file_when_smaller_than_window(tmp_path):
    from src.utils.upload_stream import stream_upload_to_path

    data = b"WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n"
    dest = str(tmp_path / "input.vtt")

    total, head = asyncio.run(
        stream_upload_to_path(_ChunkOnlyUpload(data), dest, max_bytes=1024, locale="de")
    )

    assert total == len(data)
    assert head == data


def test_oversize_body_is_rejected_before_it_is_fully_read(tmp_path):
    """413 must fire while streaming, not after the whole body is in memory."""
    from src.utils.upload_stream import stream_upload_to_path

    limit = 1 * 1024 * 1024
    src = _ChunkOnlyUpload(b"x" * (8 * limit))
    dest = str(tmp_path / "big.bin")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_upload_to_path(src, dest, max_bytes=limit, locale="de"))

    assert exc.value.status_code == 413
    # Stopped early: at most one chunk past the limit was consumed.
    assert src._pos <= limit + src.max_chunk_seen


def test_stream_chunk_size_stays_small(tmp_path):
    """A 'chunked' read that asks for 500 MB at once is still a whole-body read."""
    from src.utils.upload_stream import stream_upload_to_path

    src = _ChunkOnlyUpload(b"y" * 200_000)
    dest = str(tmp_path / "chunk.bin")
    asyncio.run(stream_upload_to_path(src, dest, max_bytes=10 * 1024 * 1024, locale="de"))

    assert 0 < src.max_chunk_seen <= 8 * 1024 * 1024


# --- storage: path-based queue file -----------------------------------------

def test_save_queue_file_from_path_stores_content_locally(tmp_path, monkeypatch):
    from src import storage

    monkeypatch.setattr(storage, "USE_S3", False)
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path / "storage")

    src = tmp_path / "upload.mp3"
    src.write_bytes(b"audio-bytes-here")

    stored = storage.save_queue_file_from_path(7, "job-abc", ".mp3", str(src))

    assert stored.endswith("users/7/jobs/job-abc/input.mp3")
    with open(stored, "rb") as f:
        assert f.read() == b"audio-bytes-here"


def test_save_job_file_from_path_stores_under_the_given_name(tmp_path, monkeypatch):
    from src import storage

    monkeypatch.setattr(storage, "USE_S3", False)
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path / "storage")

    src = tmp_path / "corrected.pptx"
    src.write_bytes(b"pptx-payload")

    stored = storage.save_job_file_from_path(4, "job-1", "corrected.pptx", str(src))

    assert stored.endswith("users/4/jobs/job-1/corrected.pptx")
    with open(stored, "rb") as f:
        assert f.read() == b"pptx-payload"


def test_save_queue_file_from_path_hands_s3_a_path_not_bytes(tmp_path, monkeypatch):
    """boto3 has to stream the file itself, not back into memory."""
    from src import storage

    calls: list[tuple] = []

    class _FakeS3:
        def upload_file(self, filename, bucket, key):
            calls.append((filename, bucket, key))

        def put_object(self, **kwargs):
            raise AssertionError("put_object buffers the whole body in RAM")

    monkeypatch.setattr(storage, "USE_S3", True)
    monkeypatch.setattr(storage, "_S3_BUCKET", "askfrancis")
    monkeypatch.setattr(storage, "_s3", lambda: _FakeS3())

    src = tmp_path / "upload.mp4"
    src.write_bytes(b"video")

    key = storage.save_queue_file_from_path(3, "job-xyz", ".mp4", str(src))

    assert key == "users/3/jobs/job-xyz/input.mp4"
    assert calls == [(str(src), "askfrancis", "users/3/jobs/job-xyz/input.mp4")]
