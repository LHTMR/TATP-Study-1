# TATP Study 1 — experiment control software

Read `docs/SPEC.md` before writing any code. It is the authoritative specification. Read
`docs/calibration_methods_comparison.md` before touching either calibration procedure — the
design is settled there and should not be re-derived.

TATP = **Touch Away The Pain**. Not "ttpa".

## Environment

Conda, declared in `environment.yml`, env name `tatp-study-1`.

```
conda env create -f environment.yml
conda activate tatp-study-1
```

Add a dependency by **editing `environment.yml` and running
`conda env update -f environment.yml --prune`**. Never `conda install` or `pip install` — an
ad-hoc install is invisible in the diff and will not exist on the lab PC. The Makefile targets
run through `conda run -n tatp-study-1`, so they work whether or not the env is active.

## Commands

```
make check          # the gate: unit tests, end-to-end validator, screenshot comparison
make test           # unit tests only
make validate       # end-to-end validator only
make shots          # regenerate screenshots and compare against approved references
make preview        # print the session schedule and any warnings
```

`make check` must pass headless, with no hardware attached. Nothing is done until it does.

## Hard rules

- **One shell command per Bash call.** No `&&`, `||`, `;`, `|`, `$(...)` or backticks. A hook
  enforces this; the rule is here so you do not fight it.
- **Never write outside this repository.** Not to OneDrive, not to a home directory, nowhere
  else on the machine.
- **Never commit participant data.** `data/` is gitignored. If you find data in a commit, stop
  and say so.
- **No literals in task code.** Timings, forces, pressures, thresholds, rates and every
  user-facing string live in `config/`. A numeric literal in `tatp/pinprick.py` or
  `tatp/touchcal.py` should be an array index or a unit conversion, nothing else.
- **Fail fast.** No broad `try`/`except`. Let exceptions propagate. The single exception is the
  data-write path, which must never lose an already-collected trial.
- **Never substitute mock, synthetic, fallback or empty data for real data.** If something
  required is missing, stop and ask.
- **Assert at stage boundaries** — after loading config, after reading the allocation file,
  after each calibration, before each garment command.

## Style

- PEP 8. `snake_case` for functions and variables, `CapWords` for classes,
  `UPPER_SNAKE_CASE` for constants. No separate convention for functions versus variables.
- Comments explain **why**, not what.
- Minimal code. No abstraction used once. No config option nothing reads.
- Units in names: `isi_min_s`, `pressure_max_kpa`, `force_mn`.

## Blinding — a study requirement, not a preference

Nothing shown to the participant may state or imply that touch is expected to relieve pain,
name the research environment, or distinguish one condition from another. **The condition is
hidden from the experimenter screen as well** — recorded in the data, never displayed.
`docs/SPEC.md` §16 has the constraints and the tests that enforce them.

## Subagents

Use one when the answer needs many files read but only the conclusion matters.

Do **not** use subagents to write the implementation. Edits belong in the main session so they
land in one reviewable diff and the reasoning stays connected. Always give a subagent a specific
question, and tell it to return findings rather than file contents.

**A subagent protects context, not budget.** Its work happens in a separate window and only its
final message comes back, so the files it reads never touch this conversation. But its tokens
count against the same usage limits. Delegating is not a way to economise — if you are near a
limit, stop and commit (see below) rather than spawning helpers.

**The lever that matters is scope, not model.** One precisely-scoped question costs less and
returns more than three broad ones. Downgrading the model on a vague task just buys a cheaper
wrong answer.

| Use | Model | `maxTurns` | Why |
|---|---|---|---|
| Extract a convention or protocol detail from a reference repo | `haiku`, or `sonnet` if the protocol is intricate | ~10 | Bounded retrieval, and the answer is verifiable at a glance |
| Investigate a failure spanning several modules | `sonnet` | ~25 | Real diagnosis, but the hypothesis comes back here to be checked |
| **Adversarial review at each milestone** | **`inherit` — never downgrade** | ~40 | Last line of defence. A weak reviewer produces false comfort, which is worse than no review |

Invoke the reviewer by name: **"Use the spec-review agent to review this diff against
docs/SPEC.md."** It is defined in `.claude/agents/spec-review.md`, so the criteria stay the same
at every milestone instead of depending on how it is prompted. Run it at every milestone in
`docs/SPEC.md` §18 before committing, and again before declaring the build done.

Where a subagent's model is not pinned in its definition it inherits this session's, which is
the right default — downgrade deliberately, not by habit.

## Committing

- Work on `main` during the initial build — the repository is new and nothing depends on it.
  Branch once there is a pilotable version worth protecting.
- **Commit at every milestone in `docs/SPEC.md` §18 with `make check` passing**, and commit
  smaller working increments in between.
- **Never end a session with the repository broken.** If something is half-finished, either
  finish it, or revert it and note it in `PROGRESS.md`.
- Message says what changed and why, and names the milestone.
- Do not push. `git push` is denied; S pushes.

## Sessions, context and limits

Context is the constraint that governs everything else. The way to survive it is to keep the
state on disk rather than in the conversation, so that any fresh session can pick up.

- **`PROGRESS.md` is the handover file.** Keep it current: what is done, what is in flight,
  what is next, and any decision taken that is not already in `docs/SPEC.md`. Update it at
  every milestone and before stopping for any reason.
- Between `docs/SPEC.md`, `PROGRESS.md` and the git log, a new session should need nothing
  from the previous conversation.
- `/clear` between unrelated tasks. A long session carrying failed approaches performs worse
  than a fresh one with a better prompt.
- Prefer a targeted grep to reading a whole file. Do not re-read a file already read this
  session, and do not paste file contents into a message to summarise them.
- Delegate file-heavy exploration to a subagent so the reading happens in its context.
- **Approaching a limit: stop cleanly rather than getting cut off.** Finish the current unit of
  work, run `make check`, commit, update `PROGRESS.md`, and say where you stopped. Do not start
  a milestone you cannot finish, and do not delegate to a subagent to stretch the session —
  that spends the same budget faster.
- After a compaction, re-read `PROGRESS.md` and `docs/SPEC.md` §18 before continuing — the
  summary will not have kept the detail.

## Working style

- IMPORTANT: build in vertical slices. One thin path through every layer that runs end to end,
  then widen. Do not build one layer completely before starting the next.
- Anything in `docs/SPEC.md` §20 that is still unresolved stays a clearly-marked placeholder
  that warns at startup. Never quietly default it.
