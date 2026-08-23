# FOR_S — what needs you

**One list: values and decisions only you can supply, that the build cannot settle by itself.**
Nothing else belongs here. Reviews of what I wrote, deviations from Bilaga 1, pilot-protocol
checks and analysis-plan questions are logged in `docs/NOTES.md`, and build state is in
`PROGRESS.md` — ask me about either when you review.

**Nothing here blocks writing code.** Each item is carried as a marked placeholder that warns at
startup, listed in `config/open_items.yaml`. If something genuinely blocks the build I stop and
ask instead of parking it here.

The **Gate** column says when an item stops being deferrable. **Ref** is the `SPEC.md` §20 item,
or the `Ln` raised during the build.

| Gate                 | Meaning                                                                                  |
| -------------------- | ---------------------------------------------------------------------------------------- |
| **Real participant** | The software runs, but a session collected without this is unusable. `blocks_use: true`. |
| **Piloting**         | Needed to get useful answers out of the pilot, not to run it.                            |
| **Bring-up**         | Belongs to the hardware bring-up session (`SPEC.md` §18.2).                              |

---

## Safety and hardware limits

| #    | What                                                                                                                                                                                                                                                                                                          | Gate             | Ref    |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------ |
| A2.2 | **Pressure rate limit.** 60 kPa/s, chosen only to sit just above the 50 kPa/s top adjustment rate of §10.3. Same situation.                                                                                                                                                                                   | Real participant | L2     |
| A2.3 | **Two things, now that the participant sets their own noise level (SPEC.md 10.7).** (a) **Fix the system output volume at bring-up and record it.** dBFS says nothing about sound pressure until it is fixed, so `white_noise_max_dbfs` is a stop on the software, not yet a safe level — set the OS volume once, meter it, and never change it. (b) **The experimenter alert must still be inaudible to the participant** at the *lowest* level any participant settles on, which is the worst case; that one is a meter check. (c) **Earplugs in the room.** §10.7 step 5 tells the experimenter to offer them when the noise cannot mask the garment, so they have to be a stocked consumable. Wording approved 23 Aug 2026. | Real participant | L3     |
| A2.4 | **Screen indices and resolutions** for the lab PC. Null means "primary screen, windowed" — right for development, wrong for a session.                                                                                                                                                                        | Real participant | §20.9  |
| A2.5 | **Garment pressure resolution.**                                                                                                                                                                                                                                                                              | Bring-up         | §20.2  |
| A2.6 | **Inflation rate per channel.** Sets pattern activation durations and decides whether the 3 s static match transfers to the moving pattern.                                                                                                                                                                   | Bring-up         | §20.3  |
| A2.7 | **Serial protocol for the proportional-valve controller.** The prototype carries a bitmask, which cannot express a per-channel pressure — a protocol change to agree with whoever builds the controller, not a driver change. `arduino_valves.py` waits on it.                                                | Bring-up         | §20.14 |
| A2.8 | **Physical labels on the response-box buttons.** Every participant screen writes confirm as ▶. If custom labels can be printed, the screens should match what is printed.                                                                                                                                     | Bring-up         | —      |
| A2.9 | **Confirm the conda env builds on the Windows lab PC.** `environment.yml` needed `sounddevice` → `python-sounddevice` (the conda-forge name); verified only on this Mac.                                                                                                                                      | Bring-up         | —      |

## Measurements and study parameters

| #    | What                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Gate             | Ref           |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------- |
| A3.1 | **Measured filament forces, weighing date and balance.** You weigh; the instruments module (launcher entry 2) writes them into `filaments.yaml`. Manufacturer forces deviate from measured by −19.75 % to +17.61 % non-systematically, so an unweighed set runs flagged.                                                                                                                                                                                                                                                                                  | Real participant | §20.1         |
| A3.2 | **Real intervention patterns**, plus per-channel activation duration, overlap between consecutive activations, and the inter-channel spacing if it is not 1.5 cm. The three sweeps in `config/patterns/examples/` are provisional mockups.                                                                                                                                                                                                                                                                                                                | Real participant | §20.5, §20.13 |
| A3.3 | **Measured block durations, from pilot timings.** The grid is settled and clash-free at 8 min spacing — 55, 63, 71, 79, 87, 95, rekindle 105–110, 117, 125, 133, 141, 149, 157 (`make preview`) — with blocks *estimated* at 4 min each. What is left is replacing the estimate with what a block really takes; the session records that on every block, so the pilot produces it for free. Set `generate.settled: true` once confirmed. | Piloting         | §20.4         |
| A3.4 | **Slope prior**, re-estimated from pilot data **pooled across participants, never per participant**. 51.6 VAS points per log₁₀ unit is a simulated starting value.<br/><br/><br/>S: we may not get enough pilot data to get a better estimate, in which case we go the simulated starting value which was based on literature.                                                                                                                                                                                                                            | Piloting         | §20.6         |
| A3.5 | **Expected pre-S → post-S offset** for the informed prior. −2.7 ladder steps from Scheuren et al.; confirm against pilot data.<br/><br/>S: we may not get enough pilot data to get a better estimate, in which case we go Scheuren's value.                                                                                                                                                                                                                                                                                                               | Piloting         | §20.7         |
| A3.6 | **Duration of one touch adjustment.** Decides whether the Protocol B time budget holds and which of schemes A/B/C is right.                                                                                                                                                                                                                                                                                                                                                                                                                               | Piloting         | §20.8         |
| A3.7 | **A proper hyperalgesic-zone figure** to replace `assets/hyperalgesia_zones.svg`. Explicitly not blocking.                                                                                                                                                                                                                                                                                                                                                                                                                                                | —                | §20.11        |

---

## How this file is written

- **Only items awaiting you.** An item appears here when I would otherwise have to guess a value
  or invent a wording. Anything I merely want you to look at goes in `docs/NOTES.md`.
- **A row exists in three places or none:** a `PLACEHOLDER`/`null` in `config/`, an entry in
  `config/open_items.yaml` with a `resolved_when:` path, and a row here.
- **Resolved means deleted**, in the same commit as the config change that resolved it. The item
  keeps its history in `PROGRESS.md` if it changed a decision; there are no struck-through rows.
- **IDs are never reused or renumbered**, so `A3.4` means the same thing in a commit message a
  month from now. New items take the next free number in their section.
- **One or two sentences a row.** The reasoning belongs in `SPEC.md` or the ethics folder.
