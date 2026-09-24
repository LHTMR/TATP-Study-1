# SOP: running a Study 1 session

The standard operating procedure for running one session with the study software. It is for the
experimenter in the lab, on paper or on a second screen.

- You are expected to know the study protocol (Bilaga 1). This document tells you how the
  software runs it.
- Words in **bold** are exactly what the screen shows: a button, a field or a message.
- **[TBC: …]** marks a step the software and Bilaga 1 do not settle yet. Ask S before the
  session if one of them affects you.

A session takes about three hours. The software guides you through every phase in order and never
skips one. **It times the phases; you launch each one.** Nothing starts until you press a button.

---

## 0. Two rules that apply all the time

**Ratings are not shown to you.** The participant rates on their own screen, behind the curtain.
Your screen says only **Waiting for the participant's response.** and then **Response received.**
It never says what the rating was. (The one exception is the fit preview, section 12.3.)

**You are blind to the kind of touch.** Three kinds of touch are used in the study, one per visit.
The software chooses which one from the allocation file and records it in the data. It never shows
it on your screen, and this SOP does not describe them. If you notice that the touch feels or
sounds different from another visit, that is expected, and it is not a fault. Do not mention it to
the participant, and do not try to work out which one it is.

What you may say to the participant about the study is set by Bilaga 1 §3.3 and the participant
information sheet. The study is framed as investigating **touch and pain sensation together**, and
pleasant and unpleasant bodily sensations. The participant may be told that there are three
different kinds of touch, one per visit, and nothing more. **Never say or suggest that the touch
is expected to reduce pain, and never name the research programme.** Do not describe one visit's
touch as different from another's.

To keep the blind:

- Do not open the data files during a session, or at any time before S says so. They record which
  kind of touch was given.
- Do not open the pattern folder or look at the file names in it.
- Do not open **Design a pattern** in the launcher. It is S's tool for making the patterns, and
  it shows their names and shapes. If you find it open, close it without reading it.

---

## 1. Before the day

### 1.1 The lab PC

1. Check that the software is installed and up to date (`docs/SETUP.md`, "Keeping it up to date").
   Pull any update S has announced.
2. Check that both displays are connected: the participant's display behind the curtain, and the
   lab display for you.
   **[TBC: until open item 9 is set, both windows open on the main display, in a window,
   and not full screen on the participant's display.]**
3. Check that the participant's headphones and the lab-side speaker are connected.
   **[TBC: which output is which (open item L10). Until it is set, the lab-side alerts may
   play through the participant's headphones.]**
4. Open the launcher (section 2.1) and choose **Preview schedule**. Read the timeline and any
   warnings. This starts nothing.

### 1.2 Equipment

Have all of this within reach before the participant arrives.

| Item | Used in |
|---|---|
| The monofilament kit, every filament listed in `config/filaments.yaml` | Pain measures, mapping |
| The soft goat-hair brush | Brush measures |
| The thermode (TCS II with the T09 probe), switched on and programmed separately. The software sends it nothing | Sensitisation, rekindle |
| 0.075 % capsaicin cream, with what you need to apply and remove it | Capsaicin |
| A skin pen and a ruler in mm | Marking the sensitised area, mapping |
| Earplugs | Audio setup, if needed |
| Headphones for the participant | Audio setup onwards |
| The participant's remote (Logitech R400) | The whole session |
| The actuating garment and its supply | Setup onwards |
| The paper pain drawing | Start of the session (Bilaga 1 §3.3) |

**[TBC: the capsaicin application and removal materials, and where the hardware stop
button and the rapid depressurisation release are for the garment in use.]**

### 1.3 Weighing the filaments: Launcher, then Instruments and environment

Do this when the filament set is new, and again whenever S asks for it. Until it is done, the
software uses the manufacturer's forces, and the open items line shows item 1.

1. Weigh each filament on the precision balance.
2. Open the launcher and choose **Instruments and environment**.
3. In **Filament forces**, type each filament's measured force in mN in the **Measured (mN)**
   column. Filaments are identified by the **Label (g)** printed on them.
4. Type the **Weighing date (YYYY-MM-DD):** and the **Balance used:**.
5. Press **Save forces**. The message **Saved … measured forces to filaments.yaml.** confirms it.

What the messages mean:

| Message | What to do |
|---|---|
| **Enter the weighing date before saving measured forces.** | Type the date, then press **Save forces** again. |
| **… is not a date in the form YYYY-MM-DD.** | Retype the date, for example `2026-09-24`. |
| **Filament … g: … is not a force in mN above zero.** | Correct that filament's value. |
| **No measured forces entered.** | Nothing was typed in the Measured column. |

Saving changes `config/filaments.yaml` on the lab PC.
**[TBC: who commits the changed filaments.yaml, so that the weighing is kept.]**

---

## 2. Starting a session

### 2.1 Open the launcher

1. Open PowerShell in the repository folder and activate the study environment, as in
   `docs/SETUP.md` step 8.
2. Run `python run_session.py`.
3. The launcher opens with four entries: **Run a session**, **Instruments and environment**,
   **Design a pattern** and **Preview schedule**. **Design a pattern** is for S only: do not
   open it (see "To keep the blind" above). Starting a session closes it if it was left open.

### 2.2 Before you open the session dialog

Do these with the participant, as Bilaga 1 §3.3 asks. They are recorded outside this software.

1. Confirm that the participant has no pain today and has not taken painkillers. If either is
   not the case, the session is rescheduled.
2. Record the session details the study collects in REDCap (nicotine use, menstrual cycle, as
   relevant). At the first visit, measure height and weight.
3. Have the participant complete the paper pain drawing.

**[TBC: SPEC.md §1.2 says the software records that the REDCap session form was
completed. It does not do this yet. Write a note (section 11.4) until it does.]**

### 2.3 Room temperature and humidity (optional)

1. In **Instruments and environment**, fill in **Room temperature (°C):** and **Relative humidity
   (%):** under **Room environment (optional)**.
2. Press **Use for the next session**. The launcher shows **Room … °C, … % RH, handed to the next
   session.**

They are kept only until the launcher closes, and a session runs without them.

### 2.4 The Run a session dialog

1. Choose **Run a session**.
2. Fill in every field. Nothing is filled in for you except the data folder.

   | Field | What to enter |
   |---|---|
   | **Participant code** | The code from the allocation file, for example `07`. Never a name. |
   | **Session number** | This visit: 1, 2 or 3. |
   | **Experimenter initials** | Yours. Use the same ones at every visit. |
   | **Participant language** | The language the participant reads: Svenska or English. |
   | **Experimenter language** | The language you want your screen in. |
   | **Data folder** | Leave it as it is (`data`) unless S says otherwise. |
   | **Pattern folder** | The folder S has named for the study. There is no default. **[TBC: the pattern folder path for real sessions (open item 5).]** |

3. Press **Check**. The software checks the session before anything is written, and lists what it
   found under the buttons.
4. Read the result (section 2.5).
5. If nothing refuses, **Start session** becomes available. Press it.

If you change any field after **Check**, **Start session** greys out again. Press **Check** again.

### 2.5 What Check can say

**Refusals, in red, under The session cannot start:**

| Message | What to do |
|---|---|
| **Required: …** | Fill in the fields named, then press **Check** again. |
| **Participant code … is not in the allocation file. Check the code.** | The code is mistyped, or that session number does not exist for the participant. Check both against the participant's record. |
| **Session … for this participant has already been completed. It will not be run again.** | The session number is wrong, or this visit has already happened. Check the participant's record. Do not try to get round it. |
| **Another session is already running from this data folder (…). Close it first.** | Another copy of the software is open. Find it and close it. If none is open, see section 14. |

**Warnings, in amber, under Warnings. The session can start, and each is recorded:**

| Message | What it means and what to do |
|---|---|
| **These initials differ from earlier sessions for this participant. …** | Bilaga 1 §3.3 asks for the same experimenter at every visit. If you mistyped your initials, correct them. If a different experimenter is running this visit, carry on. The deviation is recorded. |
| **No data was found for session … of this participant. …** | The previous session's files are not in this data folder. Check the session number. If it is right (for example, session 1 was run on another PC), carry on. The first calibration then starts from the configured filament. |
| **Session … of this participant has no accepted pre-sensitisation estimate. …** | The previous session did not finish its first calibration. Carry on. The first calibration starts from the configured filament. |
| **Session … for this participant was started before and aborted. A new session will be recorded alongside it.** | An earlier attempt at this visit was aborted. Carry on only if this is a new attempt S has agreed to. |

### 2.6 The resume offer after a crash

If the software stopped unexpectedly during this participant's session, **Start session** asks
first:

> An unfinished session was found for this participant. Completed: …. Sensitisation began … ago.
> Resume it, keeping the original timing?

- **Resume the session** carries on the session that crashed. **Choose this after a crash.**
  Section 12.5 says what it does.
- **Start a new session** starts again from setup. The crashed session's files are kept. Choose it
  only if S agrees. Once capsaicin has been applied, a fresh start cannot be run as the protocol
  intends.
- Closing the question starts nothing.

### 2.7 Starting from the command line (for S, or when S asks)

```
python run_session.py --participant 07 --session 1 --experimenter SM --patterns <pattern folder>
```

It runs the same checks. Refusals and warnings are printed, and a refusal stops it. If a crashed
session is found it stops and asks you to add `--resume` or `--new`. Never use `--clock-speed`
for a real session: it speeds up every interval, and is recorded as a development run.

---

## 3. The session screen

Your window reads top to bottom:

1. **Banners**, if any (section 13).
2. **Who and where**: **Participant …**, **Session …**, **Target limb: …** and
   **Experimenter …**.
3. **The phase**, the countdown to the next scheduled event, and **Session elapsed …**.
4. **An interruption line**, when the session is paused or stopped.
5. **What to do now**, in large type. The status line under it says whether a response is awaited
   or received, and any warning.
6. **The zone diagram**, with the zone and site for the current stimulus, and **Garment** with its
   connection state and the **Disconnect garment** / **Connect garment** button.
7. **The buttons** (section 11), then the note, substitution and mapping entries.

**Start block** is the go button for everything, not only blocks. Press it whenever the
instruction says to press Start block.

**The remote always works, whichever window you last clicked.** Its presses go to the
participant's screen even while your own window is active. The exception is while you are
typing in a text field (a note, a substitution or a distance): then the participant's presses go
into that field instead. Finish typing and press Enter before the participant needs to respond.

---

## 4. Setup

The phase shows **Setup**. Nothing is being measured yet.

### 4.1 Fit the garment

1. Seat the participant with the target arm (**Target limb: …**) on the armrest, behind the
   curtain.
2. The screen shows **Fit the garment and confirm all five channels are seated.**
3. Fit the garment. Check that all five channels are seated.
4. Give the participant the remote and show them the buttons: the two large buttons move the
   marker left and right, and the play button confirms.
5. Put the headphones on the participant.
6. Press **Start block**.

**[TBC: when and how the hardware stop button and the rapid depressurisation release are
shown to the participant (Bilaga 1 §3.10). The software rehearses only the software stop.]**

### 4.2 Welcome

1. The participant's screen shows the welcome text. Your screen shows **Waiting for the
   participant's response.**
2. The participant reads it and presses play. The session moves on by itself.

### 4.3 Audio setup: the masking check

The participant sets their own white-noise level against the sound of the garment. It takes a few
minutes.

1. The screen shows **Audio setup: the participant is setting the noise level against the
   garment.**
2. The participant works through it on their own screen: they find the noise, the garment starts,
   they raise the noise until it covers the garment, and they say whether they can still hear it.
   You do nothing unless the software alerts you.
3. **If an alert sounds and the status says:**

   > The participant can still hear the garment and the noise cannot be raised further. Offer
   > earplugs under the headphones. The noise has stopped so you can talk, and the check will
   > start again from the beginning once they are fitted.

   1. The noise and the garment have stopped. The participant's screen says the session is paused.
   2. Offer the earplugs. Fit them under the headphones.
   3. The instruction says **Fit the earplugs under the headphones, then press Start block.**
      Press **Start block**.
   4. The check starts again from the beginning.
4. **If the status says Still audible with earplugs. The session will continue and is recorded as
   not fully masked.**: nothing to do. The session carries on and the data records it. Write a note
   if the participant says anything about it.
5. The noise stays on at the participant's level from here on, except during the mapping and the
   earplug exchange.

### 4.4 The stop rehearsal

The participant presses the software stop once, for real, with the garment running. It takes
about a minute and a half.

1. The screen shows:

   > Stop rehearsal: the participant will now press the stop button. When the stop screen shows,
   > press Resume. Press Start block only if they cannot press it.

2. The participant's screen asks them to press the stop button. It is the remote's blank-screen
   button.
3. When they press it, the garment stops. Your screen shows the red line **EMERGENCY STOP. The
   garment is at zero. Press Resume when the participant is ready.** and the instruction **The
   stop was detected. Press Resume to carry on in front of the participant.**
4. Press **Resume**. The garment restarts, after the warning cue, and the participant sees that
   the session has carried on.
5. The participant reads the next screen and presses play.
6. **If the participant cannot press it**, press **Start block**. The rehearsal ends and is
   recorded as not pressed.

**[TBC: open item L11. Until the rehearsal pressure is set, the garment is started with no
pressure, so the participant sees the stop and the resume without feeling the touch stop. Open
item L12: the stop button is drawn on the participant's screen as a red circle, a placeholder
until the symbol printed on the remote's blank-screen button is confirmed.]**

---

## 5. Touch calibration

The phase shows **Touch calibration**. The participant sets and rates the touch from the garment
on their own screen. You watch, and answer only when the software asks you to.

**[TBC: how long it takes (open item 8).]**

1. The instruction names each step as it runs:
   - **Touch calibration, step 1: the participant sets the touch on the middle channel.**
   - **Touch calibration, step 2: the participant rates a series of touches.**
   - **Touch calibration, step 3: the participant matches channel … to the middle channel.**
   - **Touch calibration, step 4: the participant compares channel … with the middle channel.**
   - **Touch calibration, step 5: the participant sets the most pleasant level.**
   - **Touch calibration: the participant is asked whether the movement feels even.**
   - **Touch calibration, step 6: the participant chooses a kind of touch.**

   Step 6 happens at every visit.

2. **When the software asks you to decide:**

   | Instruction | What to do |
   |---|---|
   | **The touch-calibration estimate failed its quality check (…). Re-run the procedure, or accept it to continue with the estimate flagged.** | Press **Re-run the procedure** to repeat steps 1 and 2, or **Accept this estimate** to carry on. A re-run asks for a reason, which is kept. **[TBC: when to re-run and when to accept.]** |
   | **The touch-calibration estimate cannot be used (…). Re-run the procedure, or abort the session.** | Press **Re-run the procedure**, or **Abort session** (section 11.3). **Accept this estimate** does nothing here. |
   | **The touch-calibration estimate cannot be used (…) and the re-run limit is reached. …** | Press **Accept this estimate** to carry on with the calibration recorded as not valid for analysis, or **Abort session**. |
   | **Channel … was matched at 0 kPa again. Rebalance to repeat the match, or proceed …** | Press **Rebalance channels** to repeat the match, or **Start block** to carry on with that channel recorded as not valid for analysis. |
   | **The participant reports the movement as uneven along the arm. Rebalance the channels, or proceed.** | Press **Rebalance channels** to go back to matching, or **Start block** to carry on. |
   | **The touch-calibration estimate is ready. Accept it, or re-run the procedure.** | Only with the fit preview on (section 12.3). |

   The words in brackets say what kind of failure it was: **flat**, **not rising with pressure**,
   **noisy**, **no range between the two settings**, **targets outside what the garment can
   deliver** or **no pleasantness range left inside the garment's limits**. They never show a
   rating.

3. **Status warnings you may see**, which need nothing from you:
   - **More than the allowed share of zero-pressure catch trials were reported as felt (…).**
   - **Channel … still does not match the middle channel after re-adjustment. The session
     continues and this is recorded.**

4. After calibration the garment stops, and the screen shows **Baseline: the participant rates how
   they feel right now.** The participant answers two ratings. Nothing to do.

Bilaga 1 §3.7 mentions pausing or recalibrating if comfort declines later in the session.
**[TBC: the software has no recalibration after this phase. Pause (section 11.1) is the
only option, and the session would need to be aborted to recalibrate.]**

---

## 6. Pre-sensitisation

The phase shows **Pre-sensitisation**. The measures run in this order:

1. The long protocol, secondary zone (section 10). The zone is not sensitised yet, so apply next to
   the area where sensitisation will be applied (Bilaga 1 §3.6.1).
2. The short protocol, primary zone, with the 26 g filament: five applications.
3. The brush, secondary zone: five strokes.
4. The brush, primary zone: five strokes.

Each measure begins with **Ready. Press Start block when the participant is ready.** Press
**Start block** when you and the participant are ready.

**[TBC: VAS training. Bilaga 1 §3.6.1 asks for it at pre-sensitisation. The software does
not present the training screens yet (STATUS.md), so how it is done until then is S's call.]**

---

## 7. Heat sensitisation

1. The screen shows **Start the thermode at 50 °C. The software times the phase and does not
   command the device.**
2. Place the thermode on the dorsal hand of the target limb.
3. Start the thermode programme (Bilaga 1 §3.5: 50 °C for 2 min, with brief drops to 32 °C every
   10.2 s).
4. **Press Start block at the moment the thermode starts.** That press is session time zero:
   every later time is measured from it, and **Session elapsed** starts counting.
5. Mark the sensitised skin area with the pen (Bilaga 1 §3.5).

## 8. Capsaicin

1. At 2 minutes the countdown shows **Capsaicin is due.** An alert sounds on the lab side about
   30 s before and again 60 s after the time. Section 13.3 describes the countdown.
2. The screen shows **Apply 0.075 % capsaicin.**
3. Apply the cream to the sensitised area and rub it in (Bilaga 1 §3.5). Press **Start block**.
   The phase changes to **Capsaicin**.
4. The countdown runs to 32 minutes. In between, the screen shows **Waiting for the next scheduled
   step. The countdown shows when it is due.**
5. At 32 minutes: **Remove the capsaicin, then press Start block to begin the post-sensitisation
   measures.** Remove it, then press **Start block**.

---

## 9. Post-sensitisation

The phase shows **Post-sensitisation**. This time point has the mapping. The order is:

1. The long protocol, secondary zone (section 10).
2. **The mapping** (section 9.1).
3. The short protocol, primary zone, 26 g.
4. The brush, secondary zone.
5. The brush, primary zone.

The intervention is due at 45 minutes. If the measures finish earlier, the software waits.

### 9.1 The mapping

The white noise is switched off for the whole mapping, so that you and the participant can talk.
It comes back on afterwards. The participant's screen shows the standby display.

1. Before the first path, the screen shows the script to read aloud:

   > Say aloud: "I will touch you with this filament, moving a small step at a time towards the
   > marked area. Tell me as soon as the feeling clearly changes — burning, tenderness, or a
   > sharper pricking."

   Read it to the participant.
2. The screen then says **Path … of 4. Press Start block to start the pacing cue, and again to
   stop it at the border.** The paths are **proximal**, **lateral**, **distal** and **medial**,
   in that order.
3. Place the 26 g filament (Bilaga 1 §3.6.2: 260 mN) on the path, well outside the sensitised
   area.
   **[TBC: how far out each path starts.]**
4. Press **Start block**. The screen shows **Map path …. Step inward 5 mm on each cue and stop
   when the participant signals.** A tick sounds once a second.
5. On each tick, apply the filament 5 mm further in.
6. When the participant says the feeling has clearly changed, press **Start block** again to stop
   the ticks.
7. Mark the border on the skin with the pen.
8. Repeat for the next path. After 40 ticks (200 mm), the path stops by itself.

### 9.2 The distances

**Measure each border from the centre of the primary zone, and enter the four distances in mm
whenever convenient. This never blocks the session.**

1. Measure each of the four marks from the centre of the primary zone, in mm.
2. Whenever you have a moment, press **Mapping distances…**. A window opens beside your screen.
   The session carries on behind it.
3. Choose the time point, if more than one is listed. The latest is chosen for you.
4. Type each distance next to its path. Either decimal mark works (`23,5` or `23.5`). Leave a field
   blank if you have not measured it yet.
5. Press **Enter distances**. You may enter some now and the rest later.
6. Press **Close** when done.

- **An implausible value.** A distance under 12.5 mm or over 200 mm is not accepted at once. The
  status says **Path …: … mm is outside the plausible range. Enter the same value again to confirm
  it, or enter the corrected value.** Check the measurement. Then press **Enter distances** again
  with the same value to confirm it, or type the corrected value.
- **A correction.** Entering a different value for a path already entered records the new one. The
  old one is kept in the data.
- **At the end of the session**, any distances still missing are asked for once (section 12.2).

---

## 10. The pain measures: what each application looks like

Used in every pinprick and brush measure: pre-sensitisation, post-sensitisation, each pinprick
block and post-intervention.

1. Press **Start block** at **Ready. Press Start block when the participant is ready.**
2. For each application:
   1. The screen names the stimulus: **Apply the … g filament (… mN) at site …, … zone.** or
      **Brush the … zone at site … -- one single stroke of about 2 cm.** The zone diagram outlines
      the zone.
   2. The participant sees a short warning cue. Apply the stimulus straight after it, at the site
      named.
   3. About 9 s later the participant's rating scale appears. Your status line says **Waiting for
      the participant's response.**
   4. When they confirm, it says **Response received.**
   5. The software waits 13 to 17 s, then names the next application.
3. **The site changes on every application.** Always use the site the screen names.
   **[TBC: where sites 1 to 8 lie on the skin. The zone diagram is a placeholder (open
   item 11).]**

The long protocol runs until the software has its estimate, up to 25 applications. The short
protocol and the brush are five applications each.

### 10.1 Monofilament technique

The screen shows it under the instruction whenever a filament is used:

> Approach perpendicular from about 3 cm. Bend the filament to about three-quarters of its extended
> length, hold for about 1 s, no lateral movement, then remove slowly. Keep the site out of the
> participant's view.

- Use the filament the screen names by its gram label, which is printed on it.
- Keep the site out of the participant's view. The curtain does this.

### 10.2 Using a different filament: substitution

You may use a **lighter** filament than the one asked for whenever you judge it warranted. The
software then fits the filament you actually applied.

1. Apply the lighter filament.
2. Before the participant confirms their rating, type its gram label in **Filament applied instead
   (g)**, exactly as printed on it (`2.0`, not `2`).
3. Press **Record filament**.

| Message | What it means |
|---|---|
| **No filament labelled … g is held. The substitution was not recorded.** | That label is not in the kit list. Check it and type it again. |
| **The … g filament is not lighter than the one asked for. It is recorded as applied.** | It was recorded. If it was a slip, write a note. |

### 10.3 Messages from the long protocol

- **The calibration ran out of ladder (…). The boundary filament will be used and the trial is
  flagged. Expect this in a meaningful fraction of sessions.** This is expected sometimes. Nothing
  to do.
- **The limit of … applications was reached. The best available estimate is used and flagged.**
  Nothing to do.

A rating at the top of the scale automatically stops the software asking for that filament or a
heavier one at that site, and at every site once several sites have reached it. You will not be
told. You will simply be asked for lighter filaments.

---

## 11. The buttons

### 11.1 Pause and Resume

- **Pause** stops the garment at once and shows the participant a paused screen. Your screen shows
  **Paused. The garment is at zero. Press Resume to continue.**
- **Resume** restarts the garment where it was, after a warning cue, and repeats the step that was
  interrupted.
- A trial that was interrupted is lost and repeated. Nothing already collected is changed.
- While the session is paused or stopped, only **Resume**, **Abort session** and the note entry
  work.

### 11.2 Discard and repeat last trial

Use it when a filament or brush stroke was delivered badly but the participant still rated it.

1. Press **Discard and repeat last trial** after **Response received.** and before the next
   application is named. That is the 13 to 17 s gap after a rating.
2. The status says **Last trial discarded. It will be repeated.** The discarded trial stays in the
   data, flagged.
3. If the application limit has been reached, it says **Last trial discarded. The application limit
   has been reached, so it will not be repeated.**

It is accepted only in pinprick and brush measures, and only in that gap. At any other time the
press is ignored and logged, and the screen does not change. There is no button to skip a trial.

### 11.3 Abort session

1. Press **Abort session** (in red).
2. The dialog says **Abort this session? All data collected so far is kept.**
3. Type the reason in **Reason for aborting**. **The Abort button stays greyed out until a reason
   is typed.**
4. Press **Abort session** to end the session, or **Cancel** to go back.

The reason is written to the data. An aborted session cannot be resumed.

### 11.4 Notes

Type in **Timestamped note** and press **Add note** (or Enter). The note is saved at once, with the
time. Write a note for anything unusual: what the participant said, a filament dropped, a
distraction in the room.

### 11.5 Disconnect garment and Connect garment

- **Disconnect garment** stops the garment and disconnects it. The session carries on and nothing
  is lost. **Garment** then shows **Disconnected** in red.
- **Connect garment** reconnects it. If the touch should be running, it restarts after the warning
  cue. During a block it restarts when the block ends.

**[TBC: when an experimenter should disconnect the garment deliberately.]**

---

## 12. The intervention, post-intervention and the end

### 12.1 The intervention

The phase shows **Intervention**. It lasts 120 minutes: twelve blocks, pinprick and touch-rating
alternately, with the rekindle in the middle.

1. At 45 minutes: **The intervention starts now. Press Start block to start the touch.** Press
   **Start block**.
2. The screen shows **Touch: the garment is being started.** for a few seconds. This happens
   whenever the touch is started, at every visit. Then the session goes on.
3. Between blocks: **Waiting for the next scheduled step. The countdown shows when it is due.**
   The countdown shows the next block, for example **Next: block 3 (touch) in 04:05**.
4. **When a block is due** (section 13.3), the screen shows **Ready. Press Start block when the
   participant is ready.** Press **Start block** once. That press launches the block and starts it.
   - **A pinprick block** is the short protocol in the secondary zone with the filament the
     software chose at post-sensitisation: five applications (section 10).
   - **A touch-rating block** shows **Touch-rating block: the participant rates the touch.** The
     participant makes twelve ratings of the touch and how they feel. Nothing to do.
5. **If you are late**, launch the block as soon as you can. The software never skips or shortens
   a block. It records how late it was.
6. **The rekindle**, at 105 minutes (60 minutes into the intervention):
   1. The countdown shows **Rekindle is due.** The garment is switched off.
   2. The screen shows **Rekindle now. The garment has been deactivated and will be reactivated
      afterwards.**
   3. Place the thermode and start the rekindle programme (Bilaga 1 §3.5: 45 °C for 2 min).
      **Press Start block as the heat starts.**
   4. The software times the rekindle window, then restarts the garment (**Touch: the garment is
      being started.**) and carries on with the next block.
7. At 165 minutes: **The intervention has ended and the garment has been switched off.** The
   session moves straight on to post-intervention.

### 12.2 Post-intervention and session end

1. The phase shows **Post-intervention**. The measures are the same as post-sensitisation, with the
   mapping (sections 9 and 10).
2. **If mapping distances are still missing**, the screen says **Mapping distances are still
   outstanding. Enter them now, or close the session with them flagged missing.**
   - Enter them with **Mapping distances…**, then press **Start block**.
   - Or press **Start block** to close with the missing ones flagged.

   You are asked only once.
3. The participant's closing screen appears, and both windows close. The session is complete.
4. Remove the garment and the headphones.

### 12.3 The fit preview (piloting only)

When S has switched it on, the amber banner **FIT PREVIEW IS ON. …** shows all session. At the end
of each long protocol and of the touch calibration, a window shows the fit with the participant's
ratings, and you choose **Accept this estimate** or **Re-run the procedure**. A re-run asks **Why
are you re-running? Recorded with the discarded estimate, which is kept.** After the limit:
**The re-run limit for this procedure has been reached. This estimate will be used.**

Never switch it on yourself. It shows you ratings, which the participant has been told you do not
see.

### 12.4 Timings at a glance

Times are from the thermode press (session time zero). They come from `config/schedule.yaml`, and
**Preview schedule** shows the current ones.

| Time | Step |
|---|---|
| Before 0 | Setup, touch calibration, pre-sensitisation |
| 0 | Heat sensitisation, 2 min |
| 2 min | Capsaicin applied |
| 32 min | Capsaicin removed, post-sensitisation starts |
| 45 min | Intervention starts |
| 55, 63, 71, 79, 87, 95 min | Blocks 1 to 6 |
| 105 min | Rekindle |
| 117, 125, 133, 141, 149, 157 min | Blocks 7 to 12 |
| 165 min | Intervention ends, post-intervention |

Each block is estimated at 4 minutes. That is a guess until the pilot has measured it (open item
4).

### 12.5 After a crash: what resuming does

If the software stops unexpectedly (a crash, a power cut):

1. Tell the participant there is a short technical pause. Check that the garment is not inflated.
   **[TBC: what to do with the garment if the software crashed while it was inflated.]**
2. Start the launcher again and fill in **Run a session** exactly as before.
3. Press **Check**, then **Start session**, and choose **Resume the session**.

Resuming:

- carries on from the first step not completed. The step that was running at the crash is done
  again, and its earlier rows are kept, marked as replaced;
- keeps the original time zero, so every countdown carries on where it should;
- reloads what was already measured (the calibrations, the audio level, the mapping distances
  already entered) and does not redo it;
- during the intervention, restarts the garment after the warning cue;
- during the rekindle, never asks for the heat a second time. The screen says **The session
  resumed during the rekindle. The heat was started before the interruption and is not prompted
  again; the rekindle is timed from then. Press Start block to confirm. If the heat was not in fact
  applied, apply it now and enter a note. The garment stays off until the rekindle is over.**

**Do not close the session window to restart it.** Closing the window records the session as
aborted ("the window was closed before the session ended"), and an aborted session cannot be
resumed.

---

## 13. Emergencies, banners and warnings

### 13.1 The participant's stop

- **The hardware stop button and the rapid depressurisation release are the real safety path.**
  They work without the software. The software cannot see them.
- **The software stop** is the remote's blank-screen button (the F5 key). It sets the garment to
  zero at once, shows the participant a stop screen, and shows you the red line **EMERGENCY STOP.
  The garment is at zero. Press Resume when the participant is ready.**

When the participant presses either:

1. Go to the participant. Ask if they are all right.
2. If they want to stop the session, press **Abort session** and give the reason.
3. If they are ready to carry on, press **Resume**. The step that was interrupted is repeated.

The participant has been told that pressing the stop will not disturb the experiment. Resuming
keeps that promise.

**[TBC: what to press on the software after the participant uses the hardware stop, which
the software does not detect. Pausing first and writing a note seems sensible.]**

### 13.2 Banners at the top of your screen

| Banner | What it means | What to do |
|---|---|---|
| Red: **PARTICIPANT SCREENS STILL CONTAIN PLACEHOLDER TEXT. Do not run a real participant.** | Some participant wording is not final. | **Do not run a real participant.** Piloting with lab members only. |
| Amber: **THIS SESSION IS NOT COLLECTING VALID TOUCH-CALIBRATION DATA. The connected device (…) cannot set pressure per channel. Timings are real; pressures are not.** | The garment in use cannot set a pressure per channel, for example the prototype or the mock. | Fine for piloting timings. Not a real data session. |
| Amber: **FIT PREVIEW IS ON. You will see the participant's ratings, …** | Section 12.3. | Piloting only, unless S says otherwise. |

Banners stay for the whole session. The screen does not move when one appears.

### 13.3 The countdown and the alerts

| Shown | Meaning |
|---|---|
| Grey: **Next: … in mm:ss** | The next scheduled step and how long until it. |
| Amber, bold: **Block … is due.** or **… is due.** | Launch it when ready. |
| Red, bold: **Block … is OVERDUE.** or **… is OVERDUE.** | Launch it as soon as you can. |

A lab-side alert sounds 30 s before each step is due, and again 60 s after if it has not been
launched. The participant should not hear it (open items L3 and L10).

### 13.4 The open items line

Amber small text under the instruction: **Unresolved configuration placeholders: …**, listing item
numbers. Hover over it to see what each one is. The same list prints when the software starts.

Each item is a value only S can supply. Some of them must be settled before a real participant.
**[TBC: whether every listed item blocks a real session, or only those marked blocks_use
in config/open_items.yaml.]**

### 13.5 Other messages

| Message | What to do |
|---|---|
| **Disconnected**, in red, under **Garment** | Check the garment's cable and supply, then press **Connect garment**. |
| **Fault: …** or **Garment faults: … (detail in the data)** | Write a note. If it stays, pause and ask S. |
| A dialog titled **Error** | Write down the message, press **Close**, and see section 14. |

---

## 14. After the session

### 14.1 The data files

- They are in the **data folder** you chose, by default the `data` folder in the repository.
- Each session writes a set of CSV files named with the date and time, then `P<code>_S<session>_`
  and the table, for example `…_P07_S1_session.csv`, `…_P07_S1_log.csv` and
  `…_P07_S1_pinprick.csv`. A resumed session writes a second set, which names the first.
- Every row is saved the moment it is collected. Nothing is ever overwritten.
- **Do not open, rename, move or delete them** during the session or before they are transferred.
  They record which kind of touch was given.
- The lock file in the data folder is the software's. Leave it.

### 14.2 Transfer to the LiU secure server

**[TBC: the manual transfer to the LiU secure server (LOG N4.1). The process is not defined
yet. Needed: who does it, when, to where, how it is checked, and whether the local copy is then
deleted.]**

### 14.3 What never leaves the lab PC except by that transfer

- The data files. Never by email, a USB stick, OneDrive or another cloud-synced folder, and never
  into git. The `data` folder is excluded from git on purpose.
- Anything linking a participant code to a name. It is never in the software or its files.

### 14.4 Before you leave

1. Clean and put away the filaments, brush and thermode.
2. Write anything unusual that happened after the session closed where S asks.
   **[TBC: where post-session notes go.]**

---

## 15. Troubleshooting

| Problem | What to do |
|---|---|
| The participant presses buttons and nothing happens on their screen. | Check whether a text field on your screen has the cursor in it: while you type, the remote's presses go into that field. Press Enter or click a button. Otherwise the remote reaches the participant's screen whichever window is active. If it still does not respond, check the remote's receiver and battery. **[TBC: routing tested headless, not yet on the lab PC with the real remote.]** |
| Both windows opened on the lab display. | Open item 9 is not set yet. Tell S. Do not run a real participant. |
| **Start session** is greyed out. | Press **Check**. It greys out again whenever a field changes. |
| **Another session is already running from this data folder** but no other copy is open. | Check the taskbar for a hidden window. If none, restart the PC and try again. |
| The launcher did not open, or a long error printed in PowerShell. | Copy the last lines of the message and send them to S. Do not try to fix configuration files. |
| The software crashed during a session. | Section 12.5. |
| **Discard and repeat last trial** did nothing. | It works only in the 13 to 17 s after a pinprick or brush rating. |
| **Accept this estimate** did nothing. | That estimate cannot be used. Re-run, or abort. |
| **Abort session** in the dialog is greyed out. | Type a reason. |
| You cannot hear the lab-side alerts, or the participant can. | Open items L3 and L10. Tell S. Keep an eye on the countdown. |
| **Mapping distances…** is greyed out. | Nothing has been mapped yet in this session. |
