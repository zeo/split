# Third-party notices

Split's own code is dual-licensed under MIT or Apache-2.0. The Windows build also bundles other projects' code, and the app downloads model weights it does not own. Both are listed here.

## Model weights

None of these files ship with Split. Each one downloads from the host below the first time a task needs it, and its SHA-256 is checked against the value pinned in `split/catalog.py`. The authors' terms apply to the weights and arguably to what you make with them. Where no license is stated, assume personal, non-commercial use.

| Model | Author | License | Source |
|---|---|---|---|
| Resurrection vocals | unwa | not stated | https://huggingface.co/pcunwa/BS-Roformer-Resurrection |
| Resurrection instrumental | unwa | not stated | https://huggingface.co/pcunwa/BS-Roformer-Resurrection |
| Leap Xe vocals | unwa | not stated | https://huggingface.co/pcunwa/BS-Roformer-Leap |
| Leap instrumental | unwa | not stated | https://huggingface.co/pcunwa/BS-Roformer-Leap |
| BS-RoFormer ft1 | anvuew | GPL-3.0 | https://huggingface.co/anvuew/BS-RoFormer |
| Deux | becruily | CC-BY-NC-4.0 | https://huggingface.co/becruily/mel-band-roformer-deux |
| Instrumental | becruily | not stated | https://huggingface.co/becruily/mel-band-roformer-instrumental |
| Instrumental Fv7z | Gabox | not stated | https://huggingface.co/GaboxR67/MelBandRoformers |
| Karaoke | anvuew | GPL-3.0 | https://huggingface.co/anvuew/karaoke_bs_roformer |
| Karaoke (frazer) | frazer and becruily | not stated | https://huggingface.co/becruily/bs-roformer-karaoke |
| Karaoke IS | Gabox | not stated | https://huggingface.co/GaboxR67/MelBandRoformers |
| BS-RoFormer SW | unknown | unknown | https://github.com/nomadkaraoke/python-audio-separator |
| HT Demucs | Alexandre Défossez | MIT | https://github.com/adefossez/demucs |
| DrumSep 5-stem | aufr33 and jarredou | not stated | https://huggingface.co/noblebarkrr/mvsepless_resources |
| De-reverb | anvuew | GPL-3.0 | https://huggingface.co/anvuew/dereverb_bs_roformer |
| De-reverb, less aggressive | anvuew | GPL-3.0 | https://huggingface.co/anvuew/dereverb_mel_band_roformer |
| Denoise, Denoise aggressive | aufr33 | not stated | https://github.com/nomadkaraoke/python-audio-separator |
| Crowd removal | aufr33 and viperx | not stated | https://github.com/nomadkaraoke/python-audio-separator |

BS-RoFormer SW is reported to be extracted from Apple Logic Pro. Its original upload was taken down, and the copy Split downloads is the one audio-separator mirrors. DrumSep 5-stem is likewise a community mirror of a removed upload. Both are pinned by checksum so a swapped file is refused.

## Bundled in the Windows build

| Component | Version | License | Source |
|---|---|---|---|
| FFmpeg (Gyan essentials build) | 9.0.2 | GPL-3.0 | https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2, source at https://ffmpeg.org |
| PyTorch with CUDA 13.0 runtime | 2.13.0 | BSD-3-Clause and others; CUDA libraries under the NVIDIA CUDA EULA | https://github.com/pytorch/pytorch |
| audio-separator | 0.47.0 | MIT | https://github.com/nomadkaraoke/python-audio-separator |
| diffq-fixed | 0.2.4 | CC-BY-NC-4.0 | https://pypi.org/project/diffq-fixed |
| pywebview | 6.2.1 | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| pythonnet | 3.2.1 | MIT | https://github.com/pythonnet/pythonnet |
| FastAPI | 0.143.0 | MIT | https://github.com/fastapi/fastapi |
| Starlette | 1.8.0 | BSD-3-Clause | https://github.com/encode/starlette |
| Uvicorn | 0.54.0 | BSD-3-Clause | https://github.com/encode/uvicorn |
| NumPy, SciPy, scikit-learn | see build | BSD-3-Clause | https://numpy.org, https://scipy.org, https://scikit-learn.org |
| librosa | 1.0.0 | ISC | https://github.com/librosa/librosa |
| numba, llvmlite | 0.68.0, 0.50.0 | BSD-2-Clause | https://numba.pydata.org |
| soundfile and libsndfile | 0.14.0 | BSD-3-Clause, LGPL-2.1 | https://github.com/bastibe/python-soundfile |
| soxr | 1.1.0 | LGPL-2.1-or-later | https://github.com/dofuuz/python-soxr |
| ONNX Runtime | 1.31.0 | MIT | https://github.com/microsoft/onnxruntime |
| Atkinson Hyperlegible Next and Mono | variable fonts from google/fonts | OFL-1.1 | https://github.com/google/fonts/tree/main/ofl |
| Commit Mono | V143 | OFL-1.1 | https://github.com/eigilnikolajsen/commit-mono |
| Hanken Grotesk | variable | OFL-1.1 | https://github.com/marcologous/hanken-grotesk |

`diffq-fixed` comes in through audio-separator's Demucs code and carries a non-commercial license, which makes the packaged Windows build non-commercial as a whole. The full license texts of bundled components sit in `_internal/licenses` and next to each package inside `_internal`.
