# windows desktop build: dist/split/split.exe and the console split-cli.exe, sharing _internal/
# run through packaging/build.ps1, which fetches the pinned ffmpeg into build/ffmpeg first
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
FFMPEG = ROOT / "build" / "ffmpeg"

datas = [
    (str(ROOT / "web"), "web"),
    (str(ROOT / "assets" / "icon-1024.png"), "assets"),
    (str(ROOT / "assets" / "icon.ico"), "assets"),
    (str(ROOT / "LICENSE-MIT"), "licenses"),
    (str(ROOT / "LICENSE-APACHE"), "licenses"),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "licenses"),
    (str(FFMPEG / "LICENSE"), "licenses/ffmpeg"),
]
datas += collect_data_files("audio_separator", excludes=["**/__pycache__/**"])
datas += copy_metadata("audio-separator")
datas += collect_data_files("webview")

hiddenimports = [
    "split.engine",
    "audio_separator.separator.architectures.mdxc_separator",
    "audio_separator.separator.architectures.demucs_separator",
    *collect_submodules("audio_separator.separator.uvr_lib_v5.roformer"),
    *collect_submodules("audio_separator.separator.uvr_lib_v5.demucs"),
    *collect_submodules("audio_separator.separator.roformer"),
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]

excludes = [
    "audio_separator.separator.architectures.mdx_separator",
    "audio_separator.separator.architectures.vr_separator",
    "onnx",
    "onnx2torch",
    "torchvision",
    "tkinter",
    "matplotlib",
    "IPython",
    "pytest",
]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=[(str(FFMPEG / "ffmpeg.exe"), ".")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
cli = Analysis(
    [str(ROOT / "packaging" / "cli.py")],
    pathex=[str(ROOT)],
    hiddenimports=[name for name in hiddenimports if not name.startswith("webview")],
    excludes=[*excludes, "webview"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="split",
    icon=str(ROOT / "assets" / "icon.ico"),
    console=False,
    upx=False,
    disable_windowed_traceback=False,
)
cli_exe = EXE(
    PYZ(cli.pure),
    cli.scripts,
    [],
    exclude_binaries=True,
    name="split-cli",
    icon=str(ROOT / "assets" / "icon.ico"),
    console=True,
    upx=False,
)
# one COLLECT is how pyinstaller puts several onedir apps in one folder; shared files land once
coll = COLLECT(exe, a.binaries, a.datas, cli_exe, cli.binaries, cli.datas, name="split", upx=False)
