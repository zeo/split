import errno
import types
import urllib.error

import pytest

from split import catalog, engine, media, paths, weights


def test_downloads_retry_transient_failures(monkeypatch):
    attempts = []

    def flaky(file, progress):
        attempts.append(file.name)
        if len(attempts) < 3:
            raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(weights, "_download", flaky)
    monkeypatch.setattr(weights.time, "sleep", lambda seconds: None)
    weights._download_with_retries(catalog.MODELS["deux"].files[0], lambda n: None)
    assert len(attempts) == 3


def test_downloads_give_up_on_a_missing_file(monkeypatch):
    attempts = []

    def gone(file, progress):
        attempts.append(1)
        raise urllib.error.HTTPError(file.url, 404, "Not Found", {}, None)

    monkeypatch.setattr(weights, "_download", gone)
    with pytest.raises(urllib.error.HTTPError):
        weights._download_with_retries(catalog.MODELS["deux"].files[0], lambda n: None)
    assert attempts == [1]


def test_downloads_check_free_space_first(monkeypatch):
    monkeypatch.setattr(paths.shutil, "disk_usage", lambda folder: types.SimpleNamespace(free=10_000_000))
    with pytest.raises(paths.NoSpace, match="Downloading BS-RoFormer SW needs about"):
        weights.fetch(catalog.MODELS["sw"])
    assert engine.classify_error(paths.NoSpace("x"))[0] == "disk"


def test_job_disk_estimate_grows_with_models_and_length():
    vocals = catalog.plan("vocals", "best", False)
    ultra = catalog.plan("vocals", "ultra", False)
    stems = ["vocals", "instrumental"]
    short = engine.work_bytes(vocals, stems, 60, 44100, 2)
    assert engine.work_bytes(vocals, stems, 240, 44100, 2) > 3 * (short - engine.SPARE)
    assert engine.work_bytes(ultra, stems, 60, 44100, 2) > short


def test_errors_are_classified_for_people():
    assert engine.classify_error(OSError(errno.ENOSPC, "No space left on device"))[0] == "disk"
    assert engine.classify_error(SystemExit(1))[0] == "model"
    assert engine.classify_error(RuntimeError("CUDA out of memory. Tried to allocate"))[0] == "oom"
    assert engine.classify_error(media.MediaError("bad file")) == ("input", "bad file")


def test_out_of_memory_halves_the_chunk_until_the_floor():
    instance = types.SimpleNamespace(
        model_data_cfgdict=types.SimpleNamespace(inference=types.SimpleNamespace(dim_t=256)),
        override_model_segment_size=False,
        segment_size=256,
    )
    sizes = []
    while engine._shrink(instance):
        sizes.append(instance.segment_size)
    assert sizes == [128, 64]
    assert instance.override_model_segment_size is True
    assert engine._shrink(types.SimpleNamespace()) is False


def test_collect_caps_huge_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MAX_FILES", 2)
    for name in ("a.wav", "b.wav", "c.wav"):
        (tmp_path / name).write_bytes(b"x")
    with pytest.raises(media.MediaError, match="more than 2 files"):
        media.collect([tmp_path])
    with pytest.raises(media.MediaError, match="does not exist"):
        media.collect([tmp_path / "nope.wav"])
