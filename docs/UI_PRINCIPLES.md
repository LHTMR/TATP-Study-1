# UI principles

Normative. These are the rules a screen is reviewed against, in priority order. Where two rules
conflict, the lower-numbered section wins. Rationale is not recorded here — `docs/NOTES.md` logs
the review that produced a change.

The participant screen and the experimenter screen are different kinds of object and do not
share rules. The participant screen is a **stimulus display**: its job is to not perturb the
measurement. The experimenter screen is a **safety-critical monitoring display**: its job is to
be read correctly at a glance, under time pressure, from across the room.

## 1. Measurement validity (participant screen)

1.1 Anything on screen that is not the current question, its scale, and its anchors is a
distractor and is removed.

1.2 **Anchor wording and anchor position are fixed by Bilaga 1 §3.6.1 and §3.9.1** and are not a
presentation choice. Shortening, dropping, merging or repositioning an anchor to make a layout
work is a protocol deviation, not a design decision.

1.3 An anchor label must be unambiguously attributable to its own position on the line. Where
labels at 10 % or 90 % cannot be centred under their position without colliding, the position is
marked with a tick at the anchor and the label tied to that tick. A label displaced sideways or
dropped to another row with nothing tying it to its position is a validity failure: it silently
relabels the scale.

1.4 No numbers, and no tick marks anywhere except at a labelled anchor (`docs/SPEC.md` §10.2).

1.5 The line is straight, unbroken and of uniform weight along its whole length. Participants are
trained that twice as far along means twice as much (Bilaga 1 §3.6.1, after Price et al. 1983);
any visual feature that makes one region of the line look different from another breaks that
instruction.

1.6 Scale geometry — line length as a fraction of the screen, position, orientation, marker form,
anchor type size — is identical across every scale, every session and both languages. A rating is
only comparable to another rating drawn the same way.

1.7 Mean screen luminance does not change between a message, a stimulus, a cue and a rating
beyond what the content itself requires.

1.8 Nothing indicates a previous response, a trial number or elapsed time.

1.9 Marker behaviour is fixed by `docs/SPEC.md` §10.2: hidden until the first press, then 25 %
after a left press and 75 % after a right. Not a presentation choice.

## 2. Blinding and approved wording

**The approved wording is what is in `config/text/`.** It was written from these principles and
the ethics documents and then approved by S, and that approval is the authority. A review does
not re-derive it from source documents and does not treat a difference from Bilaga 1 as a
finding by itself. The principles below are stated so that *new* or *changed* wording has
something to be written against — not so that existing wording is re-litigated.

2.1 No screen states or implies that touch is expected to relieve pain. The participant framing
is "touch and pain sensation together", and the touch and relaxation questions exist partly to
mask the target outcome — a screen that foregrounds pain over the others undoes that.

2.2 No screen names the research environment, the hypothesis, or the condition.

2.3 The condition is never displayed on the experimenter screen, and nothing displayed there
differs by condition. `docs/SPEC.md` §16 has the enforcing tests. This one is absolute.

2.4 Where the ethics documents fix a wording, follow them: the VAS questions, anchors and
statements come from Bilaga 1, and participant-facing vocabulary for the procedure follows the
consent document — "tunna plastfilament", "en mjuk pensel", never "nålstick". **Where they say
nothing, that is not a blocker.** They describe the study, not every screen the software shows,
and most operational wording has no counterpart in them. Write it, and it is approved by S in
the normal way. S can also approve a deviation from them where one is practical; a deviation
that has been approved is recorded in `docs/NOTES.md` and is then simply the design.

2.5 Ratings are not casually visible to the experimenter, and the experimenter screen shows no
running rating and no participant response as it happens. **Deliberate, approved exceptions
exist** — the adaptive model-fit preview is one, approved because testing, piloting and
troubleshooting need it. An exception is a named screen or control, not a general licence, and
§2.3 is not subject to any exception.

## 3. Safety and legibility (experimenter screen)

3.1 Three things must be readable without approaching the screen: the current phase, what to do
now, and any active warning. Everything else is secondary and is typeset as secondary.

3.2 A state that requires action is distinguished by more than wording. Disconnected, unresolved
open items, and a placeholder-wording banner each carry a colour and a position that make them
identifiable before they are read.

3.3 A warning occupies a fixed region and never displaces the instruction or reflows other
content when it appears. A layout that moves is a layout that gets misread.

3.4 Two states that require different actions never look similar. Two states that require the
same action never look different.

3.5 The screen is legible in a dimly lit room and does not itself light the room. It must never
be the brightest object in the participant's field of view.

3.6 The emergency stop is reachable and identifiable without reading (Bilaga 1 §3.10). Nothing
is a control unless it can be operated without looking away from the participant.

## 4. Consistency

4.1 Every user-facing string comes from `config/text/`. No wording in a widget.

4.2 Swedish and English layouts are reviewed as a pair. Swedish strings are longer; a layout that
only holds at English length is broken.

4.3 Type sizes come from a small fixed set, and a size means a level in the hierarchy rather than
a screen's local preference.

4.4 Alignment, margins and spacing are shared values, not per-screen constants.

## 5. Intuitiveness and ease of use

Within §1–4, and never at their expense. §1–4 say what a screen may not do; this section is the
part that is actually about design, and it is where a review is expected to find most of its
work.

5.1 **The next action is obvious without being told.** A participant who has forgotten the
instructions, and an experimenter who has looked away and back, should both be able to resume
from what is on the screen. Prefer making the state legible over adding a sentence explaining
it.

5.2 **The experimenter screen is read in a fixed order, and the layout enforces it.** Who and
where, then what phase, then what to do now, then warnings. Grouping and spacing carry that
order; a flat list of equally-weighted lines does not.

5.3 **Wording earns its place.** A screen the participant reads once at the start may be long. A
screen they see 30 times must be short enough to take in at a glance, because after the third
time it is not read at all.

5.4 **Repetition is the dominant fact of this session.** Three hours, six blocks, five ratings
per block. A screen that is merely acceptable once becomes a burden on the hundredth pass. Judge
every participant screen at the hundredth pass, not the first.

5.5 **Same thing, same place.** A question, a line, a marker, an instruction each appear at a
fixed position across screens, so the eye does not search. This is also §1.6 for the scale
itself; here it applies to everything else.

5.6 **Nothing that must be noticed is left to a change in wording alone** — position, colour and
weight do that work, and the wording confirms it.

5.7 **The mechanics of responding are visible where they are used, not only in the instructions
screen** — but as the smallest cue that works, never as a paragraph competing with the question.

## 6. How a screen is reviewed

Against §1–5 in order, on the rendered PNG in `screenshots/current/`, in both languages, never
from the code alone. A finding is graded:

- **validity** — breaks §1 or §2. Fixed before piloting.
- **safety** — breaks §3. Fixed before piloting.
- **usability** — breaks §5. Weigh the cost of the change against how often the screen is seen.
- **polish** — breaks §4, or is a preference. Fixed if cheap; otherwise recorded and left.

A finding names the rule it breaks. "This would look better" without a rule behind it is a
preference, and belongs in the polish grade or nowhere.

A change to any screen is followed by `make shots` and re-approval of its reference image.
