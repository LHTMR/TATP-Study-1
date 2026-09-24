"""The checks before a session starts. SPEC.md 11, 15, 17.5."""

from __future__ import annotations

import pytest

from tatp import config as cfg
from tatp import preflight as pre
from tatp.clock import Clock
from tatp.session import Session

EXAMPLES = cfg.CONFIG_DIR / "patterns" / "examples"


@pytest.fixture(scope="module")
def loaded():
    return cfg.load("sv", "en")


@pytest.fixture
def config(loaded, tmp_path):
    hardware = {**loaded.hardware, "data": {"folder": str(tmp_path / "data"),
                                            "cloud_sync_markers": []}}
    return cfg.Config(**{**loaded.__dict__, "hardware": hardware})


def _session(config, number=1, initials="SM", abort=None):
    session = Session(config, "01", number, initials, EXAMPLES, clock=Clock(), rng_seed=1)
    session.start()
    if abort is not None:
        session.close(abort)
    return session


def _keys(findings, severity=None):
    return [f.text_key for f in findings if severity is None or f.severity == severity]


def test_a_first_session_with_nothing_on_disk_is_clear(config):
    assert pre.preflight(config, "01", 1, "SM", pre.data_folder_for(config)) == []


def test_a_code_absent_from_the_allocation_is_refused(config):
    findings = pre.preflight(config, "999", 1, "SM", pre.data_folder_for(config))
    assert _keys(findings, pre.REFUSE) == ["preflight.code_not_allocated"]


def test_a_session_number_the_allocation_lacks_is_refused(config):
    findings = pre.preflight(config, "01", 4, "SM", pre.data_folder_for(config))
    assert "preflight.code_not_allocated" in _keys(findings, pre.REFUSE)


def test_a_completed_session_is_refused(config):
    _session(config, abort="")
    findings = pre.preflight(config, "01", 1, "SM", pre.data_folder_for(config))
    assert _keys(findings, pre.REFUSE) == ["preflight.session_completed"]


def test_an_aborted_session_is_warned_not_refused(config):
    _session(config, abort="participant unwell")
    findings = pre.preflight(config, "01", 1, "SM", pre.data_folder_for(config))
    assert _keys(findings) == ["preflight.session_aborted_before"]
    assert _keys(findings, pre.REFUSE) == []


def test_an_aborted_attempt_before_a_completed_one_is_still_refused(config):
    _session(config, abort="participant unwell")
    _session(config, abort="")
    findings = pre.preflight(config, "01", 1, "SM", pre.data_folder_for(config))
    assert _keys(findings, pre.REFUSE) == ["preflight.session_completed"]


def test_session_three_before_session_two_is_warned(config):
    _session(config, number=1, abort="")
    findings = pre.preflight(config, "01", 3, "SM", pre.data_folder_for(config))
    assert findings == [pre.Finding(pre.WARN, "preflight.previous_session_missing", "2")]


def _with_pre_s_estimate(session):
    """Session 1 as though its pre-S long protocol had been accepted."""
    row = dict.fromkeys(session.files.tables["calibration_pinprick"].column_names)
    row.update(
        timestamp_iso=session.clock.wall_iso(), phase="pre_sensitisation", region="secondary",
        run_index=1, superseded=False, start_filament_label_g="26",
        start_source="config_default", applications_total=12, applications_measure=9,
        capped=False, slope_prior_vas_per_log10=51.6, f40_mn=150.0,
        chosen_filament_label_g="15", chosen_force_mn=147.0, out_of_range=False,
    )
    session.files.write("calibration_pinprick", **row)
    session.close("")


def test_different_initials_are_warned_with_the_existing_warning(config):
    _with_pre_s_estimate(_session(config, number=1, initials="AB"))
    findings = pre.preflight(config, "01", 2, "SM", pre.data_folder_for(config))
    assert findings == [pre.Finding(pre.WARN, "warnings.experimenter_changed", "SM")]


def test_a_previous_session_without_an_estimate_is_warned_at_launch(config):
    """SPEC.md 8.2: the fallback prior is visible before the session, not only in its log."""
    _session(config, number=1, abort="")
    findings = pre.preflight(config, "01", 2, "SM", pre.data_folder_for(config))
    assert findings == [pre.Finding(pre.WARN, "preflight.previous_estimate_missing", "1")]
    _with_pre_s_estimate(_session(config, number=1))
    assert pre.preflight(config, "01", 2, "SM", pre.data_folder_for(config)) == []


def test_a_second_instance_is_refused_and_the_lock_frees_on_release(config):
    folder = pre.data_folder_for(config)
    lock = pre.InstanceLock(folder)
    assert lock.acquire()
    assert _keys(pre.preflight(config, "01", 1, "SM", folder), pre.REFUSE) == [
        "preflight.another_instance"
    ]
    assert not pre.InstanceLock(folder).acquire()
    lock.release()
    assert pre.preflight(config, "01", 1, "SM", folder) == []


def test_every_finding_has_its_text_in_both_languages(loaded):
    english = cfg.load("sv", "en").experimenter_text
    swedish = cfg.load("sv", "sv").experimenter_text
    for key in ("preflight.code_not_allocated", "preflight.session_completed",
                "preflight.session_aborted_before", "preflight.previous_session_missing",
                "preflight.another_instance", "warnings.experimenter_changed"):
        for text in (english, swedish):
            node = text
            for part in key.split("."):
                node = node[part]
            assert "{value}" in node or key == "warnings.experimenter_changed"
