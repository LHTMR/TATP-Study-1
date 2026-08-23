# Example patterns

**Provisional.** Placeholder channel IDs and an arbitrary overlap. Real patterns come from the
hardware bring-up session — see `docs/SPEC.md` §12.2 and open items 3, 5 and 13 in §20.

## Format

Same as `LHTMR/ttpa_touch_the_pain_away`: first row is the channel IDs, every later row is one
time step, 1 for on and 0 for off. Human-readable and human-editable, which is the point.

Each `.csv` has a sidecar `.yaml` carrying **`row_interval_ms`** — the duration of one row. It
is a per-pattern value, not a fixed 100 ms, so any velocity is expressible. The driver's
`col_ms` argument takes it.

**Overlap** is written into the grid: a channel stays on for one or more rows after the next
one starts. Apparent motion generally needs some overlap; how much is a parameter to settle in
piloting. The examples in the original repo have none, which was arbitrary test data rather
than a design decision.

**Looping** is on by default (`loop: true`); a pattern repeats for as long as it is active,
including throughout the pleasantness adjustment.

## The three examples

Five channels, assumed 1.5 cm apart, one row of overlap.

| File | `row_interval_ms` | Leading-edge velocity | Onset span | One sweep with tail |
|---|---|---|---|---|
| `sweep_01cms` | 1500 | 1 cm/s | 6.0 s | 9.0 s |
| `sweep_03cms` | 500 | 3 cm/s (CT-optimal) | 2.0 s | 3.0 s |
| `sweep_20cms` | 75 | 20 cm/s | 0.3 s | 0.45 s |

Velocity is the leading edge travelling 6 cm across four inter-channel gaps. The sweep is
longer than the onset span by the trailing channel's own duration.

Note the 75 ms interval: it is below the driver's 100 ms default, which is why the interval has
to be a per-pattern parameter rather than a constant.
