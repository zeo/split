import hashlib
import io
import json

import pytest

from split import catalog, weights

PAYLOAD = bytes(range(256)) * 40


def pinned(payload=PAYLOAD):
    digest = hashlib.sha256(payload).hexdigest()
    return catalog.WeightFile("tiny.ckpt", "https://example.com/tiny.ckpt", len(payload), digest)


class Response(io.BytesIO):
    def __init__(self, body: bytes, status: int):
        super().__init__(body)
        self.status = status


def serve(monkeypatch, body=PAYLOAD, honour_range=True):
    """Answer urlopen from memory and record the Range header each request carried."""
    ranges = []

    def urlopen(request, timeout=None):
        wanted = request.get_header("Range")
        ranges.append(wanted)
        if wanted and honour_range:
            start = int(wanted.removeprefix("bytes=").rstrip("-"))
            return Response(body[start:], 206)
        return Response(body, 200)

    monkeypatch.setattr(weights.urllib.request, "urlopen", urlopen)
    return ranges


def part_of(file):
    return weights.file_path(file).with_name(file.name + ".part")


def test_download_writes_the_file_and_stamps_the_ledger(monkeypatch):
    file = pinned()
    ranges = serve(monkeypatch)
    seen = []
    weights._download(file, seen.append)

    assert weights.file_path(file).read_bytes() == PAYLOAD
    assert not part_of(file).exists()
    assert ranges == [None]
    assert seen[-1] == len(PAYLOAD)
    ledger = json.loads(weights._ledger_path().read_text())
    assert ledger[file.name][-1] == file.sha256
    assert weights._trusted(file)


def test_download_resumes_from_the_partial_file(monkeypatch):
    file = pinned()
    part_of(file).write_bytes(PAYLOAD[:1000])
    ranges = serve(monkeypatch)
    weights._download(file, lambda n: None)

    assert ranges == ["bytes=1000-"]
    assert weights.file_path(file).read_bytes() == PAYLOAD


def test_download_starts_over_when_the_server_ignores_the_range(monkeypatch):
    file = pinned()
    part_of(file).write_bytes(b"\xff" * 1000)
    serve(monkeypatch, honour_range=False)
    weights._download(file, lambda n: None)

    assert weights.file_path(file).read_bytes() == PAYLOAD


def test_download_drops_bytes_that_fail_the_hash(monkeypatch):
    file = pinned()
    serve(monkeypatch, body=bytes(len(PAYLOAD)))
    with pytest.raises(OSError, match="integrity"):
        weights._download(file, lambda n: None)

    assert not part_of(file).exists()
    assert not weights.file_path(file).exists()


def test_download_stops_when_the_server_sends_too_much(monkeypatch):
    file = pinned()
    serve(monkeypatch, body=PAYLOAD + b"extra")
    with pytest.raises(OSError, match="larger than expected"):
        weights._download(file, lambda n: None)
    assert not weights.file_path(file).exists()


def test_free_space_counts_what_is_already_downloaded(monkeypatch):
    file = pinned()
    model = catalog.Model("tiny", "Tiny", "me", "roformer", (file,), {"vocals": "vocals"}, "MIT", "https://x")
    part_of(file).write_bytes(PAYLOAD[:1000])
    asked = []
    monkeypatch.setattr(weights.paths, "require_space", lambda folder, needed, what: asked.append(needed))
    serve(monkeypatch)
    weights.fetch(model)

    assert asked == [len(PAYLOAD) - 1000 + weights.SPARE]
    assert weights.missing_files(model) == []


def test_removing_a_stopped_download_drops_its_partial_bytes(monkeypatch):
    file = pinned()
    model = catalog.Model("tiny", "Tiny", "me", "roformer", (file,), {"vocals": "vocals"}, "MIT", "https://x")
    monkeypatch.setattr(weights, "MODELS", {"tiny": model})
    part_of(file).write_bytes(PAYLOAD[:1000])
    assert weights.status()["tiny"]["stored"] == 1000
    weights.remove(model)
    assert not part_of(file).exists()
    assert weights.status()["tiny"]["stored"] == 0
