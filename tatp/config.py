"""Configuration loading and validation.

SPEC.md 6: configuration is validated on load. A missing key, a wrong type, an out-of-range
value or a referenced file that does not exist stops the program with a message naming the
file, the key and the problem. A value that was supposed to be supplied never falls back to a
default.

SPEC.md 20: a value that is not yet known is a clearly-marked placeholder that warns at
startup. `config/open_items.yaml` is what makes that automatic rather than remembered.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

TEXT_FILES = {
    ("participant", "sv"): "text/participant_sv.yaml",
    ("participant", "en"): "text/participant_en.yaml",
    ("experimenter", "sv"): "text/experimenter_sv.yaml",
    ("experimenter", "en"): "text/experimenter_en.yaml",
}

# Text marked with this prefix is not approved wording and must not reach a participant
# unnoticed (open item L4).
PLACEHOLDER_PREFIX = "PLACEHOLDER"

# Validation metadata -- which keys must carry a real value, of what type, and the range
# outside which the value is certainly a mistake. These are not study parameters: the values
# themselves live in config/ (SPEC.md 4.2). Keys that are deliberately null because they are
# open items are absent from this table and are handled by open_items.yaml instead.
#
# (file, dotted path, type, minimum, maximum) -- None where unbounded. `[*]` in a path means
# "every element of this list".
NUMBER = (int, float)
SCHEMA: tuple[tuple[str, str, type | tuple[type, ...], float | None, float | None], ...] = (
    ("study1.yaml", "design.n_participants", int, 1, None),
    ("study1.yaml", "design.n_sessions", int, 1, None),
    ("study1.yaml", "design.conditions", list, None, None),
    ("study1.yaml", "design.limbs", list, None, None),
    ("study1.yaml", "design.allocation_file", str, None, None),
    ("study1.yaml", "vas.start_pct_after_left_press", NUMBER, 0, 100),
    ("study1.yaml", "vas.start_pct_after_right_press", NUMBER, 0, 100),
    ("study1.yaml", "vas.move_step_pct", NUMBER, 0, 100),
    ("study1.yaml", "vas.hold_repeat_delay_s", NUMBER, 0, None),
    ("study1.yaml", "vas.hold_repeat_interval_s", NUMBER, 0, None),
    ("study1.yaml", "vas.no_response_warning_s", NUMBER, 0, None),
    ("study1.yaml", "pinprick.target_vas_pct", NUMBER, 0, 100),
    ("study1.yaml", "pinprick.slope_prior_vas_per_log10", NUMBER, 0, None),
    ("study1.yaml", "pinprick.measure_repetitions", int, 1, None),
    ("study1.yaml", "pinprick.measure_n_levels", int, 1, None),
    ("study1.yaml", "pinprick.max_applications", int, 1, None),
    ("study1.yaml", "pinprick.start_filament_size_session1_pre_s", str, None, None),
    ("study1.yaml", "pinprick.expected_offset_steps_pre_to_post_s", NUMBER, None, None),
    ("study1.yaml", "pinprick.isi_min_s", NUMBER, 0, None),
    ("study1.yaml", "pinprick.isi_max_s", NUMBER, 0, None),
    ("study1.yaml", "pinprick.rating_cue_delay_s", NUMBER, 0, None),
    ("study1.yaml", "pinprick.short_protocol_n_trials", int, 1, None),
    ("study1.yaml", "pinprick.n_sites", int, 1, None),
    ("study1.yaml", "pinprick.ordinal_rho_min", NUMBER, -1, 1),
    ("study1.yaml", "brush.n_trials", int, 1, None),
    ("study1.yaml", "brush.n_sites", int, 1, None),
    ("study1.yaml", "mapping.n_paths", int, 1, None),
    ("study1.yaml", "mapping.step_size_mm", NUMBER, 0, None),
    ("study1.yaml", "mapping.step_interval_s", NUMBER, 0, None),
    ("study1.yaml", "mapping.max_steps", int, 1, None),
    ("study1.yaml", "mapping.distance_plausible_min_mm", NUMBER, 0, None),
    ("study1.yaml", "mapping.distance_plausible_max_mm", NUMBER, 0, None),
    ("study1.yaml", "touch_calibration.reference_channel", int, 1, None),
    ("study1.yaml", "touch_calibration.anchors_pct[*]", NUMBER, 0, 100),
    ("study1.yaml", "touch_calibration.adjustments_per_anchor", int, 1, None),
    ("study1.yaml", "touch_calibration.start_directions", list, None, None),
    ("study1.yaml", "touch_calibration.start_offset_fraction", NUMBER, 0, 1),
    ("study1.yaml", "touch_calibration.adjustment_timeout_s", NUMBER, 0, None),
    ("study1.yaml", "touch_calibration.min_exploration_kpa", NUMBER, 0, None),
    ("study1.yaml", "touch_calibration.comparison_hold_s", NUMBER, 0, None),
    ("study1.yaml", "touch_calibration.comparison_gap_s", NUMBER, 0, None),
    ("study1.yaml", "touch_calibration.catch_trial_fraction", NUMBER, 0, 1),
    ("study1.yaml", "touch_calibration.catch_felt_warn_fraction", NUMBER, 0, 1),
    ("study1.yaml", "touch_calibration.pleasantness_range_anchors[*]", NUMBER, 0, 100),
    ("study1.yaml", "touch_calibration.pleasantness_adjustments", int, 1, None),
    ("study1.yaml", "touch_calibration.sham_target_intensity_pct", NUMBER, 0, 100),
    ("study1.yaml", "touch_calibration.evenness_check", bool, None, None),
    ("study1.yaml", "patterns.condition_pattern", dict, None, None),
    ("study1.yaml", "patterns.preference_candidates", list, None, None),
    ("study1.yaml", "cues.warning_lead_s", NUMBER, 0, None),
    ("study1.yaml", "cues.warning_duration_s", NUMBER, 0, None),
    ("hardware.yaml", "garment.driver", str, None, None),
    ("hardware.yaml", "garment.connect_timeout_s", NUMBER, 0, None),
    ("hardware.yaml", "garment.pressure_max_kpa", NUMBER, 0, None),
    ("hardware.yaml", "garment.pressure_ceiling_kpa", NUMBER, 0, None),
    ("hardware.yaml", "garment.pressure_rate_max_kpa_s", NUMBER, 0, None),
    ("hardware.yaml", "adjustment.tap_max_duration_s", NUMBER, 0, None),
    ("hardware.yaml", "adjustment.tap_step_kpa", NUMBER, 0, None),
    ("hardware.yaml", "adjustment.hold_delay_s", NUMBER, 0, None),
    ("hardware.yaml", "adjustment.hold_rate_initial_kpa_s", NUMBER, 0, None),
    ("hardware.yaml", "adjustment.hold_rate_final_kpa_s", NUMBER, 0, None),
    ("hardware.yaml", "adjustment.hold_ramp_duration_s", NUMBER, 0, None),
    ("hardware.yaml", "adjustment.tick_interval_s", NUMBER, 0, None),
    ("hardware.yaml", "responder.keys.decrease", list, None, None),
    ("hardware.yaml", "responder.keys.increase", list, None, None),
    ("hardware.yaml", "responder.keys.confirm", list, None, None),
    ("hardware.yaml", "responder.keys.emergency_stop", list, None, None),
    ("hardware.yaml", "responder.ignore_keys", list, None, None),
    ("hardware.yaml", "screens.participant_fullscreen", bool, None, None),
    ("hardware.yaml", "audio.enabled", bool, None, None),
    ("hardware.yaml", "audio.sample_rate_hz", int, 1, None),
    ("hardware.yaml", "audio.white_noise_level_dbfs", NUMBER, None, 0),
    ("hardware.yaml", "audio.participant_cue_hz", NUMBER, 0, None),
    ("hardware.yaml", "audio.participant_cue_duration_s", NUMBER, 0, None),
    ("hardware.yaml", "audio.participant_cue_level_dbfs", NUMBER, None, 0),
    ("hardware.yaml", "audio.experimenter_alert_hz", NUMBER, 0, None),
    ("hardware.yaml", "audio.experimenter_alert_duration_s", NUMBER, 0, None),
    ("hardware.yaml", "audio.experimenter_alert_level_dbfs", NUMBER, None, 0),
    ("hardware.yaml", "data.folder", str, None, None),
    ("hardware.yaml", "data.cloud_sync_markers", list, None, None),
    ("schedule.yaml", "generate.n_pinprick_blocks", int, 0, None),
    ("schedule.yaml", "generate.n_touch_blocks", int, 0, None),
    ("schedule.yaml", "generate.intervention_duration_min", NUMBER, 0, None),
    ("schedule.yaml", "generate.intervention_start_offset_min", NUMBER, 0, None),
    ("schedule.yaml", "generate.rekindle_offset_min", NUMBER, 0, None),
    ("schedule.yaml", "generate.rekindle_duration_min", NUMBER, 0, None),
    ("schedule.yaml", "generate.capsaicin_start_offset_min", NUMBER, 0, None),
    ("schedule.yaml", "generate.capsaicin_duration_min", NUMBER, 0, None),
    ("schedule.yaml", "generate.sensitisation_duration_min", NUMBER, 0, None),
    ("schedule.yaml", "generate.first_block_type", str, None, None),
    ("schedule.yaml", "overrides", list, None, None),
    ("schedule.yaml", "validation.max_session_duration_min", NUMBER, 0, None),
    ("schedule.yaml", "validation.overdue_alert_margin_s", NUMBER, 0, None),
    ("schedule.yaml", "validation.due_alert_lead_s", NUMBER, 0, None),
    ("schedule.yaml", "validation.equal_spacing_tolerance_s", NUMBER, 0, None),
    ("filaments.yaml", "filaments[*].size", str, None, None),
    ("filaments.yaml", "filaments[*].force_manual_mn", NUMBER, 0, None),
    ("filaments.yaml", "filaments[*].force_nominal_mn", NUMBER, 0, None),
)

# Files whose existence is asserted because another config value names them.
REFERENCED_FILES = (("study1.yaml", "design.allocation_file"),)


class ConfigError(Exception):
    """Configuration is missing, malformed, or out of range. Always fatal (SPEC.md 6)."""


@dataclass(frozen=True)
class OpenItem:
    """One unresolved value from SPEC.md 20, or one raised during the build (`Ln`)."""

    number: str
    summary: str
    fix: str
    blocks_use: bool
    resolved: bool

    def __str__(self) -> str:
        return f"[{self.number}] {self.summary}"


@dataclass(frozen=True)
class Config:
    """Every loaded configuration file, validated.

    Attribute access is plain dict indexing because load() has already proved the keys in
    SCHEMA are present, of the right type and in range.
    """

    study1: dict
    hardware: dict
    schedule: dict
    filaments: dict
    participant_text: dict
    experimenter_text: dict
    participant_language: str
    experimenter_language: str
    open_items: tuple[OpenItem, ...]
    sha256: str
    config_dir: Path

    @property
    def unresolved(self) -> tuple[OpenItem, ...]:
        return tuple(item for item in self.open_items if not item.resolved)

    @property
    def blocking_unresolved(self) -> tuple[OpenItem, ...]:
        """Unresolved items that make the software unfit to run a real participant."""
        return tuple(item for item in self.unresolved if item.blocks_use)

    def has_placeholder_text(self) -> bool:
        """Whether any participant-facing string is still unapproved wording."""
        return any(_walk_placeholders(self.participant_text))


def resolve(data: object, path: str) -> list[object]:
    """Resolve a dotted path, returning every value it reaches.

    `a.b` returns one value. `a.b[*].c` returns one per element of the list at `a.b`. A path
    that does not exist returns an empty list -- the caller decides whether that is an error,
    because open_items.yaml deliberately names paths that do not exist yet.
    """
    values: list[object] = [data]
    for part in path.split("."):
        every = part.endswith("[*]")
        key = part[:-3] if every else part
        nxt: list[object] = []
        for value in values:
            if not isinstance(value, dict) or key not in value:
                continue
            item = value[key]
            if every:
                if not isinstance(item, list):
                    raise ConfigError(f"{path!r}: {key!r} is not a list")
                nxt.extend(item)
            else:
                nxt.append(item)
        values = nxt
    return values


def _walk_placeholders(node: object) -> list[str]:
    """Every string in a nested structure that is still marked as unapproved wording."""
    if isinstance(node, str):
        return [node] if node.startswith(PLACEHOLDER_PREFIX) else []
    if isinstance(node, dict):
        return [s for v in node.values() for s in _walk_placeholders(v)]
    if isinstance(node, list):
        return [s for v in node for s in _walk_placeholders(v)]
    return []


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"{path}: configuration file does not exist")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path}: expected a mapping at the top level, got {type(data).__name__}"
        )
    return data


def _check(filename: str, path: str, expected, low, high, loaded: dict[str, dict]) -> None:
    values = resolve(loaded[filename], path)
    if not values:
        raise ConfigError(f"{filename}: required key {path!r} is missing")
    for value in values:
        if value is None:
            raise ConfigError(
                f"{filename}: {path!r} is null, but a value is required. If this is a value "
                f"you do not have yet, it belongs in config/open_items.yaml."
            )
        # bool is a subclass of int, so an accidental `true` where a number belongs must not
        # pass silently.
        if expected is not bool and isinstance(value, bool):
            raise ConfigError(f"{filename}: {path!r} is a boolean, expected {_name(expected)}")
        if not isinstance(value, expected):
            raise ConfigError(
                f"{filename}: {path!r} is {type(value).__name__}, expected {_name(expected)}"
            )
        if low is not None and value < low:
            raise ConfigError(f"{filename}: {path!r} is {value}, below the minimum {low}")
        if high is not None and value > high:
            raise ConfigError(f"{filename}: {path!r} is {value}, above the maximum {high}")


def _name(expected) -> str:
    if isinstance(expected, tuple):
        return " or ".join(t.__name__ for t in expected)
    return expected.__name__


def _load_open_items(loaded: dict[str, dict], config_dir: Path) -> tuple[OpenItem, ...]:
    items = []
    for entry in loaded["open_items.yaml"]["items"]:
        checks = [entry["resolved_when"]]
        if "also" in entry:
            checks.append(entry["also"])
        resolved = True
        for check in checks:
            data = loaded.get(check["file"])
            if data is None:
                data = _read_yaml(config_dir / check["file"])
                loaded[check["file"]] = data
            values = resolve(data, check["path"])
            if not values or any(v is None for v in values):
                resolved = False
        items.append(
            OpenItem(
                number=str(entry["item"]),
                summary=" ".join(entry["summary"].split()),
                fix=" ".join(entry["fix"].split()),
                blocks_use=bool(entry["blocks_use"]),
                resolved=resolved,
            )
        )
    return tuple(items)


def _assert_same_keys(a: dict, b: dict, name_a: str, name_b: str, prefix: str = "") -> None:
    """A missing key is a startup error, never a silent fallback to the other language.

    SPEC.md 10.4. Comparing key sets catches the failure at load rather than at the moment the
    screen would have been shown, which in a three-hour session could be two hours in.
    """
    for key in sorted(set(a) | set(b)):
        here = f"{prefix}{key}"
        if key not in a:
            raise ConfigError(f"{name_a}: missing key {here!r}, which {name_b} defines")
        if key not in b:
            raise ConfigError(f"{name_b}: missing key {here!r}, which {name_a} defines")
        if isinstance(a[key], dict) and isinstance(b[key], dict):
            _assert_same_keys(a[key], b[key], name_a, name_b, prefix=f"{here}.")


def load(
    participant_language: str,
    experimenter_language: str,
    config_dir: Path = CONFIG_DIR,
) -> Config:
    """Load and validate every configuration file. Raises ConfigError on any problem."""
    languages = sorted({lang for _, lang in TEXT_FILES})
    for role, lang in (
        ("participant", participant_language),
        ("experimenter", experimenter_language),
    ):
        if lang not in languages:
            raise ConfigError(f"{role} language {lang!r} is not one of {languages}")

    loaded: dict[str, dict] = {}
    for filename in (
        "study1.yaml",
        "hardware.yaml",
        "schedule.yaml",
        "filaments.yaml",
        "open_items.yaml",
    ):
        loaded[filename] = _read_yaml(config_dir / filename)
    for relative in TEXT_FILES.values():
        loaded[relative] = _read_yaml(config_dir / relative)

    for filename, path, expected, low, high in SCHEMA:
        _check(filename, path, expected, low, high, loaded)

    for filename, path in REFERENCED_FILES:
        referenced = REPO_ROOT / str(resolve(loaded[filename], path)[0])
        if not referenced.exists():
            raise ConfigError(
                f"{filename}: {path!r} names {referenced}, which does not exist. Generate it "
                f"with tools/make_allocation.py."
            )

    for role in ("participant", "experimenter"):
        first, second = (TEXT_FILES[(role, lang)] for lang in languages)
        _assert_same_keys(loaded[first], loaded[second], first, second)

    config = Config(
        study1=loaded["study1.yaml"],
        hardware=loaded["hardware.yaml"],
        schedule=loaded["schedule.yaml"],
        filaments=loaded["filaments.yaml"],
        participant_text=loaded[TEXT_FILES[("participant", participant_language)]],
        experimenter_text=loaded[TEXT_FILES[("experimenter", experimenter_language)]],
        participant_language=participant_language,
        experimenter_language=experimenter_language,
        open_items=_load_open_items(loaded, config_dir),
        sha256=hash_files(sorted(p for p in config_dir.rglob("*.yaml"))),
        config_dir=config_dir,
    )

    # Stage boundary (CLAUDE.md): everything downstream assumes these hold.
    assert config.study1["design"]["conditions"], "no conditions configured"
    assert config.filaments["filaments"], "no filaments configured"
    assert config.open_items, "open_items.yaml defines no items"
    return config


def hash_files(paths: list[Path]) -> str:
    """SHA-256 over the contents of several files, in the order given.

    Path names are mixed in as well as contents so that renaming a pattern file changes the
    hash -- the name is what the condition mapping refers to.
    """
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()
