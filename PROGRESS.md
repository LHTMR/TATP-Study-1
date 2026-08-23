# PROGRESS

Handover file (CLAUDE.md). Between `docs/SPEC.md`, this file, `FOR_S.md` and the git log, a
fresh session should need nothing from any previous conversation.

**`FOR_S.md`** holds only what S must supply or decide for the build to move — values, wordings,
hardware limits. **`docs/NOTES.md`** holds what is merely logged: deviations from Bilaga 1,
pilot-protocol checks, analysis-plan questions, process. Keep all three updated together.

**Last updated:** 23 August 2026, session 10.
**Milestone:** 2 (the checks) — *in progress. The literals and blinding checks and the
screenshot comparison are in the gate; the end-to-end validator is what remains.*

**Session 10** built the three checks SPEC.md 17.2 and 17.4 name and nothing else did:
`tools/lint_literals.py`, `tests/test_blinding_text.py` against the new `config/blinding.yaml`,
and `tatp/screenshots.py` with a 60-entry manifest. `make check` now runs them. See "What
session 10 found" below — each of the three found something, which is the only reason to
believe they work.

**Session 9 closed Milestone 1** with `tatp/schedule.py`, `tools/preview_schedule.py` and the
block boundaries in `Session`. The slice now sets session t=0 and runs its application inside
intervention block 1. S settled the grid (decision 31). 221 tests.

Session 8 built `tatp/touchcal.py` and `run_session.py`.

**Session 7 was a design session, not a build one.** It settled the participant wording, then
S's answers to it changed Protocol B twice and added a new experimenter feature. Nothing new
executes; what changed is `SPEC.md`, `DATA_SCHEMA.md`, the comparison document, the config and
the text files. 146 tests.

Session 6 closed the loop: one pinprick trial runs end to end, both windows exist, thin.
Session 5 built the foundation — config, allocation, clock, provenance, data files, garment,
responder, VAS and session.

### What session 10 found

A check that has never failed is a check nobody has tested. All three failed on first run, and
what they caught is the argument for having built them.

1. **The VAS anchor labels overlapped, and nobody had looked.** On `pain` (anchors at 0 and
   10 %) and `intensity` (0, 10, 90, 100 %) the labels were drawn centred on their own
   percentage with no collision handling, so at every window size the lab will use they landed
   on top of each other. On `intensity` all four were illegible — and that is the scale the
   whole touch calibration is rated against, so "precis märkbar" and "precis obehaglig" being
   unreadable is not cosmetic. **This was invisible to 250 passing tests** and would have been
   found by a participant. `VasWidget._anchor_layout` now stacks a colliding label onto a row
   underneath rather than moving it sideways, because moving it would put the anchor somewhere
   other than the percentage it names. Six tests pin it, across both languages.
2. **The two unit conversions were written in six places under three names** — `S_PER_MIN` in
   `schedule.py`, `SECONDS_PER_MINUTE` in `experimenter.py`, `MS_PER_S` in `touchcal.py`, and
   bare `1000.0` and `60.0` in three more. Six chances to write `100.0` and get a plausible
   wrong number rather than an error. Now `tatp/units.py`, which holds conversions and nothing
   else. **These are the one kind of constant that must not move to `config/`:** there are
   sixty seconds in a minute whatever S decides, so a configurable `s_per_min` would be a
   setting that can be wrong.
3. **The forbidden-terms check passes on the live text**, which is the result that needs the
   most care in reading. `config/blinding.yaml` says so at length and the point is worth
   repeating here: a grep catches the study name and the condition labels and *cannot* catch
   "this should help with the pain", which contains neither and breaks SPEC.md 16 completely.
   It is a floor. The wording review is the actual check.

### What session 7 decided

All S's. Recorded here because it is not recoverable from the diff; **the reasoning behind it
is not, and belongs in the ethics folder, not here.**

1. **Participant wording is approved and in the config.** Open items L4 and 12 closed.
2. **Protocol B step 1 targets the two *labelled* anchors**, 10 % and 90 %, because a
   participant can only be asked to adjust to a sensation the scale names.
3. **Protocol B step 2 became an estimation run that defines the targets** — ten randomised
   amplitudes, a log fit, inverted for P20/P30/P80 — rather than a spot-check of the
   adjustments. This is the largest change of the session.
4. **The area mapping is verbal**; the software only paces it.
5. **A fit preview for the experimenter**, off by default, with the blinding cost written down.

### What is NOT built yet from session 7

The spec, schema, config and strings are all in place for these; the code is not, because the
procedures they attach to do not exist yet.

- The step 2 estimation run and its fit — `touchcal_estimate` and `touchcal_fit` are specified
  tables with no writer.
- The fit-preview plot widget (`SPEC.md` §11.1). Deliberately not built ahead of the procedures
  it previews — there is nothing to plot yet.
- `self_start_latency_ms` (§12.3): the column exists, the measurement does not.

---

## Read this first

**`make check` exists and passes, but it is not the whole gate yet.** It runs the unit tests,
the linter and the screenshot comparison. The end-to-end validator (`tools/validate_session.py`,
SPEC.md 17.3) does not exist, so the target prints a line saying so rather than letting a
partial gate look like a passing one. Build it and delete that line — that is what is left of
Milestone 2.

**No screenshot is armed yet.** All 60 are catalogued and written, none has an approved
reference, so none is compared — that is the SPEC.md 17.4 design, not an oversight. Arming them
(`make shots ARGS="--approve-all"`, then committing `screenshots/reference/`) is **waiting on
S**: it freezes the current layout, including session 10's anchor-stacking change, as the thing
every later diff is measured against.

```
make check
```

---

## Environment

`tatp-study-1` was created on this machine and verified: PySide6 6.11.2, Qt 6.11.2, and
`QWidget.grab()` returns a correctly-sized pixmap under `QT_QPA_PLATFORM=offscreen`. So the
headless screenshot approach in SPEC.md 17.4 is sound on this platform.

**One change to `environment.yml`:** `sounddevice` → `python-sounddevice`. The conda-forge
package name differs from the import name and the original spelling does not resolve on any
channel, so `conda env create` failed outright. The import name in Python is still
`sounddevice`.

**All three reference repositories are public and readable directly** — `Touch-Comm-ASD`,
`Expt_MonofilamentDiscrimination` and `ttpa_touch_the_pain_away` (`SPEC.md` §5.2), each fetched
and confirmed 23 Aug 2026. Read the source when a detail matters rather than working from the
spec's summary. `github.com` is on the `WebFetch` allow list, so no permission prompt.

Note the base conda is **osx-64**, so the env is Intel/Rosetta on this Mac. Harmless here;
irrelevant to the Windows lab PC.

**The `conda` shell function was broken in session 5's shell** — `CONDA_EXE` was unset, so
`conda run …` exited 126 with "permission denied". The binary on `PATH` is fine, so
`command conda run …` worked and was used until the Makefile existed. **Use `make` and the
problem does not arise**: `make` spawns its recipes through `/bin/sh`, which never defines the
function. Do not "fix" anything in the repository for this.

---

## What exists

| File | State |
|---|---|
| `docs/DATA_SCHEMA.md` | **Complete**, and now genuinely parsed by `tatp/datafiles.py` |
| `config/*.yaml` | All load and validate. `config/allocation.csv` is generated and committed |
| `tatp/config.py` | Runs. Load, validate against `SCHEMA`, cross-check language key sets, open items |
| `tatp/allocation.py` | Runs. Balance verified against the committed file |
| `tatp/clock.py` | Runs, including the accelerated mode SPEC.md 17.3 needs |
| `tatp/provenance.py` | Runs. Every field populated for real |
| `tatp/datafiles.py` | **New.** Schema-driven writer, open-append-close per row |
| `tatp/garment/base.py` | **New.** Ceiling, rate limit, command recording, pattern playback, looping |
| `tatp/garment/mock.py` | **New.** Full driver with fault injection |
| `tatp/garment/patterns.py` | **New.** Tick-grid loader and event expansion |
| `tatp/responder.py` | **New.** R400 key mapping, with the `escape` rule machine-checked |
| `tatp/ui/vas.py` | **New.** `VasState` (no Qt, all the behaviour) and `VasWidget` |
| `tatp/session.py` | Session state, all 40 provenance keys, the log, blinding |
| `tatp/ui/participant.py` | **New.** Three screens — text, warning cue, VAS — plus screen placement |
| `tatp/ui/experimenter.py` | **New.** Banners, identity, phase, elapsed, garment state, open items, instruction |
| `tatp/pinprick.py` | **New.** One application end to end. Search/bracket/estimate is Milestone 3 |
| `tatp/touchcal.py` | **New.** The accelerating control, one anchor adjustment, one touch rating |
| `tatp/schedule.py` | **New.** Grid generation, per-block overrides, the §7.3 rules as warnings |
| `run_session.py` | **New.** Entry point. Adjustment, touch rating, block, pinprick application, close |
| `tools/make_allocation.py` | Run once; the output is committed |
| `tools/preview_schedule.py` | **New.** SPEC.md §7.2. `make preview`; launcher entry 4 when it exists |
| `tatp/screenshots.py` | **New.** SPEC.md 17.4. Catalogue of 60 states, manifest, per-screen arming |
| `tatp/units.py` | **New.** `MS_PER_S` and `S_PER_MIN`. Conversions only, never config |
| `tools/lint_literals.py` | **New.** SPEC.md 4.2, over the AST. `make literals` prints the inventory |
| `tools/shots.py` | **New.** Entry point for the screenshot run; sets the offscreen platform |
| `config/blinding.yaml` | **New.** The forbidden terms of SPEC.md 16, reviewable by S |
| `Makefile` | `check`, `test`, `test-one`, `lint`, `literals`, `shots`, `preview` |
| `tests/` | 263 tests, all passing headless |

## What does not exist yet

`audio.py`, `tools/validate_session.py`, `tatp/ui/widgets.py`,
`tatp/garment/arduino_{mosfet,valves}.py`, `instruments.py`,
`launcher.py`, `tools/` (except `make_allocation.py`), `sim/`, `README`,
`SOP.md`, `HARDWARE_BRINGUP.md`.

**The slice now runs outside the tests.** `run_session.py` takes the participant code, session
number, initials and pattern folder, opens both windows, runs one application of the configured
starting filament and closes the session. The four-entry launcher of `SPEC.md` §4.1 is
Milestone 5 — three of its four entries have nothing to open yet.

```
conda run -n tatp-study-1 python run_session.py --participant 01 --session 1 --experimenter SM --patterns config/patterns/examples
```

---

## Decisions taken, not already in SPEC.md

Items 1–8 were taken in session 1 and are unchanged; 9–13 are session 5; 23–26 are session 7;
27–30 are session 8; 31–34 are session 9.

37. **The participant sets their own white-noise level, and it is checked against the garment.**
    S's decision, 23 Aug 2026, replacing "set the levels with a meter". `SPEC.md` §10.7 has the
    procedure. **Specified and drafted, not built** — it needs `audio.py`, which is Milestone 4.

    The reasoning worth keeping: a meter fixes one number for every participant, every pair of
    headphones and every room, when the question is whether *this* participant can hear *this*
    garment. Four steps — raise the noise to audible, start the garment, raise until it masks
    while stopping short of uncomfortable, then confirm it is masked, re-raising up to
    `masking_check_max_attempts` times.

    Four things follow that are decisions rather than transcription:

    - **The check uses the fixed CT-targeted pattern, never the participant's own** (S). Fixed
      means it carries no information about the condition; the participant's own would put the
      condition into setup where the experimenter can hear it. `docs/NOTES.md` N2.6 records that
      everyone therefore meets that pattern once before calibration.
    - **`participant_cue_level_dbfs` is gone**, replaced by `participant_cue_over_noise_db`. An
      absolute cue level cannot stay audible over a noise level that now varies per participant.
    - **`white_noise_max_dbfs` is a hard ceiling**, the audio analogue of the pressure ceiling.
      S's answer was that participants modulate themselves, which is true of the instruction and
      not of a held button. It is a stop on the software, **not a safe sound pressure**: dBFS
      says nothing about SPL until the system volume is fixed, which is now what L3 asks for.
    - **Yes/no is positional** — options drawn left and right, chosen with the matching large
      button (S), affirmative on the left everywhere so it is one convention. `screens.comparison`
      already worked this way.

    - **A failed check escalates to the experimenter, and the remedy is earplugs** (S). Raising
      the noise is the software's only lever, so when it runs out — attempts exhausted or the
      ceiling reached — the experimenter is alerted audibly and on screen, the noise stops so
      the two can talk, and earplugs go under the headphones. **The check then restarts from
      step 1**, because earplugs move the participant's own threshold as well as the garment's
      loudness; resuming at step 3 would leave the noise at a level chosen for unplugged ears.
      `earplugs_used` is recorded, and `masking_attempts` accumulates across the restart.
      Still unmasked after that is a logged limitation, not a refusal. `docs/NOTES.md` N2.8
      records that earplugs attenuate the participant cue too, which nobody has checked.

    The wording in `config/text/participant_{sv,en}.yaml` under `audio_setup` is mine, drafted
    on S's instruction and **approved by S on 23 Aug 2026**. It is not ethics-sourced like the
    VAS questions, and is deliberately not marked `PLACEHOLDER`, because it is practical
    instruction about headphones rather than a description of the study — which is why S could
    approve it directly rather than it waiting on an ethics attachment.

36. **The software pressure ceiling is 250 kPa, the hardware maximum.** S's decision, 23 Aug
    2026, after I raised that `SPEC.md` §13 asked for a ceiling *below* it. Open item L1 closed
    and the A2.1 row deleted.

    **What changed is the spec, not just the number.** §10.3 and §13 both asserted a margin
    below the hardware; they now say what is actually true — the ceiling guarantees the software
    never commands past the device's rating, and holds nothing in reserve. `Limits.from_config`
    relaxed from `ceiling < max` to `ceiling <= max`; **above** the maximum is still refused,
    because that is a clamp that clamps nothing. The margin is §13's first bullet, the physical
    emergency stop and the rapid depressurisation mechanism, which act without the software.

    A test that asserted the ceiling sits strictly below the maximum had to be rewritten. It was
    a correct test of the old spec, so this is a spec change with a test change behind it rather
    than a test relaxed to make something pass.

31. **The rekindle divides the intervention, and block spacing is its own parameter.** Settled
    with S on 23 Aug 2026 over three rounds. `SPEC.md` §7.1 has the rule; `make preview` shows
    the result: **55, 63, 71, 79, 87, 95, rekindle 105–110, 117, 125, 133, 141, 149, 157.**

    **The chain of findings is worth keeping, because each step was only visible once the
    previous one was built.**

    a. The original formula spaced blocks at `intervention_duration / n_blocks` and put
       **block 7 exactly on the rekindle**. The preview found it the first time it ran.
    b. S chose to keep the rekindle at t+60 and delay the first hour, which gave 50…165 with
       10 min spacing and a 5 min pause. Clean, but it exposed the real constraint: **twelve
       blocks at 10 min fill all 120 minutes of the intervention and leave nothing for the
       rekindle**, so the pause had to be borrowed from the front, leaving 1 min of margin
       ahead of the rekindle and 5 after.
    c. S asked for 8 or 9 min spacing for breathing room. That required decoupling spacing from
       `intervention_duration / n_blocks` — the derived value could never produce slack.
       `block_spacing_min` is now explicit. **8 was chosen over 9** because it leaves more room
       everywhere: 6 min from the last pre-rekindle block's estimated end to the rekindle
       against 3.5, and 7.5 min after it against 5.

    The rule: the rekindle splits the intervention into two windows, blocks are divided as
    evenly as possible between them (the later window takes the extra on an odd count), and
    within each they sit `block_spacing_min` apart with the window's spare time **shared at both
    ends** rather than packed against the start. Sharing it is what buys the room — a block
    overrunning its estimate has somewhere to go at either edge.

    Two details that are decisions, not arithmetic: margins are **rounded down to whole
    minutes**, because the experimenter reads offsets off a schedule and launches by hand, and
    rounding down gives the spare half-minute to the far end rather than pushing a block toward
    what the window abuts. And when blocks **do not fit**, they start at the window's opening and
    overrun the far end rather than being centred and spilling out of both — overrunning is a
    scheduling problem the warnings describe, whereas spilling backwards pushes a block into the
    rekindle, which is the one thing the split exists to prevent.

32. **The equal-spacing check ignores the gap holding the rekindle.** That gap is wide on
    purpose, so comparing it against the others reported the one intended irregularity as a
    broken rule — two warnings on a correct grid, twice, first when the pause was 5 min and
    again when the margins widened it further. Subtracting the rekindle's duration was not
    enough; the check now skips the straddling gap entirely and measures each half separately.
    A check that always fires is a check nobody reads.

33. **The intervention window bounds when a block may be *launched*, not when its last rating
    must be in.** The experimenter starts each block and the grid puts the last one on the
    closing minute, so testing the block's *end* against the window would warn on every grid
    once durations exist. Start only, and `SPEC.md` §7.1 says so.

34. **Blocks are started by `Session.start_block`, never by the clock.** SPEC.md 7.4: the
    software times and counts down, the experimenter launches, nothing is skipped automatically.
    The planned offset and the actual start go in the `log` as `block_started`, with the drift
    between them — the gap is data, not something to correct. `close()` ends an open block so an
    aborted one still gets an actual end. There is no `blocks` table: `DATA_SCHEMA.md` already
    says the log carries block boundaries.

    `block_index` is **identity, not position**. An override that moves a block does not
    renumber it, because the value in an already-written row has to keep meaning the same block.
    The cost of having no `blocks` table is logged as `docs/NOTES.md` N3.6.

35. **Overlap is asked of the blocks in the order they run, not in index order.** The
    spec-review agent found the first version comparing only index-adjacent pairs and skipping
    the overlap test entirely once a pair was out of order — so an override putting block 1 at
    58 min, overlapping block 4, reported only the ordering. It now sorts by offset and compares
    against whatever reaches furthest into the session, which also catches a short block nested
    inside a long one. Two tests pin both cases.

    The same review caught two tests that would have become `0 == 0` the day open item 4 is
    resolved, both asserting the log carries as many `schedule_warning` rows as the live grid
    produces. They are driven by a crafted faulty grid now. **This is decision 21's lesson
    recurring**, and it recurs because asserting against live config always looks reasonable
    at the moment of writing.

27. **The pressure adjustment runs on real seconds, not on the accelerated clock.** A tap
    threshold and a ramp rate describe the participant's hand. Scaling them does not make a
    session faster, it makes the control different: at speed 100 no press is short enough to be
    a tap and a hold crosses the whole range in 60 ms. `Clock.real_elapsed_s()` was added for
    this, and `duration_s` on a `touchcal_adjust` row uses it too — that column is the FOR_S
    A3.6 measurement and must not be reported scaled. **The adjustment time-out stays scaled**,
    because that one is the session waiting for the participant rather than the participant
    acting. This was found by a test, not by reasoning: the first taps moved nothing.

28. **`AdjustmentState` takes the time as an argument and imports no Qt.** The ramp is then
    tested at exact times instead of at whatever times a timer fired, and the travel is the
    closed-form integral of the ramp rather than a per-tick accumulation — so how often the
    timer fires cannot change how far a hold travels. There is a test that pins exactly that.

29. **Minimum exploration is recorded, not enforced.** `min_exploration_met` is written on every
    row and a short confirm is still accepted. Refusing one means telling the participant why,
    and no approved wording for that exists — inventing one would be participant-facing text
    written outside the ethics attachments. Logged as `docs/NOTES.md` N2.5.

30. **`touch_calibration.anchor_prompt_keys` pairs each anchor with what the participant is
    asked.** `[just_noticeable, just_uncomfortable]` against `anchors_pct` `[10, 90]`, in order,
    with an assert that the two lists are the same length. The pairing is config and not code
    because the wording is ethics-bound and the anchors are tunable.

    `EMERGENCY_STOP_SCREEN` moved from `tatp/pinprick.py` to `tatp/ui/participant.py` as
    `show_emergency_stop()`, now that two protocols show it.

23. **Protocol B step 2 defines the targets; it no longer checks them.** Step 1's adjustments
    now only set a sampling bracket. Step 2 presents ten randomised amplitudes across it, fits
    `rating ~ a + b·log(pressure)` and inverts for P20, P30 and P80. `SPEC.md` §9 has it. Two
    choices are marked **[R]** there because they were my recommendation, not S's decision: the
    log fit form and one adjustment per anchor. **The §7.2 time budget is not re-derived** —
    that measurement is `SPEC.md` §20 item 8.

24. **Adjustment targets must be points the scale names.** 10 % "just noticeable" and 90 % "just
    uncomfortable"; everything else derived. Asking a participant to adjust to an unlabelled
    position on a line is a different task from asking for a sensation. The principle
    generalises — apply it to any future adjustment step.

25. **The area mapping is verbal and the software only paces it.** No step counting, no recorded
    signal, no participant screen. The **white noise stops for the whole phase** so the two can
    talk — the only place masking is deliberately given up. The mapping measurement is a ruler,
    not a keypress.

26. **The fit preview is an opt-in break of the experimenter blind.** `SPEC.md` §11.1. Off by
    default, `fit_preview_enabled` in every session file, warning-severity log line and banner
    when on, and a test that fails if the flag is flipped in passing.

    **A re-run never overwrites**: the discarded run keeps its rows with `superseded: true` and
    its own `run_index`. A procedure repeatable until it looks right is a forking path unless
    every attempt is retained — keep that even if the preview is switched off.

1. **`docs/DATA_SCHEMA.md` is parsed, not just read.** It declares a parsing contract: a
   `### table_name` heading followed by a table with the header
   `| Column | Type | Unit | Required | Description |`. `tatp/datafiles.py` reads it and
   `tools/validate_session.py` will, so the writer and the validator cannot drift from the
   documentation. Edit the markdown and both follow. **This is the reason not to reformat
   those tables casually.**

2. **`config/open_items.yaml` is the SPEC.md 20 mechanism.** Each item names a dotted config
   path in `resolved_when:`; the loader warns for every path that is still null. Adding an open
   item means adding a row there, not code.

3. **Four locally-raised open items (`L1`–`L4`)**, for values the spec *requires to exist* but
   does not fix: the software pressure ceiling (200 kPa is a working value, not an agreed
   limit), the pressure rate limit (60 kPa/s), audio levels in dBFS, and the participant screen
   text. All in `FOR_S.md`.

4. **Participant screen text is a placeholder, deliberately.** Every such string begins
   `PLACEHOLDER`, `Config.has_placeholder_text()` detects them, and the experimenter screen is
   to carry an unmissable banner while any remain. **This is the main thing S needs to supply.**

5. **Experimenter Swedish was written from scratch** (`experimenter_sv.yaml`). Not
   ethics-bound and not participant-facing, so it did not need to be sourced. Worth a read.

6. **Allocation design.** Condition order drawn from a pool holding each of the 6 permutations
   equally often. Starting limb alternates by participant *index*, which balances 21/20 exactly
   where random assignment would not. Codes `01`–`41`, seed `20260823` recorded in a `#` header
   line inside the CSV. Now generated, committed and covered by tests.

7. **`static_sham` pattern** holds all five channels on, so the sham matches the moving patterns
   in spatial extent and differs only in motion. **Assumption — confirm at bring-up.**

8. **Permissions and `CLAUDE.md` tightened** (see the git log): the bypass class is denied,
   because each of `find`, `sed`, `bash -c` and the rest is a way to run something the deny list
   would otherwise have caught. The one remaining hole — `conda run … python` — is stated in
   `CLAUDE.md`, narrowed to the four forms the Makefile uses. Argument paths are constrained by
   `.claude/hooks/check_bash.py`, which resolves every path token and refuses anything outside
   the repository.

9. **`play_pattern` takes no `params` dict**, though SPEC.md 12.1's signature has one. Every
   per-pattern parameter the spec names — row interval, channel ids, loop — lives in the
   pattern's sidecar YAML, so `params` would be an option nothing reads, which CLAUDE.md
   forbids. The docstring in `tatp/garment/base.py` says so. **A stated deviation from the
   spec's interface** — say if `params` was meant to carry something not anticipated.

10. **The clamps live in the base class, not the drivers.** SPEC.md 12.1 lists `set_pressure`
    as "clamped to the configured ceiling" per driver. A clamp implemented per driver is a
    clamp that differs per driver, so the ceiling, the rate limit, command recording and
    pattern playback are all in `GarmentController` and a driver implements device I/O only.

11. **The rate limit does not apply to the first command to a channel, nor to `stop()`.** It
    constrains change over elapsed time, and the first command has no interval to constrain.
    SPEC.md 13's purpose is that holding a button cannot ramp to maximum quickly, not that a
    single deliberate command to a calibrated pressure is slowed. `stop()` must never be slowed.

12. **Pattern looping lives in the base class and wraps elapsed time** rather than resetting it,
    so a slow tick resumes at the right point in the cycle instead of dropping a whole cycle.
    At exactly `t = duration_s` the next cycle's first row has already begun — that is correct,
    and there is a test that pins it.

13. **`docs/calibration_sim.py` is excluded from ruff** rather than reformatted. It is the
    record of the simulation behind `docs/calibration_methods_comparison.md` and the numbers
    there should stay traceable to the code as it was run.

14. **The VAS splits into `VasState` and `VasWidget`**, in the one file `SPEC.md` §4 gives it.
    The state imports no Qt and holds all the behaviour, so every rule in SPEC.md 10.2 is
    tested directly instead of through a widget.

15. **The first VAS press has a direction even though it does not move the marker**, so
    pressing the other button next counts as a direction change. SPEC.md 10.2 does not say
    which way to read this. A test pins the reading.

16. **A confirm with no marker shown produces no response.** There is nothing to record, so
    `VasWidget` emits `pressed_without_marker` and the session logs the press instead.

17. **`Session.experimenter_view()` is the only thing the experimenter screen may show.** The
    blinding rule then has a test on it rather than depending on care at each call site.

18. **The RNG seed is drawn when not supplied, and recorded either way**, so a session is
    reproducible from its own data file. Defaulting it to a constant would make every session's
    randomisation identical.

19. **`Session` takes the pattern folder as an argument with no default.** The experimenter
    selects it (SPEC.md 12.2), and defaulting to `config/patterns/examples/` would quietly
    substitute the provisional mockups for the real patterns (open item 5).

Items 20–26 are session 6.

20. **Three decisions S took on 23 Aug 2026, now in `docs/SPEC.md` §8.1–8.2** rather than only
    in a conversation. All three are S's, not mine.

    a. **Filaments are identified by their gram label** — `26`, not `5.46`. That is what is
       printed on the filament and what an experimenter reads off the kit under time pressure.
       `label_g` is the identifier in `filaments.yaml`, on the experimenter screen and in the
       data files; the evaluator size and the forces are companion values. The columns are
       `filament_label_g` and `applied_filament_label_g`, and `start_filament_size` /
       `chosen_filament_size` in `calibration_pinprick` moved with them. **The label is a string
       written exactly as the kit prints it**, decimals included — `2.0`, not `2` — because the
       experimenter matches it against the filament by eye.

       `config/filaments.yaml` is now transcribed wholesale from the **Aesthesio Precision
       Tactile Sensory Evaluator Data Chart**, supplied by S on 23 Aug 2026: all twenty
       filaments, 0.008 g / 0.08 mN up to 300 g / 2940 mN, where the file previously held
       eleven. `tests/test_config_files.py` checks every label against its force at the chart's
       stated 9.80665 mN/g, at 3 % tolerance because the chart's own mN column is rounded to two
       significant figures. **S confirmed on 23 Aug 2026 that the chart is the manual for the
       exact set held, that all twenty are present and that the labels match**, so the file needs
       no further reconciliation with the kit.

       **`force_manual_mn` is gone and `force_nominal_mn` changed value.** The file used to
       carry the manual force (255 mN for the 26 g) *and* a "nominal label" that rounded it
       (260 mN). The chart has one manufacturer force, so the rounded one had no source —
       `SPEC.md` §8.1's "Nominal label" row was unsourced too and has been deleted with it.
       Two tests moved from 260.0 to 255.0 as a result.

    b. **`intolerable` is derived, not observed.** There was never a mechanism for it. A rating
       reaching `pinprick.intolerable_vas_pct` is the proxy, so the software raises the flag —
       no experimenter control, no participant control beyond the scale and the emergency stop.
       The cap is prospective, per site, per time point, escalating to **all** sites once
       `pinprick.intolerable_sites_for_global_cap` distinct sites are capped, at the lowest
       force that reached the ceiling in that run. **Enforcement lands with the ladder in
       Milestone 3** — there is no filament selection yet to constrain, and the state to track
       it would be an abstraction with no consumer. The flag and its log event are written now.

    c. **`force_applied_mn` falls back to the label force while the set is unweighed.** My
       previous session had made it optional and left it empty, which would have made Protocol A
       impossible to pilot at all — and `FOR_S.md` A3.4 asks for the slope prior to be
       re-estimated *from pilot data*. It is now required and always populated: measured where
       there is one, nominal otherwise. Nothing is hidden, because `force_measured_mn` is empty
       on exactly those rows. Every force column now describes the filament that actually
       touched the skin, so the three stay consistent about one object.

    Two things I fixed by assumption rather than asking again, both stated in `SPEC.md` §8.2:
    the escalated all-sites cap uses the **lowest** ceiling-producing force in the run, and it
    clears at the next time point like the per-site cap. Censoring of ceiling ratings is
    `docs/NOTES.md` N3.5.

21. **Five tests were asserting today's state instead of the mechanism, and broke when the
    participant text changed on disk** — `config/text/participant_{sv,en}.yaml` was rewritten
    by a parallel session, which set `meta.instructions_supplied` and closed L4, so
    `has_placeholder_text()` went false. The tests asserted things like "L1–L4 are all still
    open" and "the live config contains a PLACEHOLDER", which were true when written and became
    false the moment anything moved. Each is now driven by a crafted input or by the flag
    itself, **so the suite passes whatever state the participant wording is in** — which is what
    makes the leak in decision 22 safe to unwind:

    - `test_an_open_item_is_resolved_exactly_when_its_config_path_is_filled` reads
      `open_items.yaml` and asserts `resolved` agrees with the paths it names, for every item.
      That holds at every point in the build rather than at one.
    - `test_unapproved_participant_wording_is_detected` and
      `test_unapproved_participant_wording_is_logged_at_startup` build a config carrying a
      `PLACEHOLDER` string, so the detector and the startup warning stay tested after the real
      wording is approved.
    - `test_the_placeholder_banner_follows_the_view_in_both_directions` drives the banner from
      the flag, both ways, instead of from whatever the config holds today.

    **The lesson is worth keeping:** a test that asserts an open item is still open fails as a
    reward for progress. Assert the mechanism, and let `open_items.yaml` carry the state.

22. **A parallel session's participant-wording work leaked into this session's commits.** Two
    Claude sessions were running against the same working tree on `main`. The other one is
    drafting `config/text/participant_{sv,en}.yaml`; its edits appeared here as working-tree
    changes I could not distinguish from my own, and I committed them alongside my work.

    **Corrected 23 Aug 2026 by the wording session itself.** The paragraph here previously said
    the wording was unfinished and that `meta.wording_approved` and `meta.instructions_supplied`
    were set prematurely, and recommended reverting the participant files. That was a reasonable
    inference from a half-finished-looking tree, but it is wrong: S approved the screen text
    explicitly ("The text is otherwise approved"), then answered every outstanding question —
    the adjustment targets, the verbal mapping, the self-start latency — and instructed that the
    items be marked done rather than held open for ethics alignment or later human review.

    So the flags are correct and the banner is correct to be off. **Do not revert the participant
    files.** What was genuinely unfinished at the moment of the leak was S's answers to the
    open-questions list, and those have since landed.

    What leaked, and where:

    | Commit | Leaked content |
    |---|---|
    | `c25a7df` | `FOR_S.md` A1.2 and the paragraph introducing the draft document |
    | `16beceb` | `FOR_S.md` A1 prose again |
    | `6949f9c` | `config/text/participant_{sv,en}.yaml` in full, `docs/participant_screen_text_draft.md`, `instructions.mapping_script` in both experimenter files, and the `FOR_S.md` A1 "approved, nothing here needs you" rewrite |

    Nothing is pushed, so all three are freely rewritable — but there is no longer anything to
    undo, only mis-attributed authorship. Decision 21 above made every test state-agnostic about
    the wording, so the suite never depended on which session's version was in the tree.

    **The fix going forward is S's, and already decided: parallel work gets a branch.** Two
    agents sharing one working tree cannot tell whose uncommitted change is whose, and `git add`
    with explicit paths does not help when the leak is inside a file both are editing.

21. **`ExperimenterWindow` takes a reader callable, not the `Session`.** "It reads
    `experimenter_view()` and nothing else" is then structural rather than a habit: the window
    holds no reference to a session and so has no route to `Session.condition`, whatever a later
    edit does to it. `run_session.py` passes `session.experimenter_view`.

22. **`session:` and `terms:` blocks added to `config/text/experimenter_{sv,en}.yaml`.** The
    identity strip needed format strings, and `limb` and `region` are values the software holds
    in English (`left`, `primary`) that were being interpolated untranslated into Swedish
    sentences. `terms:` maps them. The Swedish region words are inflected to fit
    `"{region} zonen"`.

23. **The participant window handles keys whenever the VAS is not showing.** An emergency stop
    that only works during a rating is not an emergency stop (SPEC.md 13). Off the VAS the
    window holds focus, emits `emergency_stop` for that key and swallows everything else,
    `escape` included — Qt would otherwise read it as "close this window" (SPEC.md 10.1).

24. **An emergency stop during a trial writes no `pinprick` row.** No rating was given, so
    there is nothing to record in the rating columns and no honest value for them. The `log`
    carries the event with its timestamp and the trial index, so what happened is recoverable.
    What the *session* does next — resume, discard, abort — is a session-level decision and is
    not in the trial.

25. **`garment_driver` added to `experimenter_view()`.** SPEC.md 11 wants hardware status, and
    the reduced-capability banner of SPEC.md 12.4 names the device in its `{value}`.

26. **The experimenter window has no refresh timer.** It redraws when the caller calls
    `refresh()`, which the trial does at each step. The ticking clock and the countdown to the
    next scheduled event are Milestone 5, and that is where the timer belongs — a timer interval
    here would be a timing literal with no home in config yet.

---

## What session 5 fixed

- **Two config files did not parse.** `config/open_items.yaml` and
  `config/text/experimenter_en.yaml` had prose values containing an unquoted `key: value`,
  which YAML reads as a nested mapping. The Swedish experimenter file quotes the same four
  strings; the English one had lost the quotes. `tests/test_config_files.py` now parses every
  YAML file under `config/`, including the pattern sidecars that `config.load` never touches.
- **The last stray tooling artefact from session 1** — an `</invoke>` tag on the final line of
  `docs/DATA_SCHEMA.md`. A search across the tracked text files shows no others remain.
- **`config/allocation.csv` generated and committed**, which unblocked config loading. This
  closes SPEC.md 20 item 10.
- **ruff made clean** across the repository.

---

## Next steps, in order

**Milestone 1 is complete.** `run_session.py` runs one anchor adjustment, one touch intensity
rating, then sets session t=0 and runs one pinprick application inside intervention block 1
against the mock garment, writing `touchcal_adjust`, `touch_ratings`, `pinprick`, `garment`,
`log` and `session`. Every layer is touched by one thin path.

Two things the schedule work fixed that were not on anyone's list: `start_sensitisation` was
never called, so **every row the slice wrote had an empty `t_session_s`**; and the generated grid
put block 7 exactly on the rekindle, which nothing would have found until someone read a
timeline. `make preview` is what found it.

1. Run the **spec-review** agent, then commit Milestone 1
   ("Use the spec-review agent to review this diff against docs/SPEC.md").

Then in **Milestone 3**, when the ladder exists: the intolerable cap of `SPEC.md` §8.2 —
per site, per time point, escalating to all sites at
`pinprick.intolerable_sites_for_global_cap`. The flag is written today; nothing enforces it yet.
The experimenter's substitution control belongs there too, for the same reason.
2. **Milestone 2, what is left**: `tools/validate_session.py` (SPEC.md 17.3) and the
   `sim/responders.py` virtual participant it needs (17.5). Then delete the `check` target's
   INCOMPLETE GATE line. The literals test, the forbidden-terms test and the screenshot
   comparison landed in session 10 and are in the gate.

   **The validator will not be able to assert everything SPEC.md 17.3 lists.** Row counts
   matching the schedule and every scheduled block appearing in order need all twelve blocks,
   which is Milestone 5. Build it against what the slice actually does today and add each
   assertion as the thing it checks starts existing — do not write assertions that pass because
   there is nothing to check.
3. Run the **spec-review** agent before declaring Milestone 1 done
   ("Use the spec-review agent to review this diff against docs/SPEC.md").

## Watch out for

- The `PreToolUse` hook rejects `&&`, `||`, `;`, `|`, `$(`, backticks and newlines **even
  inside a quoted string** — including inside a `git commit -m` message, which is easy to trip
  over. Put throwaway code in a file under `tools/`, not in `python -c`, and not in `/tmp`: the
  hook also refuses absolute paths outside the repository, which includes the session
  scratchpad.
- `mkdir` is not on the allow list. `DataFileCollection` creates its own folder, which is the
  right place for it anyway.
- **A `QObject` protocol object with no parent is collected the moment nothing holds it**, and a
  collected object silently stops answering the participant's buttons. Two tests failed this way
  before the reference was bound. `SliceRunner` holds each of its three.
- **Targeted test runs go through `make test-one ARGS="..."`.** `conda run --no-capture-output …`
  typed directly does not match the allow-list prefix, and the bare `conda` shell function is
  broken in this environment (see Environment above). The Makefile is the only place the
  environment is named.
- Directory permissions do not stop an append to an existing file. If you are testing the
  data-write failure path, chmod the *file*, not the folder.
