"""Read a file from the ethics folder, by path relative to that folder.

The folder lives outside this repository and its location is **not** recorded here -- set
`TATP_ETHICS_DIR` to it. The argument is always relative to that root, which is what keeps an
outside path out of the command: `.claude/hooks/check_bash.py` resolves every path token in a
Bash command and refuses any that lands outside the repository, so a tool taking the real path
as an argument could never be invoked.

The `Read` tool handles text and PDFs directly once the folder is added as a working directory.
This exists for the two things it cannot do: listing the folder, and .docx.

    export TATP_ETHICS_DIR="/path/to/.../Task 1.2/ethics"

    python tools/read_ethics.py --list
    python tools/read_ethics.py Bilaga1_Forskningsplan_V2.docx
    python tools/read_ethics.py support_documents/article_summaries.md --grep anchor
"""

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def ethics_root() -> Path:
    """The folder location comes from the environment, never from this repository."""
    raw = os.environ.get("TATP_ETHICS_DIR")
    if not raw:
        sys.exit(
            "TATP_ETHICS_DIR is not set. Point it at the ethics folder:\n"
            '    export TATP_ETHICS_DIR="/path/to/Task 1.2/ethics"\n'
            "The path is deliberately not stored in this repository."
        )
    root = Path(raw).expanduser()
    assert root.is_dir(), f"TATP_ETHICS_DIR is not a directory: {root}"
    return root


def docx_text(path: Path) -> str:
    """Paragraph text of a .docx, one paragraph per line. Stdlib only."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    lines = []
    for para in root.iter(f"{W}p"):
        text = "".join(node.text or "" for node in para.iter(f"{W}t"))
        if text.strip():
            lines.append(text)
    return "\n".join(lines)


parser = argparse.ArgumentParser()
parser.add_argument("name", nargs="?", help="path relative to the ethics folder")
parser.add_argument("--list", action="store_true", help="list the folder instead of reading")
parser.add_argument("--grep", help="print only matching lines, with context")
parser.add_argument("--context", type=int, default=2)
args = parser.parse_args()

root = ethics_root()

if args.list:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            print(f"{path.stat().st_size:>10}  {path.relative_to(root)}")
    sys.exit(0)

if not args.name:
    parser.error("give a file name, or --list")

target = root / args.name
assert target.is_file(), f"not a file: {target}"

text = docx_text(target) if target.suffix == ".docx" else target.read_text(encoding="utf-8")
lines = text.split("\n")

if args.grep is None:
    print(text)
else:
    pattern = re.compile(args.grep, re.IGNORECASE)
    hits = [i for i, line in enumerate(lines) if pattern.search(line)]
    assert hits, f"no match for {args.grep!r} in {args.name}"
    shown = set()
    for i in hits:
        for j in range(max(0, i - args.context), min(len(lines), i + args.context + 1)):
            if j not in shown:
                shown.add(j)
                print(f"{j + 1}: {lines[j]}")
        print("--")
