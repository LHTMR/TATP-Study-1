#!/usr/bin/env python
"""Check that every session file in the data folder has an identical copy in 01_raw.

For S, after the experimenter's upload (SOP.md 14.2, docs/LOG.md N4.1). Every data file in the
local data folder is looked for, by name, in the study's `01_raw` folder on the LiU network
storage and compared by SHA-256, so a copy that is the right size but wrong inside is caught
too. Both folders are only read. The lab PC keeps every session, so a clean run means every
session run on it is safely uploaded.

A file in `01_raw` with no local copy is not a problem -- it may come from another PC -- and is
not reported.

Exit status 0 if every file matched, 1 if any is missing or different.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tatp import config as cfg  # noqa: E402  -- after the path insert above
from tatp.preflight import data_folder_for  # noqa: E402

# The software's data files (tatp/datafiles.py FILENAME_TEMPLATE). The lock file is not one.
DATA_FILE_GLOB = "TATP1_*_P{code}_S{number}_*.csv"
CHUNK_BYTES = 1 << 20

OK = "ok"
MISSING = "missing"
DIFFERENT = "different"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=None,
                        help="the local data folder. Defaults to hardware.yaml data.folder.")
    parser.add_argument("--raw", type=Path, default=None,
                        help="the 01_raw folder. Defaults to hardware.yaml data.upload_folder; "
                             "on a Mac, give the mounted path, e.g. /Volumes/tatp/01_raw.")
    parser.add_argument("--participant", default=None, help="only this participant code")
    parser.add_argument("--session", type=int, default=None, help="only this session number")
    return parser.parse_args(argv)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def data_files(folder: Path, participant: str | None, session: int | None) -> list[Path]:
    code = "*" if participant is None else participant
    number = "*" if session is None else str(session)
    pattern = DATA_FILE_GLOB.format(code=code, number=number)
    return sorted(p for p in folder.glob(pattern) if p.is_file())


def compare(local: list[Path], raw: Path) -> list[tuple[Path, str]]:
    results = []
    for path in local:
        copy = raw / path.name
        if not copy.is_file():
            results.append((path, MISSING))
        elif sha256_of(copy) != sha256_of(path):
            results.append((path, DIFFERENT))
        else:
            results.append((path, OK))
    return results


def report(results: list[tuple[Path, str]], data: Path, raw: Path) -> list[str]:
    counts = {state: sum(1 for _, s in results if s == state)
              for state in (OK, MISSING, DIFFERENT)}
    lines = [f"Data folder: {data}", f"01_raw:      {raw}", ""]
    lines += [f"  {state.upper():9} {path.name}" for path, state in results if state != OK]
    if counts[MISSING] or counts[DIFFERENT]:
        lines.append("")
    lines.append(f"{len(results)} files checked: {counts[OK]} identical, "
                 f"{counts[MISSING]} missing, {counts[DIFFERENT]} different.")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = cfg.load("en", "en")
    data = args.data if args.data is not None else data_folder_for(config)
    raw = args.raw if args.raw is not None else Path(config.hardware["data"]["upload_folder"])
    # Fail fast: an unmounted share would otherwise report every file as missing.
    assert data.is_dir(), f"the data folder {data} does not exist"
    assert raw.is_dir(), f"{raw} cannot be reached -- is the network storage connected?"

    local = data_files(data, args.participant, args.session)
    assert local, f"no data files in {data} for these filters"
    results = compare(local, raw)
    for line in report(results, data, raw):
        print(line)
    return 0 if all(state == OK for _, state in results) else 1


if __name__ == "__main__":
    sys.exit(main())
