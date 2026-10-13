import shutil

import numpy as np
import pytest
import soundfile as sf

from split import media

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def tone(path, rate=48000, channels=1, seconds=1.5):
    t = np.arange(int(rate * seconds)) / rate
    wave = 0.5 * np.sin(2 * np.pi * 440 * t)
    data = np.stack([wave] * channels, axis=1) if channels > 1 else wave
    sf.write(path, data, rate, subtype="PCM_16")
    return path


def test_decode_reports_source_shape_and_writes_float_stereo(tmp_path):
    source = media.decode(tone(tmp_path / "in.wav"), tmp_path / "mix.wav")
    assert source.sample_rate == 48000
    assert source.channels == 1
    assert source.duration == pytest.approx(1.5, abs=0.01)
    info = sf.info(tmp_path / "mix.wav")
    assert (info.samplerate, info.channels, info.subtype) == (44100, 2, "FLOAT")


def test_decode_rejects_files_without_audio(tmp_path):
    bogus = tmp_path / "notes.wav"
    bogus.write_text("not audio")
    with pytest.raises(media.MediaError, match=r"Could not read notes.wav"):
        media.decode(bogus, tmp_path / "mix.wav")


@pytest.mark.parametrize(("fmt", "subtype"), [("wav", "PCM_24"), ("flac", "PCM_24"), ("mp3", None)])
def test_encode_restores_source_rate_and_channels(tmp_path, fmt, subtype):
    source = media.decode(tone(tmp_path / "in.wav"), tmp_path / "mix.wav")
    out = tmp_path / f"stem.{fmt}"
    media.encode(tmp_path / "mix.wav", out, fmt, source)
    info = sf.info(out)
    assert info.samplerate == 48000
    assert info.channels == 1
    if subtype:
        assert info.subtype == subtype


def test_mix_sums_stems_sample_by_sample(tmp_path):
    a = np.full((100, 2), 0.25, dtype=np.float32)
    b = np.full((80, 2), 0.5, dtype=np.float32)
    sf.write(tmp_path / "a.wav", a, 44100, subtype="FLOAT")
    sf.write(tmp_path / "b.wav", b, 44100, subtype="FLOAT")
    media.mix([tmp_path / "a.wav", tmp_path / "b.wav"], tmp_path / "sum.wav")
    total, _ = sf.read(tmp_path / "sum.wav", dtype="float32")
    assert total.shape == (100, 2)
    assert total[0, 0] == pytest.approx(0.75)
    assert total[-1, 0] == pytest.approx(0.25)


def test_peaks_cover_the_whole_file(tmp_path):
    path = tone(tmp_path / "in.wav", rate=44100, channels=2, seconds=2)
    data = media.peaks(path, buckets=100)
    assert data["duration"] == pytest.approx(2.0)
    assert 99 <= len(data["peak"]) <= 101
    assert max(data["peak"]) == pytest.approx(0.5, abs=0.01)
    assert all(r <= p + 1e-6 for p, r in zip(data["peak"], data["rms"], strict=True))
