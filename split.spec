# PyInstaller build for Split.exe (Windows, onedir with console for first-run logs)
# Usage: pyinstaller split.spec
# Output: dist/Split/Split.exe (+ _internal with torch/demucs/audio-separator)
import pathlib

block_cipher = None
ROOT = pathlib.Path(SPECPATH)  # directory containing this spec file
SITE = pathlib.Path(__import__("sys").exec_prefix) / "Lib" / "site-packages"
# audio-separator loads these JSON catalogs from its package dir at runtime
AS_PKG = pathlib.Path(__import__("audio_separator").__file__).parent
# per-user site also holds audio-separator when installed with --user
import site as _site

_USER_SITE = [pathlib.Path(p) for p in _site.getusersitepackages() if isinstance(p, str)]
_AS_DIST = None
for _base in [pathlib.Path(__import__("sys").prefix) / "Lib" / "site-packages",
              pathlib.Path(__import__("sys").exec_prefix) / "Lib" / "site-packages",
              *_USER_SITE]:
    _cand = _base / "audio_separator-0.47.0.dist-info"
    if _cand.exists():
        _AS_DIST = _cand
        break

import shutil as _shutil
# Bundle ffmpeg.exe into the exe so end-user machines need no PATH setup.
# Build machine resolves it via PATH; falls back to the WinGet Gyan package dir.
_FFMPEG_CANDIDATES = [p for p in [(_shutil.which("ffmpeg") or "")] if p]
_FFMPEG_CANDIDATES += list(pathlib.Path("tools").glob("ffmpeg*.exe"))
try:
    _FFMPEG_CANDIDATES += sorted(pathlib.Path.home().glob(
        "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_*/ffmpeg-*-full_build/bin/ffmpeg.exe"))
except Exception:
    pass
def _real(p):
    try:
        r = pathlib.Path(str(p)).resolve()
        return str(r) if r.is_file() else None
    except Exception:
        return None
FFMPEG_EXE = next((r for r in (_real(p) for p in _FFMPEG_CANDIDATES) if r), None)


a = Analysis(
    ["split_gui.py"],
    pathex=[str(ROOT)],
    binaries=[(FFMPEG_EXE, ".")] if FFMPEG_EXE else [],
    datas=[
        (str(ROOT / "web"), "web"),
        (str(ROOT / "README.md"), "."),
        # whole audio-separator package dir: models.json, model-data.json,
        # ensemble_presets.json, configs — resolved via importlib.resources
        (str(AS_PKG), "audio_separator"),
    ] + ([(str(_AS_DIST), "audio_separator-0.47.0.dist-info")] if _AS_DIST else []),
    hiddenimports=[
        "split", "split.engine", "split.models",
        "split.cli", "split.server",
        "audio_separator", "audio_separator.separator",
        "demucs", "demucs.separate", "demucs.hdemucs", "demucs.hdemucs_mmi",
        "demucs.htdemucs", "demucs.pretrained",
        "librosa", "soundfile", "resampy", "samplerate",
        "einops", "rotary_embedding_torch", "beartype",
        "onnx", "onnxruntime", "onnx2torch",
        "uvicorn", "uvicorn.logging", "uvicorn.loops.auto",
        "fastapi", "starlette", "multipart", "aiofiles",
        "torch", "torchaudio", "torchvision",
        "scipy", "sklearn", "pydub", "audioread", "ml_collections",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter", "notebook", "jupyter", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Split",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX breaks torch DLLs
    console=True,  # keep console: shows URL + first-run model download progress
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Split",
)
