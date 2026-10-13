import json

from conftest import wait_for

from split.jobs import KEEP_JOBS


def spec(source, **extra):
    return {
        "name": "song",
        "source": str(source),
        "task": "vocals",
        "tier": "best",
        "stems": ["vocals", "instrumental"],
        "format": "wav",
        **extra,
    }


def test_job_runs_to_done_and_persists(make_jobs, tmp_path):
    jobs = make_jobs()
    jobs.start()
    record = jobs.submit(spec(tmp_path / "a.wav"))
    done = wait_for(jobs, record["id"])
    assert done["status"] == "done"
    assert done["outputs"] == {"vocals": "vocals.wav", "instrumental": "instrumental.wav"}
    saved = json.loads((jobs.job_dir(record["id"]) / "job.json").read_text())
    assert saved["status"] == "done"
    assert jobs.snapshot()["device"]["kind"] == "cpu"


def test_jobs_run_one_at_a_time_in_order(make_jobs, tmp_path):
    jobs = make_jobs()
    jobs.start()
    ids = [jobs.submit(spec(tmp_path / f"{i}.wav"))["id"] for i in range(3)]
    for job_id in ids:
        wait_for(jobs, job_id)
    assert [r["key"] for r in jobs.supervisor.requests] == ids


def test_failure_keeps_message_and_kind(make_jobs, tmp_path):
    jobs = make_jobs("fail")
    jobs.start()
    record = wait_for(jobs, jobs.submit(spec(tmp_path / "a.wav"))["id"])
    assert record["status"] == "error"
    assert record["error_kind"] == "oom"


def test_worker_crash_is_reported(make_jobs, tmp_path):
    jobs = make_jobs("crash")
    jobs.start()
    record = wait_for(jobs, jobs.submit(spec(tmp_path / "a.wav"))["id"])
    assert record["status"] == "error"
    assert record["error_kind"] == "crash"


def test_cancel_running_kills_the_worker(make_jobs, tmp_path):
    jobs = make_jobs("hang")
    jobs.start()
    record = jobs.submit(spec(tmp_path / "a.wav"))
    wait_for(jobs, record["id"], statuses=("running",))
    assert jobs.cancel(record["id"])
    assert wait_for(jobs, record["id"])["status"] == "cancelled"
    assert jobs.supervisor.kills == 1


def test_cancel_queued_never_reaches_the_worker(make_jobs, tmp_path):
    jobs = make_jobs()
    record = jobs.submit(spec(tmp_path / "a.wav"))
    assert jobs.cancel(record["id"])
    jobs.start()
    assert jobs.get(record["id"])["status"] == "cancelled"
    assert not jobs.supervisor.requests


def test_interrupted_jobs_are_marked_on_reload(make_jobs, tmp_path):
    root = tmp_path / "jobs"
    first = make_jobs("hang", root=root)
    first.start()
    record = first.submit(spec(tmp_path / "a.wav"))
    wait_for(first, record["id"], statuses=("running",))
    reloaded = make_jobs(root=root)
    again = reloaded.get(record["id"])
    assert again["status"] == "error"
    assert again["error_kind"] == "interrupted"


def test_retry_and_delete(make_jobs, tmp_path):
    jobs = make_jobs("fail")
    jobs.start()
    first = wait_for(jobs, jobs.submit(spec(tmp_path / "a.wav"))["id"])
    second = jobs.retry(first["id"])
    assert second["id"] != first["id"]
    wait_for(jobs, second["id"])
    assert jobs.delete(first["id"])
    assert jobs.get(first["id"]) is None
    assert not jobs.job_dir(first["id"]).exists()


def test_uploads_are_removed_with_their_job(make_jobs, tmp_path):
    jobs = make_jobs()
    jobs.start()
    upload = tmp_path / "upload.wav"
    upload.write_bytes(b"x")
    record = wait_for(jobs, jobs.submit(spec(upload, owns_source=True))["id"])
    assert not upload.exists()
    jobs.delete(record["id"])


def test_sweep_keeps_recent_jobs_only(make_jobs, tmp_path):
    jobs = make_jobs()
    jobs.start()
    ids = [jobs.submit(spec(tmp_path / f"{i}.wav"))["id"] for i in range(KEEP_JOBS + 3)]
    for job_id in ids:
        wait_for(jobs, job_id)
    assert len(jobs.list()) == KEEP_JOBS
    old = jobs.list()[-1]
    assert jobs.sweep(now=old["created"] + 30 * 86400) == KEEP_JOBS
