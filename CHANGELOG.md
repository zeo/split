# changelog

dates are release-tag dates.

## [Unreleased]

### app
- new app icon: a brushed steel note on a steel tile
- the update check asks whichever installed rot installer owns Split, so an older shared installer no longer hides updates
- checks for updates through the rot installer and offers them in the status bar; installing closes Split, hands over to the installer and reopens it
- add a whole folder with the picker under the drop area or by opening Split with it; every audio and video file inside is added, up to 500 at a time
- each job keeps the original mix at the same trim as its stems; Original (O) switches between the two for an A/B
- drag across the time ruler to loop a stretch; L turns the loop on and off, Shift-click clears it
- Process on a lane sends that stem to another task, so a vocal can go straight into de-reverb
- Run again stages the same file with the current settings
- Copy details puts a failed job's error, setup and traceback on the clipboard
- the models sheet finds checkpoints nothing uses anymore and removes them in one go
- Clear finished empties the queue history
- `#loop=` in the url opens a session with a loop set

### engine
- a model that runs out of GPU memory retries with shorter chunks before giving up, and the session notes it
- jobs and downloads check free disk space first and fail with the space they need
- downloads retry dropped connections and server errors, resuming where they stopped
- while one job runs, the weights for the next queued job download in the background
- a checkpoint that fails to load reports itself instead of an internal error

### command line
- `separate` takes folders as well as files

### packaging
- Python 3.14 is out of range until diffq ships wheels for it

## [0.3.0] - 2026-10-14

A rewrite. The old build could not run its band tasks once frozen, and its models were a year behind.

### models
- vocals now default to unwa's Leap Xe, with Ultra averaging Leap Xe, anvuew's ft1 and becruily's Deux
- new Instrumental task tuned for the backing track: Leap instrumental, or Leap, becruily and Fv7z averaged
- karaoke uses the anvuew BS-RoFormer model, or anvuew plus frazer/becruily averaged
- 4 and 6 stems use BS-RoFormer SW; HT Demucs stays as the fast 4-stem option and now runs in-process
- the drum kit first pulls drums out with SW, then splits them with the 5-stem DrumSep, instead of feeding the full mix to DrumSep
- cleanup is three tasks (de-reverb, denoise, crowd) with an option to isolate the vocal first
- every weight file is pinned by URL, size and SHA-256 and downloads with resume and progress

### engine
- separation runs in its own process: one job at a time, cancel frees the GPU, a crash fails the job instead of the app
- stems now sum back to the mix; audio-separator's per-stem peak normalization is off
- output keeps the source's sample rate and channel count, at 24-bit for WAV and FLAC
- when any stem would clip, every stem gets the same small trim, so none clips and they still sum to the mix; the session shows the trim
- RoFormer inference is 2.5x to 3.5x faster than float32 on an RTX 4070 Ti; vocal stems match the float32 output to 48 to 53 dB SNR
- GPUs without kernels in the bundled torch build fall back to the CPU with a note instead of failing
- jobs persist on disk and survive a restart; finished jobs are kept for 7 days, up to 40

### app
- native window instead of a console plus browser tab, with its own title bar, drag and drop, file and folder pickers, export and show-in-Explorer; moving and resizing still go through Windows, so snap works
- a second launch focuses the running window and hands it the files
- arrangement view: one lane per stem with solo, mute, gain, an LED meter and save, a time ruler, and played audio lit while the rest stays dim, all on one sample clock
- queue with live progress, time left, cancel, retry and remove
- models sheet with license, source, size and download state for every checkpoint
- MK II, the new house style: lettered settings modules, a spec plate with the published score and download size, and a wired signal path for the chosen task; the earlier graphite and brass finish stays under Look as Brass
- `#job=`, `#task=`, `#style=` and `#theme=` in the url open a view directly
- the local API refuses other hosts and requires a per-launch token for anything that writes

### packaging
- data lives in `%LOCALAPPDATA%\Split`; weights from older builds move there on first launch
- Windows builds bundle a pinned FFmpeg 9.0.2 and ship through the rot installer as resumable parts
