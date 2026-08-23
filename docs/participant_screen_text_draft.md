# Participant screen text — approved, with the reasoning behind it

**Status: approved by S on 23 August 2026 and transcribed.** This closed open item L4 —
`FOR_S.md` A1.1 and A1.2. `config/text/participant_{sv,en}.yaml` now holds the real strings,
`meta.instructions_supplied` is set, and the placeholder banner no longer fires for these keys.

This file is kept as the **rationale**, not as a staging area: which wording came from which
approved document, what the literature required, and which decisions S took against my
recommendation. The pre-registration and any later reviewer will need that, and it is not
recoverable from the YAML.

**Still open:** `meta.verified_against_ethics` (A1.3) — the drafted Swedish VAS wordings in
`SPEC.md` §10.6 have not been checked against the participant-facing ethics attachments. That
is a separate item from the screens.

## Sources actually consulted

Read from the connected ethics folder:

- **`Bilaga3a_FP-info_TATP_sv.docx`** (current version) — the approved participant-facing
  vocabulary. This is what the screens must not contradict.
- **`Bilaga1_Forskningsplan_V2.docx`** §§ on pinprick pain, area of secondary hyperalgesia,
  touch calibration.
- **`support_documents/article_summaries.md`** §IV (rating-scale anchoring and training) and
  §VIII (autonomy, agency and control).

The archive copy `archive/Bilaga3a_FP-info_TATP_sv.md` is **superseded** — it describes a nature
film and a vision component that are not in the current sheet. It was not used.

## What the evidence changed

Three findings, none of which I would have got right by judgment.

1. **Vocabulary is fixed by Bilaga 3a and my first draft had it wrong.** The sheet says the
   skin is tested "med tunna plastfilament som trycks mot huden och med en mjuk pensel". It
   never says *nålstick*. A screen that says "pinpricks" describes the study in words the
   participant was not consented with. Screens below say *filament* and *pensel*, or nothing.
2. **The `self_start` wording is load-bearing, because it is part of the manipulation.**
   `SPEC.md` §12.3 gives the self-start press to the `participant_preferred` condition only, so
   the agentive framing is not a stylistic flourish that leaks expectancy into a clean
   contrast — it is what that arm is made of, together with the self-chosen pattern.

   `article_summaries.md` §VIII.f still applies, but as guidance on **making the manipulation
   work** rather than on suppressing it: the effect depends on instructions emphasising
   personal involvement (Löffler et al. 2018), is inert unless participants believe the control
   works (Vancleef & Peters 2011), can reverse under partial or unreliable control
   (Weisenberg et al. 1985), and may be abolished by latency between press and onset
   (Karsh et al. 2018). Note that §VIII.f itself is written from the premise that autonomy is
   *not* a design factor and would therefore be contamination; that premise does not hold for
   this design, so read its conclusions as being about the CT-vs-control contrast, not this arm.
3. **The welcome screen should re-orient to the scales at every visit, not only the first.**
   §IV, Pathak et al. 2018: rating error falls with repeated exposure and re-orientation to the
   anchors at the start of each session limits between-session drift — which is the drift the
   within-person AUC does *not* cancel out. One line is enough; the VAS training block does the
   real work.

**A1.2 is answerable and no longer needs S to invent anything.** Bilaga 1 gives the English
proportionality wording directly: "a mark twice as far along the line indicates it is twice as
painful", and for touch "twice as pleasant/intense" (Price et al. 1983). Transcribed into the
`training:` keys that is:

| key | English |
|---|---|
| `training.pain` | A mark twice as far along the line means it was twice as painful. |
| `training.intensity` | A mark twice as far along the line means the touch felt twice as intense. |
| `training.pleasantness` | A mark twice as far along the line means the touch felt twice as pleasant. |

Say the word and I will put those three in, since they come from the approved plan rather than
from me.

## Conventions

- At most four short lines per screen; no paragraphs.
- Buttons named as the participant sees them: "the two large buttons" and "▶". If the play
  button is not marked ▶, one substitution fixes every screen.
- Blinding (§16): no relief, no study name, no condition detail. Touch is "beröringen från
  plagget", never a treatment.

---

## The ten screens

### welcome

**English**
> Welcome.
> This study is about pleasant and unpleasant bodily sensations — touch and pain.
> You will rate what you feel by marking a point on a line. There are no right answers, and the
> experimenter does not see your ratings.
>
> Press ▶ to begin.

**Svenska**
> Välkommen.
> Studien handlar om behagliga och obehagliga kroppsförnimmelser – beröring och smärta.
> Du skattar det du känner genom att markera en punkt på en linje. Det finns inga rätta svar,
> och försöksledaren ser inte dina skattningar.
>
> Tryck på ▶ för att börja.

The framing line is the title of Bilaga 3a. "Försöksledaren ser inte dina skattningar" is the
sheet's own sentence.

### standby

**English**
> Rest for a moment.
> The next part starts shortly.

**Svenska**
> Vila en stund.
> Nästa del börjar snart.

### session_end

**English**
> That is the end of today's visit.
> Thank you.
> Please wait for the experimenter.

**Svenska**
> Då är dagens besök slut.
> Tack.
> Vänta kvar tills försöksledaren kommer.

### paused

**English**
> Paused.
> The session continues shortly.

**Svenska**
> Pausad.
> Sessionen fortsätter snart.

### emergency_stop

**English**
> Stopped.
> The touch has been switched off.
> Please wait for the experimenter.

**Svenska**
> Stoppat.
> Beröringen är avstängd.
> Vänta kvar tills försöksledaren kommer.

### self_start

**This screen appears in the `participant_preferred` condition only** — `SPEC.md` §12.3: "In
the participant-preferred condition the participant starts the stimulation with the confirm
button." Together with the self-chosen pattern, the self-initiation is what constitutes that
arm. The agentive wording is therefore the manipulation, and it should be as agentive as the
approved documents allow rather than as bare as possible.

**English**
> Press ▶ when you're ready for the touch to start.

**Svenska**
> Tryck på ▶ när du är redo att beröringen ska börja.

Deliberately says *the touch will start because you pressed*, not merely *continue*. If the arm
is meant to carry top-down content, the instruction is where that content lives (Löffler et al.
2018: the controllability effect appeared only when instructions emphasised personal
involvement).

Two knock-on points that follow from this being the manipulation:

- **Latency matters.** §VIII.f, on Karsh et al. 2018's contiguity requirement: a lag between
  the press and touch onset may abolish the effect. Argues for a short, fixed, logged latency
  from keypress to first garment command.
- **Intensity may be the wrong place to look for it.** Löffler et al. 2018 found
  controllability moved *suffering*, leaving intensity and unpleasantness unchanged. If this is
  meant to do something detectable rather than simply be present, it belongs in the analysis
  plan as a pre-registered exploratory question.

### adjust

Generic frame, shown below a per-step target line from `adjust_targets:`.

**English**
> Left button: weaker. Right button: stronger.
> Press ▶ when it feels right.

**Svenska**
> Vänster knapp: svagare. Höger knapp: starkare.
> Tryck på ▶ när det känns rätt.

**Targets** (S, 23 Aug 2026: use the anchor labels). Worded with the anchor label of the scale
in question wherever the target sits on a labelled anchor.

| key | English | Svenska |
|---|---|---|
| `just_noticeable` | Set the touch so that it is just noticeable. | Ställ in beröringen så att den är precis märkbar. |
| `marked_point` | Set the touch so that it matches the marked point on the scale. | Ställ in beröringen så att den motsvarar den markerade punkten på skalan. |
| `match` | Set the second touch so that it feels as strong as the first. | Ställ in den andra beröringen så att den känns lika stark som den första. |
| `most_pleasant` | Set the touch so that it feels as pleasant as possible. | Ställ in beröringen så att den känns så behaglig som möjligt. |

**One assumption, stated because it goes beyond "use the anchor labels".** Protocol B's
intensity targets are 10 %, 30 % and 80 %, but only 10 % carries an anchor label ("just
noticeable"); the labels at 90 % and 100 % are above the working range and 30 % and 80 % have
none. So the 30 % and 80 % steps use `marked_point`, which needs the VAS drawn with the target
position marked. If you would rather those two points got anchor labels of their own, that is a
change to `SPEC.md` §10.6 and to Bilaga 1 §3.9.1, not just to this file.

### comparison

**English**
> Two touches, one after the other.
> Which felt stronger?
> Left button: the first. Right button: the second.
> Press ▶ to confirm.

**Svenska**
> Två beröringar, en i taget.
> Vilken kändes starkast?
> Vänster knapp: den första. Höger knapp: den andra.
> Tryck på ▶ för att bekräfta.

### preference

**English**
> You will feel a few different kinds of touch.
> Use the two large buttons to move between them.
> Press ▶ to choose the one you like best.

**Svenska**
> Du får känna några olika sorters beröring.
> Använd de två stora knapparna för att växla mellan dem.
> Tryck på ▶ för att välja den du tycker bäst om.

### mapping — no participant screen

**S, 23 Aug 2026: the mapping is instructed verbally and the participant signals verbally.**
Bilaga 1 says participants *report* the change, and that reading is the correct one.

Consequences, all applied:

- `screens.mapping` is **removed** from `participant_{sv,en}.yaml`. A key nothing reads is
  exactly what `CLAUDE.md` forbids, and a stale instruction screen would eventually be shown.
- The wording moves to the experimenter files as `instructions.mapping_script`, a line to read
  aloud. It keeps Bilaga 1's own examples of the change — "burning", "tenderness", "more
  intense pricking" — because those are what the approved plan says participants are told.
- The participant screen shows `standby` throughout the mapping.

**The script** (experimenter reads aloud)
> I will touch you with this filament, moving a small step at a time towards the marked area.
> Tell me as soon as the feeling clearly changes — burning, tenderness, or a sharper pricking.

> Jag kommer att röra vid dig med det här filamentet och flytta ett litet steg i taget mot det
> markerade området. Säg till så snart känslan tydligt förändras – brännande, ömmande eller
> vassare stick.

**One implementation consequence for `SPEC.md` §8.4.** It says "the participant signals the
change in sensation; the software records the step number". If the signal is verbal, the
keypress that stops the pacing cue is the **experimenter's**, not the participant's, and the
recorded step therefore carries the experimenter's reaction time on top of the participant's.
That is normal for this protocol and is what the source papers do, but §8.4 should say which
key ends a path, and the data schema should not imply the participant pressed it.

---

## Questions raised, and how they were settled

1. **Per-target `adjust` strings** — settled: use the anchor labels. `adjust_targets:` above.
2. **Is the play button marked ▶?** — open, and it belongs to the hardware bring-up session:
   custom labels may be printable on the buttons. Carried as `FOR_S.md` A2.8. Until it is
   settled, every screen writes the button as ▶ and a single substitution changes them all.
3. **Verbal mapping** — settled: verbal instruction, verbal signal, no participant screen. See
   the mapping section above, including the one consequence for `SPEC.md` §8.4.

Ethics-document questions raised in passing (the participant information sheet's description of
how ratings are given, and its silence on the participant stop button) are outside this
repository's scope and are deliberately **not** tracked here.
