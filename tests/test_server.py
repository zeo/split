import io
import zipfile
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
        ({"task": "vocals", "paths": []}, "Add at least one file"),
        ({"task": "vocals", "paths": ["Z:/definitely/missing.wav"]}, "is not a file"),
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
            assert "Â" not in text and "â€" not in text, f"mojibake in {asset.name}"


def test_ui_assets_are_revalidated(client):
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
