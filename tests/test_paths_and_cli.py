import hashlib

import pytest

from split import catalog, cli, paths, weights


def test_data_root_follows_split_home(isolated_home):
    assert paths.data_root() == isolated_home
    assert paths.models_dir() == isolated_home / "models"
    assert paths.models_dir().is_dir()


def test_web_dir_has_the_ui():
    assert (paths.web_dir() / "index.html").is_file()


def test_legacy_models_move_and_old_cache_goes(tmp_path, monkeypatch):
    legacy = tmp_path / "models_cache"
    legacy.mkdir()
    (legacy / "BS-Roformer-SW.yaml").write_text("kept")
    (legacy / "old_model.ckpt").write_text("dropped")
    monkeypatch.setattr(paths, "legacy_model_dirs", lambda: [legacy])
    assert paths.migrate_legacy_models(catalog.file_names()) == 1
    assert (paths.models_dir() / "BS-Roformer-SW.yaml").read_text() == "kept"
    assert not (paths.models_dir() / "old_model.ckpt").exists()
    assert not legacy.exists()


def test_weights_trust_only_matching_bytes(monkeypatch):
    payload = b"weights"
    pinned = catalog.WeightFile(
        "tiny.ckpt", "https://example.com/tiny.ckpt", len(payload), hashlib.sha256(payload).hexdigest()
    )
    model = catalog.Model(
        "tiny", "Tiny", "me", "roformer", (pinned,), {"vocals": "vocals"}, "MIT", "https://x"
    )
    assert weights.missing_files(model) == [pinned]
    weights.file_path(pinned).write_bytes(payload)
    assert weights.missing_files(model) == []
    weights.file_path(pinned).write_bytes(b"wrongs!")
    assert weights.missing_files(model) == [pinned]


def test_cli_lists_models(capsys):
    assert cli.main(["models"]) == 0
    out = capsys.readouterr().out
    assert "band6" in out and "BS-RoFormer SW" in out


def test_cli_rejects_unknown_stems(tmp_path, capsys):
    song = tmp_path / "a.wav"
    song.write_bytes(b"x")
    assert cli.main(["separate", str(song), "--task", "vocals", "--stems", "drums"]) == 2
    assert "Vocals stems are" in capsys.readouterr().err


def test_cli_rejects_missing_inputs(tmp_path, capsys):
    assert cli.main(["separate", str(tmp_path / "gone.wav")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_cli_rejects_unknown_tier(tmp_path):
    song = tmp_path / "a.wav"
    song.write_bytes(b"x")
    assert cli.main(["separate", str(song), "--task", "band6", "--tier", "fast"]) == 2


def test_cli_parser_knows_every_task():
    parser = cli.build_parser()
    for task in catalog.TASKS:
        assert parser.parse_args(["separate", "x.wav", "-t", task]).task == task
    with pytest.raises(SystemExit):
        parser.parse_args(["separate", "x.wav", "-t", "orchestra"])
