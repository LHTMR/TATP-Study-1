# fonts

The fonts every screen uses, installed at startup by `tatp/ui/application.py` and named in
`config/hardware.yaml` under `screens:`. They are committed rather than taken from the platform
so the dev machine, the lab PC and the headless test run all draw the same letters.
`tests/test_application.py` fails if any character in the configured text has no glyph here.

**Roboto**, the study font (S, 23 Sep 2026). SIL Open Font License 1.1, which permits
redistribution; the licence is `Roboto/OFL.txt`. Source:
https://fonts.google.com/specimen/Roboto, downloaded by S. `Roboto/` is the Google Fonts download
as unzipped; only `static/Roboto-Regular.ttf` and `static/Roboto-Bold.ttf` are installed and
committed.

Chosen from a side-by-side render of Source Sans 3, Atkinson Hyperlegible, Roboto, IBM Plex Sans
and Noto Sans against the approved Mac screens. Atkinson Hyperlegible was chosen first and
rejected as too wide-looking. Roboto sets text at the same width but reads closest to the
system font the screens were first approved in.

**DejaVu Sans**, fallback only (S, 23 Sep 2026). Roboto has no ▶, the confirm symbol, which the
participant text uses inline, so Qt would draw it from whatever the machine had -- and
headless, from nothing, as an empty box. Qt consults DejaVu only for characters Roboto lacks.
Bitstream Vera licence with DejaVu's changes in the public domain, which permits
redistribution; the licence is `DejaVu_Sans/LICENSE`. Copied from conda-forge's
`font-ttf-dejavu-sans-mono` 2.37, which ships the proportional face alongside the mono one.
