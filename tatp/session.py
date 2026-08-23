"""Session state, provenance and logging. SPEC.md 7.4, 14, 15, 16.

A `Session` owns the things every phase needs and nothing a phase does: the clock, the data
files, the garment, the allocation and the log. Phases are built on top of it.

Blinding (SPEC.md 16): the condition is read from the allocation, written to the data files and
returned by `Session.condition` for the software's own use. It is never put into anything shown
on either screen. `experimenter_view()` exists so that there is one obvious place where what the
experimenter may see is decided, and a test asserts the condition is not in it.
"""

from __future__ import annotations

import random
from pathlib import Path

from tatp import allocation as alloc
from tatp import provenance
from tatp import schedule as sched
from tatp.clock import Clock
from tatp.config import REPO_ROOT, Config, hash_files
from tatp.datafiles import DataFileCollection
from tatp.garment.base import GarmentController, Limits
from tatp.garment.mock import MockGarment
from tatp.garment.patterns import load_folder

# The controlled vocabulary of the `phase` column, from the Conventions section of
# docs/DATA_SCHEMA.md. A test asserts this tuple still matches the document.
PHASES = (
    "setup",
    "touch_calibration",
    "pre_sensitisation",
    "sensitisation",
    "capsaicin",
    "post_sensitisation",
    "intervention",
    "rekindle",
    "post_intervention",
    "session_end",
)

ORIGINS = ("software", "experimenter", "participant")
SEVERITIES = ("info", "warning", "error")

DRIVERS: dict[str, type[GarmentController]] = {"mock": MockGarment}


class SessionError(Exception):
    """The session cannot start or continue as asked. Fatal."""


class Session:
    """One participant-session. Created by the launcher, driven by the phases."""

    def __init__(
        self,
        config: Config,
        participant_code: str,
        session_number: int,
        experimenter_initials: str,
        pattern_folder: Path,
        clock: Clock | None = None,
        rng_seed: int | None = None,
        resumed_from: str = "",
    ):
        self.config = config
        self.clock = clock or Clock()
        self.participant_code = participant_code
        self.session_number = session_number
        self.experimenter_initials = experimenter_initials
        self.resumed_from = resumed_from
        self.session_start_iso = self.clock.wall_iso()

        # Recorded whether it was given or drawn, so a session is always reproducible from its
        # own data file (SPEC.md 14.2). Never defaulted to a constant, which would make every
        # session's randomisation identical.
        self.rng_seed = random.SystemRandom().randrange(2**31) if rng_seed is None else rng_seed
        self.rng = random.Random(self.rng_seed)

        self.allocation_path = Path(config.study1["design"]["allocation_file"])
        if not self.allocation_path.is_absolute():
            self.allocation_path = REPO_ROOT / self.allocation_path
        design = config.study1["design"]
        self.allocation = alloc.load(
            self.allocation_path, design["conditions"], design["limbs"], design["n_sessions"]
        )
        assignment = self.allocation.get(participant_code, session_number)
        # Blinding (SPEC.md 16): recorded, never displayed.
        self._condition = assignment.condition
        self.limb = assignment.limb

        self.pattern_folder = pattern_folder
        self.patterns = load_folder(pattern_folder)

        self.schedule = sched.generate(config.schedule)

        self.phase = PHASES[0]
        self.block_index: int | None = None
        self._block: sched.Block | None = None
        self._block_start_s: float | None = None
        self.aborted_reason = ""
        self.closed = False

        # SPEC.md 11.1. Off by default; a session run with it on shows the experimenter the
        # participant's ratings and is recorded as unblinded in that respect.
        self.fit_preview_enabled = config.study1["fit_preview"]["enabled"]
        self.fit_preview_reruns = 0

        # SPEC.md 10.7. Set by the masking check, which is Milestone 4 -- the participant picks
        # their own noise level, so there is no configured value to default these to. None
        # means the check has not run, which is distinguishable from it having run and failed.
        self.white_noise_level_dbfs: float | None = None
        self.masking_confirmed: bool | None = None
        self.masking_attempts = 0

        self.data_folder = Path(config.hardware["data"]["folder"])
        if not self.data_folder.is_absolute():
            self.data_folder = REPO_ROOT / self.data_folder
        self.cloud_sync_warning = provenance.cloud_sync_warning(
            self.data_folder, config.hardware["data"]["cloud_sync_markers"]
        )

        self.files = DataFileCollection(
            self.data_folder,
            participant_code,
            session_number,
            self.clock.filename_stamp(),
        )

        driver_name = config.hardware["garment"]["driver"]
        if driver_name not in DRIVERS:
            raise SessionError(
                f"garment.driver is {driver_name!r}. Available drivers: {sorted(DRIVERS)}."
            )
        self.garment = DRIVERS[driver_name](
            Limits.from_config(config.hardware), self.clock, on_command=self._record_garment
        )

    # -- blinding ----------------------------------------------------------------------

    @property
    def condition(self) -> str:
        """For the software's own use only. Never put this on a screen (SPEC.md 16)."""
        return self._condition

    def experimenter_view(self) -> dict:
        """Everything the experimenter screen may show about the session.

        One place, so that "the condition is hidden from the experimenter screen as well"
        (CLAUDE.md) is a property of a function with a test on it, rather than a habit.
        """
        return {
            "participant_code": self.participant_code,
            "session_number": self.session_number,
            "limb": self.limb,
            "experimenter_initials": self.experimenter_initials,
            "phase": self.phase,
            "block_index": self.block_index,
            "elapsed_s": self.clock.elapsed_s(),
            "t_session_s": self.clock.t_session_s(),
            "garment_connected": self.garment.connected,
            "garment_driver": self.garment.driver_name,
            "unresolved_open_items": [str(item) for item in self.config.unresolved],
            "placeholder_text": self.config.has_placeholder_text(),
            "reduced_capability_device": not self.garment.per_channel_pressure,
            "fit_preview_enabled": self.fit_preview_enabled,
        }

    # -- logging -----------------------------------------------------------------------

    def log(
        self,
        event: str,
        origin: str = "software",
        severity: str = "info",
        detail: str = "",
    ) -> None:
        """One row in the `log` table. Every event carries its origin (SPEC.md 13)."""
        if origin not in ORIGINS:
            raise SessionError(f"origin {origin!r} is not one of {list(ORIGINS)}")
        if severity not in SEVERITIES:
            raise SessionError(f"severity {severity!r} is not one of {list(SEVERITIES)}")
        self.files.write(
            "log",
            timestamp_iso=self.clock.wall_iso(),
            t_session_s=self.clock.t_session_s(),
            phase=self.phase,
            block_index=self.block_index,
            event=event,
            origin=origin,
            severity=severity,
            detail=detail,
        )

    def set_phase(self, phase: str) -> None:
        if phase not in PHASES:
            raise SessionError(f"phase {phase!r} is not one of {list(PHASES)}")
        previous, self.phase = self.phase, phase
        self.log("phase_changed", detail=f"{previous} -> {phase}")

    def start_sensitisation(self) -> None:
        """Session t=0 (SPEC.md 7.4). Everything scheduled is timed from here."""
        self.set_phase("sensitisation")
        self.clock.start_session()
        self.log("sensitisation_started")

    # -- blocks ------------------------------------------------------------------------

    def start_block(self, block: sched.Block) -> None:
        """The experimenter has launched a block (SPEC.md 7.4).

        Nothing here decides *when*: the software times and counts down, the experimenter
        launches, and no block is ever skipped automatically. What is recorded is the planned
        offset alongside the moment it actually began, so the drift is in the data rather than
        corrected away.
        """
        if self._block is not None:
            raise SessionError(
                f"block {self._block.index} is still open; end it before starting "
                f"block {block.index}"
            )
        if not self.clock.session_started:
            raise SessionError(
                f"block {block.index} was started before session t=0. Blocks are offsets from "
                f"the start of sensitisation, so there is no honest actual-start to record."
            )
        self._block = block
        self._block_start_s = self.clock.t_session_s()
        self.block_index = block.index
        started_min = self._block_start_s / 60.0
        self.log(
            "block_started",
            origin="experimenter",
            detail=f"{block.type}; planned {block.planned_offset_min:g} min, "
            f"started {started_min:.2f} min, "
            f"{started_min - block.planned_offset_min:+.2f} min against plan",
        )

    def end_block(self) -> None:
        """Close the open block, recording how long it actually took."""
        if self._block is None:
            raise SessionError("no block is open")
        block, start_s = self._block, self._block_start_s
        actual_min = (self.clock.t_session_s() - start_s) / 60.0
        planned = (
            "unset" if block.expected_duration_min is None
            else f"{block.expected_duration_min:g} min"
        )
        self.log(
            "block_ended",
            detail=f"{block.type}; took {actual_min:.2f} min, expected {planned}",
        )
        self._block = None
        self._block_start_s = None
        self.block_index = None

    def _record_garment(self, command: dict) -> None:
        """The garment reports what it did; the session adds the phase and the block."""
        self.files.write(
            "garment",
            timestamp_iso=self.clock.wall_iso(),
            t_session_s=self.clock.t_session_s(),
            phase=self.phase,
            block_index=self.block_index,
            clamped=bool(command.pop("clamped", False)),
            **command,
        )

    # -- lifecycle ---------------------------------------------------------------------

    def start(self, room_temperature_c: float | None = None,
              relative_humidity_pct: float | None = None) -> None:
        """Write the session provenance and connect the garment."""
        self.garment.connect()
        self.files.write_session(self._provenance(room_temperature_c, relative_humidity_pct))
        self.log("session_started", detail=f"software {provenance.base()['software_version']}")
        if self.cloud_sync_warning:
            self.log("cloud_sync_folder", severity="warning", detail=self.cloud_sync_warning)
        for item in self.config.unresolved:
            self.log("unresolved_open_item", severity="warning", detail=str(item))
        # SPEC.md 7.3: the schedule warns and never blocks, so the warnings have to be somewhere
        # a session can be audited from afterwards rather than only in the preview.
        for warning in self.schedule.warnings():
            self.log("schedule_warning", severity="warning", detail=warning)
        if self.config.has_placeholder_text():
            self.log(
                "placeholder_participant_text",
                severity="warning",
                detail="participant wording is not approved wording (open item L4)",
            )
        if not self.garment.per_channel_pressure:
            self.log(
                "reduced_capability_device",
                severity="warning",
                detail=f"{self.garment.driver_name} cannot set per-channel pressure "
                f"(SPEC.md 12.4)",
            )
        if self.fit_preview_enabled:
            self.log(
                "fit_preview_enabled",
                severity="warning",
                detail="the experimenter can see participant ratings; this session is not "
                "blind in the sense Bilaga 1 3.3 describes (SPEC.md 11.1)",
            )

    def close(self, abort_reason: str = "") -> None:
        """Stop the garment, write the closing provenance, and flush. Safe to call twice."""
        if self.closed:
            return
        # SPEC.md 7.4 wants an actual end for every block, which includes one the session was
        # aborted out of. Closed here rather than at each abort path so it cannot be forgotten.
        if self._block is not None:
            self.end_block()
        self.aborted_reason = abort_reason
        if self.garment.connected:
            self.garment.stop()
            self.garment.disconnect()
        self.set_phase("session_end")
        if abort_reason:
            self.log("session_aborted", severity="warning", detail=abort_reason)
        self.log("session_ended")
        self.files.write_session(
            {
                "sensitisation_start_iso": self.clock.sensitisation_start_iso or "",
                "session_end_iso": self.clock.wall_iso(),
                "abort_reason": abort_reason,
            }
        )
        self.files.close()
        self.closed = True

    # -- provenance --------------------------------------------------------------------

    def _earlier_experimenters(self) -> set[str]:
        """Initials recorded in this participant's earlier session files (SPEC.md 14.2)."""
        pattern = f"TATP1_*_P{self.participant_code}_S*_session.csv"
        found = set()
        for path in sorted(self.data_folder.glob(pattern)):
            if path == self.files.path("session"):
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition(",")
                if key == "experimenter_initials" and value:
                    found.add(value)
        return found

    def _provenance(
        self, room_temperature_c: float | None, relative_humidity_pct: float | None
    ) -> dict:
        base = provenance.base()
        filaments = self.config.filaments["filaments"]
        capabilities = self.garment.capabilities()
        earlier = self._earlier_experimenters()
        return {
            **base,
            "participant_code": self.participant_code,
            "session_number": self.session_number,
            "condition": self._condition,
            "limb": self.limb,
            "experimenter_initials": self.experimenter_initials,
            "experimenter_changed": bool(earlier and self.experimenter_initials not in earlier),
            "participant_language": self.config.participant_language,
            "experimenter_language": self.config.experimenter_language,
            "rng_seed": self.rng_seed,
            "allocation_file": str(self.allocation_path),
            "allocation_sha256": hash_files([self.allocation_path]),
            "schedule_file": str(self.config.config_dir / "schedule.yaml"),
            "schedule_sha256": hash_files([self.config.config_dir / "schedule.yaml"]),
            "config_sha256": self.config.sha256,
            "pattern_folder": str(self.pattern_folder),
            "pattern_sha256": hash_files(
                sorted(p for p in self.pattern_folder.iterdir() if p.is_file())
            ),
            "pattern_names": ";".join(sorted(self.patterns)),
            "garment_driver": self.garment.driver_name,
            "garment_capabilities": ";".join(
                f"{k}={v}" for k, v in sorted(capabilities.items())
            ),
            "reduced_capability_device": not capabilities["per_channel_pressure"],
            # A session run with the preview on is not blind in the sense Bilaga 1 3.3
            # describes, so analysis must be able to tell it apart (SPEC.md 11.1).
            "fit_preview_enabled": self.fit_preview_enabled,
            "fit_preview_reruns": self.fit_preview_reruns,
            "filament_calibration_date": self.config.filaments.get("weighing_date") or "",
            "filaments_measured": all(f["force_measured_mn"] is not None for f in filaments),
            "slope_prior_vas_per_log10": self.config.study1["pinprick"][
                "slope_prior_vas_per_log10"
            ],
            "room_temperature_c": room_temperature_c,
            "relative_humidity_pct": relative_humidity_pct,
            # SPEC.md 10.7. The masking check fills these in setup and rewrites the row; they
            # are declared here so the column exists from the first session rather than
            # appearing when the procedure lands. Empty means the check has not run.
            "white_noise_level_dbfs": self.white_noise_level_dbfs,
            "masking_confirmed": self.masking_confirmed,
            "masking_attempts": self.masking_attempts,
            "data_folder": str(self.data_folder.resolve()),
            "cloud_sync_warning": self.cloud_sync_warning,
            "unresolved_open_items": ";".join(
                item.number for item in self.config.unresolved
            ),
            "resumed_from_session_file": self.resumed_from,
            "session_start_iso": self.session_start_iso,
        }
