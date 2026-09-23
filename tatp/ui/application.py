"""The Qt application, with the study's fonts installed.

Every screen takes its font from the application, so installing them here is what makes the
lab PC, the dev machine and the headless test run draw the same letters. Left to the platform
they did not: the approved screenshots were the Mac's system font, a real session on the lab PC
would have been Segoe UI, and headless Windows reads fonts from an empty folder under Qt and
drew every character as a box.

Everything that makes a window gets its application from here -- the session, the tools and
the test suite -- so a screen measured by a test is a screen the lab PC shows.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication

from tatp.config import REPO_ROOT


def application(hardware: dict) -> QApplication:
    """The running application, created if need be, with the configured fonts in use.

    The first family is the study font. The rest are consulted, in order, only for a character
    the first does not have; naming them is what stops Qt reaching for whatever the machine has.
    """
    app = QApplication.instance() or QApplication(sys.argv[:1])
    families = list(hardware["screens"]["font_families"])
    if app.font().families() == families:
        return app

    installed = set()
    for relative in hardware["screens"]["font_files"]:
        font_id = QFontDatabase.addApplicationFont(str(REPO_ROOT / relative))
        assert font_id != -1, f"Qt could not load the font file {relative}"
        installed.update(QFontDatabase.applicationFontFamilies(font_id))
    missing = set(families) - installed
    assert not missing, f"no font file supplies {sorted(missing)}; the files hold {installed}"
    font = QFont()
    font.setFamilies(families)
    app.setFont(font)

    # Fail fast: Qt substitutes a fallback for a family it cannot match and says nothing,
    # which is exactly how the platform font went unnoticed.
    in_use = QFontInfo(app.font()).family()
    assert in_use == families[0], f"asked for {families[0]!r}, Qt is drawing {in_use!r}"
    # Emphasised participant text and the experimenter banners are bold. Without a bold file
    # Qt would thicken the regular one, which draws worse and is again silent.
    styles = QFontDatabase.styles(families[0])
    assert "Bold" in styles, f"{families[0]!r} has no bold weight installed, only {styles}"
    return app
