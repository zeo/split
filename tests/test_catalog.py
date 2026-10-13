import json
import re
from importlib import resources

import pytest

from split import catalog


def audio_separator_names() -> set[str]:
    listing = json.loads(resources.files("audio_separator").joinpath("models.json").read_text())
    names = set()
    for group in ("roformer_download_list", "mdx23c_download_list"):
        for files in listing[group].values():
            names.update(files)
            names.update(files.values())
    return names


def test_every_pin_is_well_formed():
    for model in catalog.MODELS.values():
        for weight in model.files:
            assert weight.url.startswith("https://"), weight.name
            assert re.fullmatch(r"[0-9a-f]{64}", weight.sha256), weight.name
            assert weight.size > 0, weight.name
        assert model.files[0].name.endswith((".ckpt", ".yaml")), model.id


def test_model_ids_and_file_names_are_unique():
    files = [f.name for m in catalog.MODELS.values() for f in m.files]
    labels = [(m.author, m.label) for m in catalog.MODELS.values()]
    assert len(labels) == len(set(labels))
    assert len(files) >= len(set(files))
    assert catalog.file_names() == set(files)


def test_catalog_models_match_audio_separator_names():
    # weights hosted by audio-separator must keep the exact names its loader expects
    known = audio_separator_names()
    for model in catalog.MODELS.values():
        if "python-audio-separator" in model.files[0].url:
            assert {f.name for f in model.files} <= known, model.id


@pytest.mark.parametrize("task", list(catalog.TASKS.values()), ids=lambda t: t.id)
def test_every_tier_produces_exactly_the_task_stems(task):
    for tier in task.tiers:
        for isolate in {False, task.isolatable}:
            produced: set[str] = set()
            available = {"mix"}
            for step in catalog.plan(task.id, tier.id, isolate):
                assert step.input in available, (tier.id, step.input)
                for model_id in step.models:
                    model = catalog.MODELS[model_id]
                    assert set(step.outputs) <= set(model.stems.values()), (model_id, step.outputs)
                    available |= set(model.stems.values())
                if len(step.models) > 1:
                    stems = [set(catalog.MODELS[m].stems.values()) for m in step.models]
                    assert all(s == stems[0] for s in stems), "ensembled models must agree on stems"
                produced |= set(step.outputs.values())
            assert produced == set(task.stems_for(isolate)), (tier.id, isolate)


def test_default_tier_exists_and_public_shape():
    data = catalog.public()
    for task in data["tasks"]:
        assert task["default_tier"] in {t["id"] for t in task["tiers"]}
        for tier in task["tiers"]:
            assert all(m in data["models"] for m in tier["models"])


def test_unknown_tier_is_rejected():
    with pytest.raises(ValueError):
        catalog.TASKS["vocals"].tier("legendary")


def test_notices_list_every_model_source():
    from pathlib import Path

    notices = (Path(__file__).parent.parent / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for model in catalog.MODELS.values():
        assert model.source in notices, model.id
        assert model.label.split(",")[0] in notices, model.id
