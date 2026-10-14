# changelog

dates are release-tag dates.

## [Unreleased]

## [0.3.0] - 2026-10-15

A rewrite. The old build could not run its band tasks once frozen, and its models were a year behind.

### models
- vocals now default to unwa's Leap Xe, with Ultra averaging Leap Xe, anvuew's ft1 and becruily's Deux
- new Instrumental task tuned for the backing track: Leap instrumental, or Leap, becruily and Fv7z averaged
- karaoke uses the anvuew BS-RoFormer model, or anvuew plus frazer/becruily averaged
- 4 and 6 stems use BS-RoFormer SW; HT Demucs stays as the fast 4-stem option
- the drum kit first pulls drums out with SW, then splits them with the 5-stem DrumSep, instead of feeding the full mix to DrumSep
- cleanup is three tasks (de-reverb, denoise, crowd) with an option to isolate the vocal first
- every weight file is pinned by URL, size and SHA-256 and downloads with resume and progress

### app
- native window with its own title bar: drag to move, snap or shake, double-click to maximize, resize from any edge
- arrangement view: one lane per stem with solo, mute, gain, a level meter and save, a time ruler, and played audio lit while the rest stays dim, all on one sample clock
- each job keeps the original mix; Original (O) switches to it for an A/B against the stems
- drag across the time ruler to loop a stretch; L turns the loop on and off
- Process on a lane sends that stem to another task, so a vocal can go straight into de-reverb
- add a whole folder at once, up to 500 files; a second launch hands its files to the running window
- queue with live progress, time left, cancel, retry, run again and clear finished
- models sheet with license, source, size and download state for every checkpoint, and a button to remove leftover files from older versions
- a failed job can copy its error, setup and log for a bug report
- light and dark themes
- checks for updates through the rot installer and installs them when you ask

### engine
- separation runs in its own process: one job at a time, cancel frees the GPU, a crash fails the job instead of the app
- stems sum back to the mix, keep the source's sample rate and channel count, and come out at 24-bit for WAV and FLAC
- when any stem would clip, every stem gets the same small trim, so none clips and they still sum to the mix
- RoFormer inference is 2.5x to 3.5x faster than float32 on an RTX 4070 Ti
- a model that runs out of GPU memory retries on shorter chunks before giving up
- jobs and downloads check free disk space first; downloads retry dropped connections and resume
- while one job runs, the next job's models download in the background
- GPUs too old for the bundled CUDA build fall back to the CPU with a note instead of failing

### command line
- `split separate` takes files or folders, `--json` prints progress for scripts

### packaging
- installs through the rot installer as signed, resumable parts, with a Start menu entry and an uninstaller
- bundles a pinned FFmpeg 9.0.2
- data lives in `%LOCALAPPDATA%\Split`; weights from older builds move there on first launch
