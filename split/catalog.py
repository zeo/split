"""Models, tasks and the recipes that tie them together. The single source of truth for the ui."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

HF = "https://huggingface.co"


@dataclass(frozen=True)
class WeightFile:
    name: str
    url: str
    size: int
    sha256: str


# every weight file split may download, pinned to the bytes that were tested
_PINS: dict[str, tuple[str, int, str]] = {
    "bs_roformer_vocals_resurrection_unwa.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/bs_roformer_vocals_resurrection_unwa.ckpt",
        204510749,
        "9dbfe5cb572e4ed32a15ec727d7bd06c8d7aba97509e6fda5bc008bb1e0b2dd5",
    ),
    "config_bs_roformer_vocals_resurrection_unwa.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/config_bs_roformer_vocals_resurrection_unwa.yaml",
        2348,
        "7d6010fdc12a4919c886b099b2567ec475ae2fa8b0acf438bd83385bc0cb31d9",
    ),
    "bs_leap_xe_voc.ckpt": (
        "https://huggingface.co/pcunwa/BS-Roformer-Leap/resolve/main/Xe/bs_leap_xe_voc.ckpt",
        267796851,
        "b739c1d2d87a81cd3dd3844ed9ad0bd678708c7a0a761a03a1aaff9af79a096d",
    ),
    "leap_xe_config_voc.yaml": (
        "https://huggingface.co/pcunwa/BS-Roformer-Leap/resolve/main/Xe/leap_xe_config_voc.yaml",
        2190,
        "d3cb8c84be2e9bcbc64c1086e2256dc097ab5addebc5ce507818e90ff8cbdc25",
    ),
    "bs_roformer_ft1_anvuew_sdr_12.55.ckpt": (
        "https://huggingface.co/anvuew/BS-RoFormer/resolve/main/bs_roformer_ft1_anvuew_sdr_12.55.ckpt",
        204493312,
        "60347271e8493fdff28ef558c3b2297afb869a1f4462594ed548038264bec395",
    ),
    "config_bs_roformer_ft1_anvuew.yaml": (
        "https://huggingface.co/anvuew/BS-RoFormer/resolve/main/config.yaml",
        1969,
        "033e57abee226a480ef410e0631b9fe00e8b7bc9a3bb5fe55659d0b43a238701",
    ),
    "becruily_deux.ckpt": (
        "https://huggingface.co/becruily/mel-band-roformer-deux/resolve/main/becruily_deux.ckpt",
        435006815,
        "10255c02295bf3e3865d4ee50ff752d7b19b124ed5fd93b147babc4333eda3aa",
    ),
    "config_deux_becruily.yaml": (
        "https://huggingface.co/becruily/mel-band-roformer-deux/resolve/main/config_deux_becruily.yaml",
        1175,
        "bb3ea9bce37ca96d63568490d5a92d7e41df3d7726788b6970c10d89eb62d902",
    ),
    "bs_roformer_instrumental_resurrection_unwa.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/bs_roformer_instrumental_resurrection_unwa.ckpt",
        204483033,
        "16311025a5133ae6411760ccfe9e3e66b31a01d9d8bec0a03fa7ec4bedac7a15",
    ),
    "config_bs_roformer_instrumental_resurrection_unwa.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/config_bs_roformer_instrumental_resurrection_unwa.yaml",
        2347,
        "d28c16f35e3118c8db3b5b28320d70e3fbb7ab46ab1ff1e60e0332b1e5871ba1",
    ),
    "bs_roformer_leap_inst.ckpt": (
        "https://huggingface.co/pcunwa/BS-Roformer-Leap/resolve/main/bs_roformer_leap_inst.ckpt",
        238212233,
        "1459b5eb70d7e1a805d8d080cb0d1abfcd06dc3931daedecad59944a8f7a0a57",
    ),
    "bs_leap_inst_conf.yaml": (
        "https://huggingface.co/pcunwa/BS-Roformer-Leap/resolve/main/bs_leap_inst_conf.yaml",
        1960,
        "2004e01f7019e9dd7bad44dd213b337dd055806811266f0f0ac925b3da33cb29",
    ),
    "mel_band_roformer_instrumental_becruily.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/mel_band_roformer_instrumental_becruily.ckpt",
        913106900,
        "a8da6632a1c25efb1c9be783ce9ea367d226d4b918cd6c3717c8b1d7a396041d",
    ),
    "config_mel_band_roformer_instrumental_becruily.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/config_mel_band_roformer_instrumental_becruily.yaml",
        1736,
        "a222235643d329817a1123d82d8eb38392d919e90ed597e053de49c092d3b442",
    ),
    "mel_band_roformer_instrumental_fv7z_gabox.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/mel_band_roformer_instrumental_fv7z_gabox.ckpt",
        913031195,
        "ef229f0dcd370c1767e4292981c59e5248814da45f32bfacebcc0f28adaa30a1",
    ),
    "config_mel_band_roformer_instrumental_gabox.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/config_mel_band_roformer_instrumental_gabox.yaml",
        920,
        "723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
    ),
    "bs_roformer_karaoke_anvuew.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/bs_roformer_karaoke_anvuew.ckpt",
        204486925,
        "206d04757cb5f75ca3b55f8a0a48f5c26aa2351d4ff3c7adbfc9affa30ea3ae4",
    ),
    "config_bs_roformer_karaoke_anvuew.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/config_bs_roformer_karaoke_anvuew.yaml",
        1973,
        "5cb3f127ecbc6a8e37f31ea7e05f60f360a44da43e857bde805b7b68558f6338",
    ),
    "bs_roformer_karaoke_frazer_becruily.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/bs_roformer_karaoke_frazer_becruily.ckpt",
        204436907,
        "eb90ee24c1154d83fbcfd27e96182f19e061557cc6e4746953125e08c29389f9",
    ),
    "config_bs_roformer_karaoke_frazer_becruily.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/config_bs_roformer_karaoke_frazer_becruily.yaml",
        1903,
        "1d3b58b473025183d0d3c91e7a444cb5f1418d9f34e8f46b8d2fb10d2cc8ab34",
    ),
    "bs_karaoke_gabox_IS.ckpt": (
        "https://huggingface.co/GaboxR67/MelBandRoformers/resolve/main/bsroformers/bs_karaoke_gabox_IS.ckpt",
        204483448,
        "db8357825398d4231031ad1ab4aa12a94bcaad8d67e8ce5e4b3c5b48fdee1d4f",
    ),
    "karaoke_bs_roformer_gabox.yaml": (
        "https://huggingface.co/GaboxR67/MelBandRoformers/resolve/main/bsroformers/karaoke_bs_roformer.yaml",
        1999,
        "ee6ce776404db78dc115179a9f5ca67c06dd379fbd2611890f3637a3caa14b7c",
    ),
    "BS-Roformer-SW.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/BS-Roformer-SW.ckpt",
        699412152,
        "24e7d35ee9c64415673d3fd33e06a67cac2c103c5df6267ba1576459c775916e",
    ),
    "BS-Roformer-SW.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/BS-Roformer-SW.yaml",
        4653,
        "b558996f1e25eb48798bd6502505a5de94c4f966d6edfb1a0420f06cc40b501a",
    ),
    "htdemucs.yaml": (
        "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/htdemucs.yaml",
        21,
        "239c445d0b14454d541ad8bd9bb271c9e536d267e8a4625208744cbb2e7bb66c",
    ),
    "955717e8-8726e21a.th": (
        "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th",
        84141911,
        "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4",
    ),
    "mdx23c_drumsep_5stem_aufr33_jarredou.ckpt": (
        "https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main/mdx23c/mdx23c_drumsep_5stem_aufr33_jarredou.ckpt",
        437648758,
        "1f8e636fb674b88a52c8399fde9a4ebe2b72b065ca07eed4e03ab1c9f0bfb2e0",
    ),
    "mdx23c_drumsep_5stem_aufr33_jarredou_config.yaml": (
        "https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main/mdx23c/mdx23c_drumsep_5stem_aufr33_jarredou_config.yaml",
        1061,
        "b559768ab3209adb667d6d9c0bab2816107b03a86f75df432f9f275990ecb9bb",
    ),
    "dereverb_bs_roformer_anvuew_sdr_22.5050.ckpt": (
        "https://huggingface.co/anvuew/dereverb_bs_roformer/resolve/main/dereverb_bs_roformer_anvuew_sdr_22.5050.ckpt",
        204496717,
        "b4dfa4c4aa251c0afc303e5d512d904a1c2255e51d8d0dbfbddb18d740563d42",
    ),
    "config_dereverb_bs_roformer_anvuew.yaml": (
        "https://huggingface.co/anvuew/dereverb_bs_roformer/resolve/main/config.yaml",
        1969,
        "5022524393c946974ec160df81b82299cd0055fb1f1b51058cb251098d9a01b7",
    ),
    "dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt",
        913107578,
        "0db8f1b41c00cead1112e967262a12802fd32e76c0c3a8eb207e772bae25d07b",
    ),
    "dereverb_mel_band_roformer_anvuew.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/dereverb_mel_band_roformer_anvuew.yaml",
        1846,
        "1599d9ea717ea2b5b3bc55d936f752b8d0f67baaa3de95acd6d03259a2f37784",
    ),
    "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt",
        913097300,
        "7c1c39191edc34e942ca7f2346ce6b6c0e1208a5f76349ffce6f696bd12910de",
    ),
    "denoise_mel_band_roformer_aufr33_sdr_27.9959_config.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/denoise_mel_band_roformer_aufr33_sdr_27.9959_config.yaml",
        1621,
        "5d7d83b2e9d232da60941b717b0abdc345155d45cff3f79715cdb2790ba18c36",
    ),
    "denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt",
        913097300,
        "a25e3b233722cd81e2de7b8e798a3fef29d4b9799ccacda60b0dc958a1e2a5bb",
    ),
    "denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768_config.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768_config.yaml",
        1621,
        "5d7d83b2e9d232da60941b717b0abdc345155d45cff3f79715cdb2790ba18c36",
    ),
    "mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt",
        913096801,
        "ca8799531fe51c94172cc047226209ed48bf7d8c02e04671795a15d2a1c318af",
    ),
    "mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144_config.yaml": (
        "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144_config.yaml",
        1621,
        "029e5dce3abae9d9895ea19449c2b1fe749417437751676474affe255846d0de",
    ),
}


def _files(*names: str) -> tuple[WeightFile, ...]:
    return tuple(WeightFile(name, *_PINS[name]) for name in names)


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    author: str
    arch: str
    files: tuple[WeightFile, ...]
    # output label reported by the model (lowercase) -> split's stem name
    stems: dict[str, str]
    license: str
    source: str
    scores: dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def load_name(self) -> str:
        return self.files[0].name

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    def public(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "author": self.author,
            "license": self.license,
            "source": self.source,
            "scores": self.scores,
            "note": self.note,
            "size": self.size,
            "stems": sorted(set(self.stems.values())),
        }


VOCAL_PAIR = {
    "vocals": "vocals",
    "other": "instrumental",
    "instrumental": "instrumental",
    "instrument": "instrumental",
}
KARAOKE_PAIR = {"vocals": "lead", "instrumental": "backing"}
UNSTATED = "Not stated by the author"
SW_NOTE = (
    "Reportedly extracted from Apple Logic Pro; the original upload is gone and this copy is mirrored by "
    "audio-separator. Its license is unknown, so treat output as personal use only."
)

_MODELS = [
    Model(
        "resurrection-voc",
        "Resurrection vocals",
        "unwa",
        "roformer",
        _files(
            "bs_roformer_vocals_resurrection_unwa.ckpt", "config_bs_roformer_vocals_resurrection_unwa.yaml"
        ),
        VOCAL_PAIR,
        UNSTATED,
        f"{HF}/pcunwa/BS-Roformer-Resurrection",
        {"vocals": 11.34, "instrumental": 17.64},
    ),
    Model(
        "leap-xe-voc",
        "Leap Xe vocals",
        "unwa",
        "roformer",
        _files("bs_leap_xe_voc.ckpt", "leap_xe_config_voc.yaml"),
        VOCAL_PAIR,
        UNSTATED,
        f"{HF}/pcunwa/BS-Roformer-Leap",
        {"vocals": 11.76, "instrumental": 18.07},
    ),
    Model(
        "anvuew-ft1",
        "BS-RoFormer ft1",
        "anvuew",
        "roformer",
        _files("bs_roformer_ft1_anvuew_sdr_12.55.ckpt", "config_bs_roformer_ft1_anvuew.yaml"),
        VOCAL_PAIR,
        "GPL-3.0",
        f"{HF}/anvuew/BS-RoFormer",
        {"vocals": 11.54, "instrumental": 17.85},
    ),
    Model(
        "deux",
        "Deux",
        "becruily",
        "roformer",
        _files("becruily_deux.ckpt", "config_deux_becruily.yaml"),
        VOCAL_PAIR,
        "CC-BY-NC-4.0",
        f"{HF}/becruily/mel-band-roformer-deux",
        {"vocals": 11.37, "instrumental": 17.55},
    ),
    Model(
        "resurrection-inst",
        "Resurrection instrumental",
        "unwa",
        "roformer",
        _files(
            "bs_roformer_instrumental_resurrection_unwa.ckpt",
            "config_bs_roformer_instrumental_resurrection_unwa.yaml",
        ),
        VOCAL_PAIR,
        UNSTATED,
        f"{HF}/pcunwa/BS-Roformer-Resurrection",
        {"instrumental": 17.25},
    ),
    Model(
        "leap-inst",
        "Leap instrumental",
        "unwa",
        "roformer",
        _files("bs_roformer_leap_inst.ckpt", "bs_leap_inst_conf.yaml"),
        VOCAL_PAIR,
        UNSTATED,
        f"{HF}/pcunwa/BS-Roformer-Leap",
        {"instrumental": 17.76},
    ),
    Model(
        "becruily-inst",
        "Instrumental",
        "becruily",
        "roformer",
        _files(
            "mel_band_roformer_instrumental_becruily.ckpt",
            "config_mel_band_roformer_instrumental_becruily.yaml",
        ),
        VOCAL_PAIR,
        UNSTATED,
        f"{HF}/becruily/mel-band-roformer-instrumental",
    ),
    Model(
        "fv7z",
        "Instrumental Fv7z",
        "Gabox",
        "roformer",
        _files(
            "mel_band_roformer_instrumental_fv7z_gabox.ckpt",
            "config_mel_band_roformer_instrumental_gabox.yaml",
        ),
        VOCAL_PAIR,
        UNSTATED,
        f"{HF}/GaboxR67/MelBandRoformers",
    ),
    Model(
        "karaoke-anvuew",
        "Karaoke",
        "anvuew",
        "roformer",
        _files("bs_roformer_karaoke_anvuew.ckpt", "config_bs_roformer_karaoke_anvuew.yaml"),
        KARAOKE_PAIR,
        "GPL-3.0",
        f"{HF}/anvuew/karaoke_bs_roformer",
        {"lead": 10.20},
    ),
    Model(
        "karaoke-frazer",
        "Karaoke (frazer)",
        "frazer and becruily",
        "roformer",
        _files("bs_roformer_karaoke_frazer_becruily.ckpt", "config_bs_roformer_karaoke_frazer_becruily.yaml"),
        KARAOKE_PAIR,
        UNSTATED,
        f"{HF}/becruily/bs-roformer-karaoke",
        {"lead": 10.06},
    ),
    Model(
        "karaoke-gabox",
        "Karaoke IS",
        "Gabox",
        "roformer",
        _files("bs_karaoke_gabox_IS.ckpt", "karaoke_bs_roformer_gabox.yaml"),
        {"vocals": "lead", "other": "backing"},
        UNSTATED,
        f"{HF}/GaboxR67/MelBandRoformers",
    ),
    Model(
        "sw",
        "BS-RoFormer SW",
        "unknown",
        "roformer",
        _files("BS-Roformer-SW.ckpt", "BS-Roformer-SW.yaml"),
        {s: s for s in ("vocals", "drums", "bass", "guitar", "piano", "other")},
        "Unknown",
        "https://github.com/nomadkaraoke/python-audio-separator",
        {"vocals": 11.30, "drums": 14.11, "bass": 14.62, "other": 8.72, "guitar": 9.01, "piano": 7.80},
        SW_NOTE,
    ),
    Model(
        "htdemucs",
        "HT Demucs",
        "Alexandre Défossez",
        "demucs",
        _files("htdemucs.yaml", "955717e8-8726e21a.th"),
        {s: s for s in ("vocals", "drums", "bass", "other")},
        "MIT",
        "https://github.com/adefossez/demucs",
    ),
    Model(
        "drumsep-5",
        "DrumSep 5-stem",
        "aufr33 and jarredou",
        "roformer",
        _files(
            "mdx23c_drumsep_5stem_aufr33_jarredou.ckpt", "mdx23c_drumsep_5stem_aufr33_jarredou_config.yaml"
        ),
        {"kick": "kick", "snare": "snare", "toms": "toms", "hh": "hihat", "cymbals": "cymbals"},
        UNSTATED,
        f"{HF}/noblebarkrr/mvsepless_resources",
        {"kick": 16.66, "snare": 11.53, "toms": 12.33, "hihat": 4.04, "cymbals": 6.36},
        "The authors' original upload is gone; this is a community mirror pinned by checksum.",
    ),
    Model(
        "dereverb-bs",
        "De-reverb",
        "anvuew",
        "roformer",
        _files("dereverb_bs_roformer_anvuew_sdr_22.5050.ckpt", "config_dereverb_bs_roformer_anvuew.yaml"),
        {"noreverb": "dry", "reverb": "reverb"},
        "GPL-3.0",
        f"{HF}/anvuew/dereverb_bs_roformer",
    ),
    Model(
        "dereverb-gentle",
        "De-reverb, less aggressive",
        "anvuew",
        "roformer",
        _files(
            "dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt",
            "dereverb_mel_band_roformer_anvuew.yaml",
        ),
        {"noreverb": "dry", "reverb": "reverb"},
        "GPL-3.0",
        f"{HF}/anvuew/dereverb_mel_band_roformer",
    ),
    Model(
        "denoise",
        "Denoise",
        "aufr33",
        "roformer",
        _files(
            "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt",
            "denoise_mel_band_roformer_aufr33_sdr_27.9959_config.yaml",
        ),
        {"dry": "clean", "other": "noise"},
        UNSTATED,
        "https://github.com/nomadkaraoke/python-audio-separator",
    ),
    Model(
        "denoise-strong",
        "Denoise, aggressive",
        "aufr33",
        "roformer",
        _files(
            "denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt",
            "denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768_config.yaml",
        ),
        {"dry": "clean", "other": "noise"},
        UNSTATED,
        "https://github.com/nomadkaraoke/python-audio-separator",
    ),
    Model(
        "crowd",
        "Crowd removal",
        "aufr33 and viperx",
        "roformer",
        _files(
            "mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt",
            "mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144_config.yaml",
        ),
        {"crowd": "crowd", "other": "clean"},
        UNSTATED,
        "https://github.com/nomadkaraoke/python-audio-separator",
    ),
]

MODELS: dict[str, Model] = {m.id: m for m in _MODELS}


def file_names() -> set[str]:
    return set(_PINS)


@dataclass(frozen=True)
class Step:
    models: tuple[str, ...]
    # model stem -> output stem; several model stems may fold into one output by summing
    outputs: dict[str, str]
    input: str = "mix"
    algorithm: str = "avg_wave"
    # share of the second output folded back into the first, so a lighter touch still sums to the input
    keep: float = 0.0


@dataclass(frozen=True)
class Tier:
    id: str
    label: str
    blurb: str
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Task:
    id: str
    label: str
    blurb: str
    group: str
    stems: tuple[str, ...]
    tiers: tuple[Tier, ...]
    isolatable: bool = False
    splittable: bool = False

    @property
    def default_tier(self) -> str:
        return next((t.id for t in self.tiers if t.id == "best"), self.tiers[0].id)

    def tier(self, tier_id: str) -> Tier:
        for tier in self.tiers:
            if tier.id == tier_id:
                return tier
        raise ValueError(f"{self.label} has no {tier_id!r} tier")

    def stems_for(self, isolate: bool, lead_back: bool = False) -> tuple[str, ...]:
        if lead_back and self.splittable:
            return tuple(
                s for stem in self.stems for s in (("lead", "back") if stem == "vocals" else (stem,))
            )
        return (*self.stems, "instrumental") if isolate and self.isolatable else self.stems

    def public(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "blurb": self.blurb,
            "group": self.group,
            "stems": list(self.stems),
            "isolatable": self.isolatable,
            "splittable": self.splittable,
            "default_tier": self.default_tier,
            "tiers": [
                {
                    "id": t.id,
                    "label": t.label,
                    "blurb": t.blurb,
                    "models": list(dict.fromkeys(m for step in t.steps for m in step.models)),
                    "steps": [_public_step(step) for step in plan(self.id, t.id)],
                    "isolated_steps": [_public_step(step) for step in plan(self.id, t.id, True)],
                    "split_steps": [_public_step(step) for step in plan(self.id, t.id, lead_back=True)],
                }
                for t in self.tiers
            ],
        }


def _public_step(step: Step) -> dict:
    return {
        "models": list(step.models),
        "input": step.input,
        "outputs": list(dict.fromkeys(step.outputs.values())),
    }


def _one(model: str, outputs: dict[str, str] | None = None, source: str = "mix") -> Step:
    if outputs is None:
        outputs = {s: s for s in dict.fromkeys(MODELS[model].stems.values())}
    return Step((model,), outputs, source)


PAIR = {"vocals": "vocals", "instrumental": "instrumental"}
KARAOKE_ULTRA = ("karaoke-anvuew", "karaoke-frazer", "karaoke-gabox")
BAND4 = {
    "vocals": "vocals",
    "drums": "drums",
    "bass": "bass",
    "other": "other",
    "guitar": "other",
    "piano": "other",
}

TASKS: dict[str, Task] = {
    t.id: t
    for t in [
        Task(
            "vocals",
            "Vocals",
            "Every voice in one stem, the backing track in the other",
            "separate",
            ("vocals", "instrumental"),
            (
                Tier(
                    "fast",
                    "Fast",
                    "Resurrection: a lighter model, about twice as quick",
                    (_one("resurrection-voc"),),
                ),
                Tier(
                    "best",
                    "Best",
                    "Leap Xe: the highest-scoring vocal model you can run locally",
                    (_one("leap-xe-voc"),),
                ),
                Tier(
                    "ultra",
                    "Ultra",
                    "Leap Xe, ft1 and Deux averaged sample by sample",
                    (Step(("leap-xe-voc", "anvuew-ft1", "deux"), PAIR),),
                ),
            ),
            splittable=True,
        ),
        Task(
            "instrumental",
            "Instrumental",
            "A backing track tuned to leave as little voice behind as possible",
            "separate",
            ("instrumental", "vocals"),
            (
                Tier("fast", "Fast", "Resurrection instrumental", (_one("resurrection-inst"),)),
                Tier(
                    "best",
                    "Best",
                    "Leap Xe: the top instrumental score and the least voice left behind",
                    (_one("leap-xe-voc"),),
                ),
                Tier(
                    "full",
                    "Full",
                    "Leap instrumental: a fuller backing track that keeps a trace more voice",
                    (_one("leap-inst"),),
                ),
                Tier(
                    "ultra",
                    "Ultra",
                    "Leap, becruily and Fv7z instrumental models averaged",
                    (Step(("leap-inst", "becruily-inst", "fv7z"), PAIR),),
                ),
            ),
        ),
        Task(
            "karaoke",
            "Karaoke",
            "The lead singer alone, with harmonies kept in the backing track",
            "separate",
            ("lead", "backing"),
            (
                Tier("best", "Best", "anvuew karaoke model", (_one("karaoke-anvuew"),)),
                Tier(
                    "ultra",
                    "Ultra",
                    "anvuew, frazer/becruily and Gabox karaoke models averaged",
                    (Step(KARAOKE_ULTRA, {"lead": "lead", "backing": "backing"}),),
                ),
            ),
        ),
        Task(
            "band4",
            "4 stems",
            "Vocals, drums, bass and everything else",
            "separate",
            ("vocals", "drums", "bass", "other"),
            (
                Tier("fast", "Fast", "HT Demucs: quick and light on memory", (_one("htdemucs"),)),
                Tier(
                    "best",
                    "Best",
                    "BS-RoFormer SW, with guitar and piano folded into other",
                    (_one("sw", BAND4),),
                ),
            ),
        ),
        Task(
            "band6",
            "6 stems",
            "The four-stem split plus guitar and piano",
            "separate",
            ("vocals", "drums", "bass", "guitar", "piano", "other"),
            (Tier("best", "Best", "BS-RoFormer SW", (_one("sw"),)),),
        ),
        Task(
            "drums",
            "Drum kit",
            "Kick, snare, toms, hi-hat and cymbals as separate tracks",
            "separate",
            ("kick", "snare", "toms", "hihat", "cymbals"),
            (
                Tier(
                    "best",
                    "Best",
                    "SW pulls the drums out, then DrumSep splits the kit",
                    (_one("sw", {}), _one("drumsep-5", source="drums")),
                ),
            ),
        ),
        Task(
            "dereverb",
            "De-reverb",
            "Strip room sound and echo, keep the dry voice",
            "clean",
            ("dry", "reverb"),
            (
                Tier("best", "Strong", "anvuew BS de-reverb", (_one("dereverb-bs"),)),
                Tier("gentle", "Gentle", "anvuew Mel de-reverb, less aggressive", (_one("dereverb-gentle"),)),
            ),
            isolatable=True,
        ),
        Task(
            "denoise",
            "Denoise",
            "Take out hiss, hum and background noise",
            "clean",
            ("clean", "noise"),
            (
                Tier(
                    "mild",
                    "Mild",
                    "aufr33 denoise with half the noise left in",
                    (Step(("denoise",), {"clean": "clean", "noise": "noise"}, keep=0.5),),
                ),
                Tier("best", "Normal", "aufr33 denoise", (_one("denoise"),)),
                Tier("strong", "Aggressive", "aufr33 denoise, aggressive", (_one("denoise-strong"),)),
            ),
            isolatable=True,
        ),
        Task(
            "crowd",
            "Crowd",
            "Pull audience noise and applause out of live recordings",
            "clean",
            ("clean", "crowd"),
            (Tier("best", "Best", "aufr33 and viperx crowd model", (_one("crowd"),)),),
        ),
    ]
}

ISOLATE = Step(("leap-xe-voc",), {"instrumental": "instrumental"})
MODES = {"balanced": "avg_wave", "clear": "uvr_min_spec", "deep": "uvr_max_spec"}


def plan(
    task_id: str, tier_id: str, isolate: bool = False, lead_back: bool = False, mode: str = "balanced"
) -> tuple[Step, ...]:
    task = TASKS[task_id]
    steps = task.tier(tier_id).steps
    if isolate and task.isolatable:
        steps = (ISOLATE, *(replace(s, input="vocals") for s in steps))
    if lead_back and task.splittable:
        karaoke = KARAOKE_ULTRA if tier_id == "ultra" else ("karaoke-anvuew",)
        steps = (
            *(replace(s, outputs={k: v for k, v in s.outputs.items() if v != "vocals"}) for s in steps),
            Step(karaoke, {"lead": "lead", "backing": "back"}, "vocals"),
        )
    return tuple(replace(s, algorithm=MODES[mode]) if len(s.models) > 1 else s for s in steps)


def public() -> dict:
    return {
        "tasks": [t.public() for t in TASKS.values()],
        "models": {m.id: m.public() for m in MODELS.values()},
    }
