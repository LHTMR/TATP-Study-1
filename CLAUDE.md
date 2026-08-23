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

## Reach for a tool before a shell command

Most of what a shell command is normally used for here has a dedicated tool that is safer,
faster and needs no permission prompt. **Use the tool where it exists.** A shell command is for
things that genuinely have no tool: running the test suite, git, conda.

| To do this | Use | Not |
|---|---|---|
| Read a file, or part of one | `Read` | `cat`, `head`, `tail`, `less` |
| Change a file | `Edit` / `Write` | `sed -i`, `perl -i`, `tee`, `>` |
| Find files by name or glob | `Glob`, else `ls` / `git ls-files` | `find` |
| Search file contents | `Grep`, else `grep -rn` | `awk`, `find -exec grep` |
| Explore across many files where only the conclusion matters | a subagent | a pipeline |

**`Glob` and `Grep` are not present in every session.** When they are missing, `ls`,
`git ls-files` and `grep -rn` are allowed and are the fallback — that is why `grep` and `rg`
are on the allow list while `find` is denied. `git ls-files` is usually the better of the three
anyway: it lists exactly the tracked files and never descends into `data/`.

The deny list refuses `find`, `sed`, `awk`, `perl`, `tee`, `xargs` and the shell wrappers
(`bash -c`, `sh`, `zsh`, `env`, `eval`, `exec`, `nohup`, `time`, `watch`) outright. Those are
not arbitrary refusals: each is a way to run something the permission patterns would otherwise
have matched and refused — `find -delete` deletes without invoking `rm`, `bash -c "…"` hides the
real command inside a string. Denying the wrapper is what makes denying the wrapped thing mean
anything. Same reason for `cp`, `ln`, `dd`, `truncate`, `unlink`, and for `git checkout` /
`git restore` / `git config` (they discard uncommitted work or rewrite tool behaviour — use
`git switch` to change branch).

**One known hole, stated rather than papered over:** `conda run … python` can execute anything,
and the Makefile needs it. It is narrowed to the four forms the Makefile actually uses
(`python -m pytest`, `python -m tatp`, `python tools/…`, `python run_session.py`) rather than
allowed wholesale. An ad-hoc `python -c` will prompt, which is the right outcome.

## Hard rules

- **One shell command per Bash call.** No `&&`, `||`, `;`, `|`, `$(...)` or backticks. A hook
  enforces this; the rule is here so you do not fight it. The hook rejects those characters
  even inside a quoted string, so `python -c "a=1; b=2"` is refused too — put the code in a
  file under `tools/` instead of fighting the quoting.
- **Write the command so the permission rule can match it.** The rules in
  `.claude/settings.json` match a command *prefix*, so anything in front of the real command
  breaks the match and prompts:
  - **No environment-variable prefix.** Not `QT_QPA_PLATFORM=offscreen pytest`. Set the
    variable in `tests/conftest.py` or in the tool itself. (`env` is denied anyway.)
  - **No `git -C <path>`.** The working directory is already the repository root, so plain
    `git status`, `git add -A`, `git commit` are both shorter and matchable.
  - Prefer `make check` over its parts. Subprocesses a Makefile spawns are not
    permission-checked, so the Makefile is the right home for the env vars and the
    `conda run` invocations.
- **Never write outside this repository.** Not to OneDrive, not to a home directory, nowhere
  else on the machine. This includes the session scratchpad: the hook resolves every absolute
  path in a command and refuses any that lands outside the repo, so temporary scripts go in
  `tools/`, not `/tmp`.
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
- **`FOR_S.md` is S's queue.** See below — update it in the same breath as `PROGRESS.md`.
- Between `docs/SPEC.md`, `PROGRESS.md`, `FOR_S.md` and the git log, a new session should need
  nothing from the previous conversation.
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

## `FOR_S.md` — the queue of things the build cannot settle by itself

`PROGRESS.md` is for the next session. **`FOR_S.md` is for S**, and it is the only file S
should have to read to know what is waiting on them. Keep it current or it becomes actively
misleading — a stale queue is worse than no queue, because it gets trusted.

Two lists, and the distinction is load-bearing:

- **List A — things only S can supply.** A value, a wording or a decision from outside the
  repository. Measured forces, participant text, a pressure limit, a serial protocol.
- **List B — things that need S's attention.** No input to me. Reviews of what I wrote,
  alignments between Bilaga 1 and the implementation, analysis-plan decisions, process.

**The three-places rule.** Any time you would otherwise guess a value, invent a wording, or
default something the spec does not fix, do all three of these or none:

1. Leave a **clearly-marked placeholder** in `config/` — `null`, or a string prefixed
   `PLACEHOLDER`. Never a plausible-looking constant.
2. Add an entry to **`config/open_items.yaml`** with a `resolved_when:` path, so the startup
   warning is automatic rather than remembered. Items the spec does not number get `Ln`.
3. Add a row to **`FOR_S.md`**, in the right list, with the gate at which it stops being
   deferrable.

Doing one or two of the three is how a guess ends up in the study. `open_items.yaml` is the
machine-checked list and `FOR_S.md` is the human-readable one; **they must never disagree.**
When an item's `resolved_when:` path stops being null, delete its row from `FOR_S.md` in the
same commit.

Only genuinely non-blocking things belong in `FOR_S.md`. If something blocks the build, the
rule above it applies instead — **stop and ask.** Do not park a blocker in a list and carry on.

## Working style

- IMPORTANT: build in vertical slices. One thin path through every layer that runs end to end,
  then widen. Do not build one layer completely before starting the next.
- Anything in `docs/SPEC.md` §20 that is still unresolved stays a clearly-marked placeholder
  that warns at startup. Never quietly default it — see the three-places rule above.
