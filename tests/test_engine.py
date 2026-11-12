import logging
import shutil

import numpy as np
import pytest
import soundfile as sf

from split import engine
from split.catalog import MODELS, Step

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def fake_runner(monkeypatch):
    """A Runner whose models split their input into equal shares, so every output sums to the input."""
    runner = engine.Runner.__new__(engine.Runner)
    runner.device = {"kind": "cpu", "name": "CPU", "memory": 0, "note": ""}
    runner.separator = None
    runner.notes = []

    def run_model(model, source, out, report):
        out.mkdir(parents=True, exist_ok=True)
        data, rate = sf.read(source, dtype="float32", always_2d=True)
        stems = list(dict.fromkeys(model.stems.values()))
        produced = {}
        for stem in stems:
            produced[stem] = out / f"{stem}.wav"
            sf.write(produced[stem], data / len(stems), rate, subtype="FLOAT")
        report(1.0)
        return produced

    monkeypatch.setattr(runner, "_run_model", run_model)
    monkeypatch.setattr(runner, "_ensure_weights", lambda model, report: None)
    return runner


def song(path, amplitude=0.5, rate=48000, channels=1, seconds=1.0, subtype="PCM_16"):
    t = np.arange(int(rate * seconds)) / rate
    wave = amplitude * np.sin(2 * np.pi * 220 * t) * np.linspace(0.2, 1.0, t.size)
    data = np.stack([wave] * channels, axis=1) if channels > 1 else wave
    sf.write(path, data, rate, subtype=subtype)
    return path


def separate(runner, tmp_path, source, task, tier, stems, **extra):
    job_dir = tmp_path / "job"
    job_dir.mkdir(exist_ok=True)
    events = []
    request = {
        "job_dir": str(job_dir),
        "source": str(source),
        "task": task,
        "tier": tier,
        "stems": stems,
        "format": "wav",
        **extra,
    }
    return job_dir, runner.separate(request, lambda **event: events.append(event)), events


def total(job_dir, names):
    return sum(sf.read(job_dir / name, dtype="float64", always_2d=True)[0] for name in names)


@needs_ffmpeg
def test_stems_sum_to_the_original_at_the_source_shape(monkeypatch, tmp_path):
    runner = fake_runner(monkeypatch)
    source = song(tmp_path / "in.wav")
    stems = ["vocals", "drums", "bass", "other"]
    job_dir, result, _ = separate(runner, tmp_path, source, "band4", "best", stems)

    assert set(result["outputs"]) == set(stems)
    assert not (job_dir / "work").exists()
    for name in result["outputs"].values():
        info = sf.info(job_dir / name)
        assert (info.samplerate, info.channels) == (48000, 1)
        assert (job_dir / "peaks" / f"{name.split('.')[0]}.json").is_file()
    original, _ = sf.read(job_dir / result["original"], dtype="float64", always_2d=True)
    assert np.abs(total(job_dir, result["outputs"].values()) - original).max() < 1e-4


@needs_ffmpeg
def test_chained_steps_fold_into_the_wanted_stems(monkeypatch, tmp_path):
    runner = fake_runner(monkeypatch)
    source = song(tmp_path / "in.wav", channels=2, rate=44100)
    stems = ["kick", "snare", "toms", "hihat", "cymbals"]
    job_dir, result, _ = separate(runner, tmp_path, source, "drums", "best", stems)

    drums, _ = sf.read(source, dtype="float64", always_2d=True)
    # the sw step splits six ways and only its drums share feeds the kit model
    expected = drums / len(dict.fromkeys(MODELS["sw"].stems.values()))
    assert np.abs(total(job_dir, result["outputs"].values()) - expected).max() < 1e-3


@needs_ffmpeg
def test_a_subset_of_stems_is_written_alone(monkeypatch, tmp_path):
    runner = fake_runner(monkeypatch)
    source = song(tmp_path / "in.wav")
    job_dir, result, _ = separate(runner, tmp_path, source, "vocals", "best", ["vocals"])

    assert list(result["outputs"]) == ["vocals"]
    assert not (job_dir / "instrumental.wav").exists()


@needs_ffmpeg
def test_a_loud_original_is_trimmed_with_a_subset_of_stems(monkeypatch, tmp_path):
    runner = fake_runner(monkeypatch)
    source = song(tmp_path / "in.wav", amplitude=1.3, channels=2, subtype="FLOAT")
    job_dir, result, _ = separate(runner, tmp_path, source, "vocals", "best", ["vocals"])

    original, _ = sf.read(job_dir / result["original"], dtype="float64", always_2d=True)
    vocals, _ = sf.read(job_dir / result["outputs"]["vocals"], dtype="float64", always_2d=True)
    assert np.abs(original).max() < 1.0
    assert result["trim_db"] < 0
    # the trim is shared, so the stem still sits at its share of the original
    assert np.abs(vocals * 2 - original).max() < 1e-3


def write_members(tmp_path, waves):
    results = []
    for index, wave in enumerate(waves):
        path = tmp_path / f"member{index}.wav"
        sf.write(path, wave, 44100, subtype="FLOAT")
        results.append({"vocals": path})
    return results


def test_balanced_ensemble_is_the_sample_average(tmp_path):
    rng = np.random.default_rng(1)
    waves = [rng.uniform(-0.5, 0.5, (4410, 2)).astype(np.float32) for _ in range(3)]
    step = Step(("a", "b", "c"), {"vocals": "vocals"}, algorithm="avg_wave")
    merged = engine.Runner._combine(None, step, write_members(tmp_path, waves), tmp_path / "out")

    combined, rate = sf.read(merged["vocals"], dtype="float32", always_2d=True)
    assert rate == 44100
    assert combined.shape == waves[0].shape
    assert np.abs(combined - np.mean(waves, axis=0)).max() < 1e-5


def test_clear_ensemble_keeps_less_energy_than_deep(tmp_path):
    t = np.arange(44100 * 2) / 44100
    rng = np.random.default_rng(2)
    voices = [np.sin(2 * np.pi * f * t) * 0.3 + rng.normal(0, 0.05, t.size) for f in (220, 330, 440)]
    waves = [np.stack([voice] * 2, axis=1).astype(np.float32) for voice in voices]
    energy = {}
    for algorithm in ("uvr_min_spec", "uvr_max_spec"):
        step = Step(("a", "b", "c"), {"vocals": "vocals"}, algorithm=algorithm)
        merged = engine.Runner._combine(None, step, write_members(tmp_path, waves), tmp_path / algorithm)
        combined, _ = sf.read(merged["vocals"], dtype="float64", always_2d=True)
        energy[algorithm] = float(np.sum(combined**2))
    assert energy["uvr_min_spec"] < energy["uvr_max_spec"]


def test_single_member_is_passed_through(tmp_path):
    step = Step(("a",), {"vocals": "vocals"})
    results = write_members(tmp_path, [np.zeros((10, 2), np.float32)])
    assert engine.Runner._combine(None, step, results, tmp_path / "out") is results[0]


def test_loading_trusts_the_fetched_files_and_never_downloads(tmp_path):
    separator_class = engine._separator_class()
    separator = separator_class.__new__(separator_class)
    separator.model_file_dir = str(tmp_path)
    separator.logger = logging.getLogger("test")
    model = MODELS["resurrection-voc"]
    # upstream publishes checksums for these names, so its own loader would delete the stand-ins
    for file in model.files:
        (tmp_path / file.name).write_bytes(b"stand-in")
    found = separator.download_model_files(model.load_name)
    assert found[0] == model.load_name
    assert all((tmp_path / file.name).read_bytes() == b"stand-in" for file in model.files)
    (tmp_path / model.files[0].name).unlink()
    with pytest.raises(FileNotFoundError):
        separator.download_model_files(model.load_name)
