import multiprocessing

from split.cli import main

if __name__ == "__main__":
    # split-cli serve runs jobs in spawned workers, which re-enter this exe
    multiprocessing.freeze_support()
    raise SystemExit(main())
