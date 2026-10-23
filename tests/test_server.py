import io
import zipfile
from pathlib import Path
from urllib.parse import unquote

import pytest
from conftest import wait_for
from fastapi.testclient import TestClient

from split.server import create_app, safe_name

TOKEN = "test-token"


@pytest.fixture
def client(make_jobs):
    jobs = make_jobs()
    with TestClient(create_app(jobs=jobs, token=TOKEN), base_url="http://127.0.0.1") as test_client:
        test_client.jobs = jobs
        yield test_client


def authed(client, method, url, **kwargs):
    return client.request(method, url, headers={"x-split-token": TOKEN}, **kwargs)


def test_index_carries_the_session_token(client):
    page = client.get("/")
    assert page.status_code == 200
    assert f'<meta name="split-token" content="{TOKEN}">' in page.text


def test_foreign_host_is_refused(client):
    assert client.get("/api/catalog", headers={"host": "evil.example"}).status_code == 400


def test_mutations_need_the_token(client, tmp_path):
    song = tmp_path / "song.wav"
    song.write_bytes(b"x")
    body = {"paths": [str(song)], "task": "vocals"}
    assert client.post("/api/jobs", json=body).status_code == 403
    assert client.post("/api/jobs", json=body, headers={"x-split-token": "nope"}).status_code == 403
    assert client.delete("/api/models/deux").status_code == 403


def test_catalog_lists_tasks_models_and_download_state(client):
    data = client.get("/api/catalog").json()
    assert {t["id"] for t in data["tasks"]} >= {"vocals", "band6", "drums", "dereverb"}
    assert data["models"]["sw"]["present"] is False
    assert data["models"]["sw"]["missing"] == data["models"]["sw"]["size"]
    assert data["formats"] == ["wav", "flac", "mp3"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"task": "nope"}, "Unknown task"),
        ({"task": "vocals", "tier": "legendary"}, "no 'legendary' tier"),
        ({"task": "vocals", "stems": ["drums"]}, "Pick stems"),
        ({"task": "vocals", "format": "ogg"}, "Format must be"),
        ({"task": "vocals", "mode": "loud"}, "Mode must be"),
        ({"task": "vocals", "lead_back": True, "stems": ["vocals"]}, "Pick stems"),
        ({"task": "vocals", "paths": []}, "Add at least one file"),
        ({"task": "vocals", "paths": ["Z:/definitely/missing.wav"]}, "does not exist"),
    ],
)
def test_job_validation(client, body, message):
    response = authed(client, "POST", "/api/jobs", json=body)
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_path_job_round_trip(client, tmp_path):
    song = tmp_path / "My   Song.flac"
    song.write_bytes(b"x")
    created = authed(
        client,
        "POST",
        "/api/jobs",
        json={
            "paths": [str(song)],
            "task": "band4",
            "stems": ["drums", "vocals"],
            "format": "flac",
        },
    ).json()["jobs"]
    job = wait_for(client.jobs, created[0]["id"])
    assert job["name"] == "My Song"
    assert list(job["outputs"]) == ["vocals", "drums"]

    stem = client.get(f"/api/jobs/{job['id']}/stems/drums?download=true")
    assert stem.status_code == 200
    assert stem.headers["content-type"] == "audio/flac"
    assert "My Song - drums.flac" in unquote(stem.headers["content-disposition"])
    assert client.get(f"/api/jobs/{job['id']}/stems/bass").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/peaks/vocals").json()["peak"] == [0.5]

    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/jobs/{job['id']}/zip").content))
    assert sorted(archive.namelist()) == ["My Song - drums.flac", "My Song - vocals.flac"]

    export = tmp_path / "export"
    export.mkdir()
    files = authed(client, "POST", f"/api/jobs/{job['id']}/export", json={"folder": str(export)}).json()[
        "files"
    ]
    assert sorted(p.name for p in export.iterdir()) == ["My Song - drums.flac", "My Song - vocals.flac"]
    assert len(files) == 2

    assert authed(client, "DELETE", f"/api/jobs/{job['id']}").json() == {"deleted": job["id"]}
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_upload_job(client):
    response = authed(
        client,
        "POST",
        "/api/jobs",
        data={"task": "vocals", "tier": "fast", "format": "mp3"},
        files=[("files", ("take one.wav", b"RIFF", "audio/wav"))],
    )
    job = response.json()["jobs"][0]
    assert job["owns_source"] is True
    assert job["name"] == "take one"
    done = wait_for(client.jobs, job["id"])
    assert done["status"] == "done"


def test_isolate_adds_instrumental_only_for_cleanup_tasks(client, tmp_path):
    song = tmp_path / "a.wav"
    song.write_bytes(b"x")
    cleanup = authed(
        client, "POST", "/api/jobs", json={"paths": [str(song)], "task": "dereverb", "isolate": True}
    ).json()
    assert cleanup["jobs"][0]["stems"] == ["dry", "reverb", "instrumental"]
    band = authed(
        client, "POST", "/api/jobs", json={"paths": [str(song)], "task": "band4", "isolate": True}
    ).json()
    assert band["jobs"][0]["isolate"] is False


def test_lead_back_only_splits_the_vocals_task(client, tmp_path):
    song = tmp_path / "a.wav"
    song.write_bytes(b"x")
    vocals = authed(
        client,
        "POST",
        "/api/jobs",
        json={"paths": [str(song)], "task": "vocals", "lead_back": True, "mode": "clear"},
    ).json()["jobs"][0]
    assert vocals["stems"] == ["lead", "back", "instrumental"]
    assert vocals["lead_back"] is True and vocals["mode"] == "clear"
    karaoke = authed(
        client, "POST", "/api/jobs", json={"paths": [str(song)], "task": "karaoke", "lead_back": True}
    ).json()["jobs"][0]
    assert karaoke["lead_back"] is False and karaoke["stems"] == ["lead", "backing"]


def test_focus_offers_files_to_the_page(client, tmp_path):
    song = tmp_path / "a.wav"
    song.write_bytes(b"x")
    before = client.get("/api/state").json()["opened"]["seq"]
    authed(client, "POST", "/api/focus", json={"paths": [str(song), "Z:/missing.wav"]})
    opened = client.get("/api/state").json()["opened"]
    assert opened["seq"] == before + 1
    assert opened["paths"] == [str(song)]


def test_model_download_is_queued(client):
    assert authed(client, "POST", "/api/models/deux/download").json() == {"queued": "deux"}
    assert authed(client, "POST", "/api/models/unknown/download").status_code == 404


def test_safe_name_strips_path_characters():
    assert safe_name('a/b\\c:d*e?"f<g>h|') == "a b c d e f g h"
    assert safe_name("   ") == "audio"
    assert len(safe_name("x" * 400)) == 120


def test_web_assets_are_clean_utf8():
    from split import paths

    for asset in paths.web_dir().glob("*.*"):
        if asset.suffix in {".js", ".css", ".html"}:
            text = asset.read_bytes().decode("utf-8")
            # utf-8 bytes of a middle dot or curly quote decoded as cp1252
            broken = (chr(0xC2) + chr(0xB7), chr(0xE2) + chr(0x20AC))
            assert not any(b in text for b in broken), f"mojibake in {asset.name}"


def test_ui_assets_are_revalidated(client):
    assert client.get("/app.js").headers["cache-control"] == "no-cache"


def song_in(folder, name):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_folders_expand_to_the_audio_inside(client, tmp_path):
    album = tmp_path / "album"
    song_in(album, "02 b.flac")
    song_in(album, "01 a.mp3")
    song_in(album / "bonus", "03 c.wav")
    song_in(album, "cover.jpg")
    found = authed(client, "POST", "/api/scan", json={"paths": [str(album)]}).json()["paths"]
    assert [Path(p).relative_to(album).as_posix() for p in found] == [
        "01 a.mp3",
        "02 b.flac",
        "bonus/03 c.wav",
    ]
    created = authed(client, "POST", "/api/jobs", json={"paths": [str(album)], "task": "vocals"}).json()
    assert [j["name"] for j in created["jobs"]] == ["01 a", "02 b", "03 c"]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert (
        authed(client, "POST", "/api/jobs", json={"paths": [str(empty)], "task": "vocals"}).status_code == 400
    )


def test_dropped_folders_reach_the_page_as_files(client, tmp_path):
    album = tmp_path / "album"
    song = song_in(album, "a.wav")
    authed(client, "POST", "/api/focus", json={"paths": [str(album)]})
    assert client.get("/api/state").json()["opened"]["paths"] == [str(song)]


def test_a_stem_can_feed_a_new_job(client, tmp_path):
    song = song_in(tmp_path, "Song.wav")
    first = authed(client, "POST", "/api/jobs", json={"paths": [str(song)], "task": "vocals"}).json()
    parent = wait_for(client.jobs, first["jobs"][0]["id"])
    body = {"task": "dereverb", "stems_of": [{"job": parent["id"], "stem": "vocals"}]}
    child = authed(client, "POST", "/api/jobs", json=body).json()["jobs"][0]
    assert child["name"] == "Song (vocals)"
    assert child["owns_source"] is True
    # the copy outlives the job it came from
    authed(client, "DELETE", f"/api/jobs/{parent['id']}")
    assert wait_for(client.jobs, child["id"])["status"] == "done"
    missing = {"task": "dereverb", "stems_of": [{"job": parent["id"], "stem": "vocals"}]}
    assert authed(client, "POST", "/api/jobs", json=missing).status_code == 404


def test_original_mix_is_served_beside_the_stems(client, tmp_path):
    song = song_in(tmp_path, "a.wav")
    created = authed(client, "POST", "/api/jobs", json={"paths": [str(song)], "task": "vocals"}).json()
    job = wait_for(client.jobs, created["jobs"][0]["id"])
    assert job["original"] == "original.flac"
    original = client.get(f"/api/jobs/{job['id']}/original")
    assert original.headers["content-type"] == "audio/flac"
    assert client.get(f"/api/jobs/{job['id']}/peaks/original").json()["peak"] == [0.9]


def test_clearing_history_keeps_active_jobs(make_jobs, tmp_path):
    jobs = make_jobs("hang")
    with TestClient(create_app(jobs=jobs, token=TOKEN), base_url="http://127.0.0.1") as hung:
        song = song_in(tmp_path, "a.wav")
        body = {"paths": [str(song)], "task": "vocals"}
        first = authed(hung, "POST", "/api/jobs", json=body).json()["jobs"][0]
        second = authed(hung, "POST", "/api/jobs", json=body).json()["jobs"][0]
        authed(hung, "POST", f"/api/jobs/{second['id']}/cancel")
        assert authed(hung, "DELETE", "/api/jobs").json() == {"deleted": 1}
        assert [j["id"] for j in hung.get("/api/state").json()["jobs"]] == [first["id"]]


def test_error_log_is_readable(client, make_jobs, tmp_path):
    jobs = make_jobs("fail")
    with TestClient(create_app(jobs=jobs, token=TOKEN), base_url="http://127.0.0.1") as failing:
        song = song_in(tmp_path, "a.wav")
        job = authed(failing, "POST", "/api/jobs", json={"paths": [str(song)], "task": "vocals"}).json()[
            "jobs"
        ][0]
        wait_for(jobs, job["id"])
        assert failing.get(f"/api/jobs/{job['id']}/log").status_code == 404
        (jobs.job_dir(job["id"]) / "error.log").write_text("Traceback: boom", encoding="utf-8")
        assert failing.get(f"/api/jobs/{job['id']}/log").json() == {"log": "Traceback: boom"}


def test_unused_weights_are_listed_and_removed(client):
    from split import paths

    models = paths.models_dir()
    (models / "old_model.ckpt").write_bytes(b"x" * 1000)
    (models / "BS-Roformer-SW.ckpt.part").write_bytes(b"x" * 10)
    (models / "BS-Roformer-SW.yaml").write_bytes(b"kept")
    assert client.get("/api/catalog").json()["unused"] == {"count": 1, "size": 1000}
    assert authed(client, "DELETE", "/api/models/unused").json() == {"freed": 1000}
    assert sorted(p.name for p in models.iterdir()) == ["BS-Roformer-SW.ckpt.part", "BS-Roformer-SW.yaml"]


def test_malformed_bodies_are_refused_cleanly(client):
    bad = client.post(
        "/api/jobs", content=b"{nope", headers={"x-split-token": TOKEN, "content-type": "application/json"}
    )
    assert bad.status_code == 400
    assert authed(client, "POST", "/api/scan", json=["a"]).status_code == 400
