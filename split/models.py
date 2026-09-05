"""Model registry: SOTA separators newer and better than Demucs htdemucs_ft.

Vocal SDR reference (audio-separator catalog, higher is better):
  Viperx-1297 12.98 · Kim Mel-Band 12.6 · Big Beta 4 12.5 · htdemucs_ft 10.8
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelInfo:
    id: str
    backend: str  # 'roformer' (audio-separator) | 'demucs' (subprocess)
    filename: str  # audio-separator model filename, or demucs model name
    label: str
    description: str
    stems: list[str]
    quality: str  # fast / balanced / best
    sdr: dict[str, float] = field(default_factory=dict)
    # maps lowercase token parsed from output filename -> canonical stem name
    aliases: dict[str, str] = field(default_factory=dict)


MODELS: list[ModelInfo] = [
    # ---- Vocals / karaoke (RoFormer family — beats htdemucs_ft by ~2 dB) ----
    ModelInfo(
        id="fast-mdx",
        backend="roformer",
        filename="UVR-MDX-NET-Inst_HQ_3.onnx",
        label="MDX Inst HQ3 (Fast)",
        description="ONNX preview model. Seconds per track, great for quick checks.",
        stems=["vocals", "instrumental"],
        quality="fast",
        sdr={"vocals": 8.8, "instrumental": 15.4},
        aliases={"vocals": "vocals", "instrumental": "instrumental"},
    ),
    ModelInfo(
        id="kim-vocals",
        backend="roformer",
        filename="vocals_mel_band_roformer.ckpt",
        label="Kim Mel-Band RoFormer (Balanced)",
        description="Vocal SDR 12.6 vs 10.8 for Demucs ft. The default workhorse.",
        stems=["vocals", "instrumental"],
        quality="balanced",
        sdr={"vocals": 12.6},
        aliases={"vocals": "vocals", "other": "instrumental",
                 "instrumental": "instrumental", "instrument": "instrumental"},
    ),
    ModelInfo(
        id="viperx-1297",
        backend="roformer",
        filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        label="BS-RoFormer Viperx-1297 (Best)",
        description="Top published vocal SDR (12.98). The lalal.ai-beater. Slower.",
        stems=["vocals", "instrumental"],
        quality="best",
        sdr={"vocals": 12.98, "instrumental": 16.5},
        aliases={"vocals": "vocals", "instrumental": "instrumental",
                 "other": "instrumental"},
    ),
    ModelInfo(
        id="karaoke-becruily",
        backend="roformer",
        filename="mel_band_roformer_karaoke_becruily.ckpt",
        label="Karaoke by becruily",
        description="Checkpoint tuned specifically for karaoke/instrumental tracks.",
        stems=["vocals", "instrumental"],
        quality="balanced",
        aliases={"vocals": "vocals", "instrumental": "instrumental",
                 "instrument": "instrumental", "karaoke": "instrumental",
                 "accompaniment": "instrumental", "other": "instrumental"},
    ),
    ModelInfo(
        id="karaoke-ensemble",
        backend="roformer-ensemble",
        filename="karaoke",
        label="Karaoke Ensemble (Ultra)",
        description="3-model karaoke ensemble (Aufr33 Viperx + Gabox V2 + becruily). Highest-quality instrumental.",
        stems=["vocals", "instrumental"],
        quality="ultra",
        sdr={"vocals": 10.6, "instrumental": 16.5},
        aliases={"vocals": "vocals", "instrumental": "instrumental",
                 "instrument": "instrumental", "karaoke": "instrumental",
                 "accompaniment": "instrumental", "other": "instrumental"},
    ),
    ModelInfo(
        id="vocals-ensemble",
        backend="roformer-ensemble",
        filename="vocal_clean",
        label="Vocal Clean Ensemble (Ultra)",
        description="Revive V2 + Kim FT2-bleedless ensemble. Minimal instrument bleed in vocals.",
        stems=["vocals", "instrumental"],
        quality="ultra",
        aliases={"vocals": "vocals", "instrumental": "instrumental",
                 "other": "instrumental"},
    ),
    # ---- Full band (Demucs still SOTA for drums/bass/guitar/piano) ----
    ModelInfo(
        id="hdemucs_mmi",
        backend="demucs",
        filename="hdemucs_mmi",
        label="Demucs MMI (Fast)",
        description="Fast 4-stem preview: vocals/drums/bass/other.",
        stems=["vocals", "drums", "bass", "other"],
        quality="fast",
        sdr={"vocals": 10.2, "drums": 9.6, "bass": 12.2},
    ),
    ModelInfo(
        id="htdemucs",
        backend="demucs",
        filename="htdemucs",
        label="HD Demucs (Balanced)",
        description="Hybrid-Transformer 4-stem separation.",
        stems=["vocals", "drums", "bass", "other"],
        quality="balanced",
        sdr={"vocals": 9.9, "drums": 9.4, "bass": 11.6},
    ),
    ModelInfo(
        id="htdemucs_ft",
        backend="demucs",
        filename="htdemucs_ft",
        label="HD Demucs fine-tuned (Best 4-stem)",
        description="Best open 4-stem: vocals SDR 10.8, bass 12.0.",
        stems=["vocals", "drums", "bass", "other"],
        quality="best",
        sdr={"vocals": 10.8, "drums": 10.0, "bass": 12.0},
    ),
    ModelInfo(
        id="htdemucs_6s",
        backend="demucs",
        filename="htdemucs_6s",
        label="HD Demucs 6-stem (Pro)",
        description="Only true 6-stem open model: adds guitar + piano.",
        stems=["vocals", "drums", "bass", "guitar", "piano", "other"],
        quality="best",
        sdr={"vocals": 9.6, "drums": 8.5, "bass": 10.1},
    ),
    # ---- Specialists ----
    ModelInfo(
        id="drumsep-mdx23c",
        backend="roformer",
        filename="MDX23C-DrumSep-aufr33-jarredou.ckpt",
        label="MDX23C DrumSep (Pro drums)",
        description="Splits drums into kick/snare/toms/hats/ride/crash.",
        stems=["kick", "snare", "toms", "hh", "ride", "crash"],
        quality="best",
        aliases={"kick": "kick", "snare": "snare", "toms": "toms",
                 "hh": "hh", "ride": "ride", "crash": "crash",
                 "hi-hat": "hh", "hihat": "hh"},
    ),
    ModelInfo(
        id="denoise",
        backend="roformer",
        filename="denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt",
        label="Denoise (Aufr33)",
        description="Removes noise/bleed, keeps full-bandwidth dry signal.",
        stems=["denoised", "noise"],
        quality="balanced",
        aliases={"dry": "denoised", "other": "noise", "noise": "noise"},
    ),
    ModelInfo(
        id="dereverb-v2",
        backend="roformer",
        filename="dereverb-echo_mel_band_roformer_sdr_13.4843_v2.ckpt",
        label="De-Reverb/Echo V2 (Pro cleanup)",
        description="Strips reverb and echo tails from vocals and mixes.",
        stems=["dry", "removed"],
        quality="best",
        aliases={"dry": "dry", "no dry": "removed", "reverb": "removed",
                 "echo": "removed", "wet": "removed"},
    ),
]

MODEL_IDS = [m.id for m in MODELS]

# Sidebar task -> tier -> model id. This is what beats lalal.ai per use case.
TASK_TIERS: dict[str, dict[str, str]] = {
    "vocals": {"fast": "fast-mdx", "balanced": "kim-vocals", "best": "viperx-1297", "ultra": "vocals-ensemble"},
    "karaoke": {"fast": "fast-mdx", "balanced": "karaoke-becruily", "best": "viperx-1297", "ultra": "karaoke-ensemble"},
    "band": {"fast": "hdemucs_mmi", "balanced": "htdemucs", "best": "htdemucs_ft", "ultra": "htdemucs_ft"},
    "band6": {"fast": "htdemucs", "balanced": "htdemucs_6s", "best": "htdemucs_6s", "ultra": "htdemucs_6s"},
    "drums": {"fast": "htdemucs_ft", "balanced": "drumsep-mdx23c", "best": "drumsep-mdx23c", "ultra": "drumsep-mdx23c"},
    "cleanup": {"fast": "denoise", "balanced": "denoise", "best": "dereverb-v2", "ultra": "dereverb-v2"},
}

TASKS: dict[str, dict] = {
    "vocals": {"label": "Vocals", "icon": "🎙", "desc": "Lead vocal + instrumental"},
    "karaoke": {"label": "Karaoke", "icon": "🎶", "desc": "Instrumental track maker"},
    "band": {"label": "Full band", "icon": "🥁", "desc": "Vocals / drums / bass / other"},
    "band6": {"label": "Band 6-stem", "icon": "🎸", "desc": "+ guitar and piano"},
    "drums": {"label": "Drum kit", "icon": "🥁", "desc": "Kick / snare / toms / cymbals"},
    "cleanup": {"label": "Cleanup", "icon": "✨", "desc": "Denoise / de-reverb"},
}


def get_model(model_id: str) -> ModelInfo:
    for m in MODELS:
        if m.id == model_id:
            return m
    raise ValueError(f"Unknown model {model_id!r}. Choose from: {MODEL_IDS}")


def resolve_model(task: str, tier: str) -> ModelInfo:
    try:
        return get_model(TASK_TIERS[task][tier])
    except KeyError:
        raise ValueError(f"Unknown task/tier {task!r}/{tier!r}")
