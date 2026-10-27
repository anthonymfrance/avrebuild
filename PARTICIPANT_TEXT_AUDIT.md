# Participant text audit

Every piece of text a participant can see during a session, in the order it
appears, with the word count of the page they are looking at. This is the state
after the first round of wording changes (the earlier single-page wording is in
the previous commit of this branch).

Generated from the source, so the wording below is the wording on screen:

```bash
python3 tools/participant_text_inventory.py          # word/char counts per string
python3 tools/participant_text_inventory.py --full    # counts + full wording
python3 tools/render_screen_mock.py                   # contact sheet of the static screens
```

`render_screen_mock.py` draws the screens to HTML with fake PsychoPy objects —
no display and no PsychoPy needed — using the real positions, image sizes and
page breaks. Serve it and open it:

```bash
python3 -m http.server 8791 --directory build/screen_mock
```

Run-time values appear below as `«placeholders»`; counts in the tables are the
words the participant reads on that page, including its "Press SPACE…" line.

The block intro and the trial recap are built from live trial counts by
`screens.block_intro_message` and `screens.trial_recap_message`, so the inventory
tool prints their fixed wording with placeholders for the numbers; the counts
below come from rendering those two with representative values
(`tests/test_participant_text.py` and `tests/test_screens.py` pin the assembled
pages).

---

## A. Screen order

Operator screens (the study-setup plan listing and the per-frame debug overlay)
are **not** participant-visible and only appear when preflight is run with the
*Debug run* button; they are excluded.

| # | Screen | Source | Words | When |
| --- | --- | --- | --- | --- |
| 1 | Hand Placement | [screens.py:114](screens.py#L114) | 62 | once, before the plan exists |
| 2 | Number Key Check | [screens.py:165](screens.py#L165) | 37 then less | once; the "still to check" list shrinks per key |
| 3 | Sound Check | [screens.py:177](screens.py#L177) | 27 | once |
| 4 | Instructions — page 1 of 3 | [screens.py:47](screens.py#L47) | 44 | once, one SPACE per page |
| 5 | Instructions — page 2 of 3 | [screens.py:47](screens.py#L47) | 47 | " |
| 6 | Instructions — page 3 of 3 | [screens.py:47](screens.py#L47) | 69 | " |
| 7 | How your responses are scored — 1 of 2 | [screens.py:71](screens.py#L71) | 45 | once |
| 8 | How your responses are scored — 2 of 2 | [screens.py:71](screens.py#L71) | 57 | " |
| 9 | Practice intro | [practice.py:112](practice.py#L112) | 23 | once |
| 10 | Practice coach step 1 (circle) | [practice.py:30](practice.py#L30) | 13 | once |
| 11 | Practice coach step 2 (square) | [practice.py:35](practice.py#L35) | 16 | once |
| 12 | Practice coach step 3 (both) | [practice.py:44](practice.py#L44) | 13 | once |
| 13 | Coach feedback notices | [practice.py:287](practice.py#L287) | 1–9 | after each coached press |
| 14 | Now at the real speed | [practice.py:173](practice.py#L173) | 23 | once |
| 15 | Paced practice caption | [practice.py:341](practice.py#L341) | 2 | during the 5-item round |
| 16 | Practice summary | [practice.py:390](practice.py#L390) | 87 | once |
| 17 | Block intro | [screens.py:269](screens.py#L269) | 24 | once per block (×2) |
| 18 | Trial recap | [screens.py:278](screens.py#L278) | 58 | after every trial (×8) |
| 19 | Break | [screens.py:325](screens.py#L325) | 28 | once, after block 1 |
| 20 | Study complete | [experiment.py:464](experiment.py#L464) | 34–36 | once, at the end; varies with the saved path length |

**26 pages per session, from 18 distinct page types**: the block intro appears
twice (once per block) and the trial recap eight times (once per trial). The
table's last two rows are not pages a participant advances past: the
coached-feedback lines appear under a practice prompt, and the "Circles only."
caption is drawn during the paced practice round. Every instructions and scoring
page now waits for SPACE, so the participant sets the reading pace instead of
facing a two-block wall of text.

### 1. Hand Placement — 62 words

Text in the left column, the new keyboard photo under it, and the tall finger
diagram on the right as the labelled key reference:

```
Hand Placement

Here is an example hand position: one finger on the
space bar and two on the number pad. Please use your
dominant hand on the number pad.

Rest your index finger between 4 and 1, and your
middle finger between 5 and 2.
Keep your fingers on the number pad between responses.

Press SPACE when your hand is in place.
```

Images: [Example Hand Placement Photo.jpg](Example%20Hand%20Placement%20Photo.jpg)
(883×401 at 1920×1080, under the text) and
[Finger Placement Screen Visual.png](Finger%20Placement%20Screen%20Visual.png)
(576×768, right column).

### 2. Number Key Check — 37 words at first, then fewer as keys are ticked off

```
Number Key Check

Press each of the four number keys shown here once.

Still to check: top-left (4), top-right (5), bottom-left (1), bottom-right (2)

If a key does not work, turn Num Lock on and try again.
```

### 3. Sound Check — 27 words

```
Sound Check

Listen for a short sound.

Press R to hear it again.
Press SPACE if you heard it.
Press N if you did not hear it.
```

### 4–6. Instructions — 44 / 47 / 69 words, one page each

```
The experiment has two parts: an animals part and an objects part.
You will be told which part comes first for you.

During the animals part, all animals are your targets.
During the objects part, all objects are your targets.

Press SPACE to continue.
```

```
When a target appears, press the number key for the corner where it appeared.

Do not press for pictures that are not your targets. In the animals part, for
example, do not react to pictures of objects.

You have 0.9 seconds to respond.

Press SPACE to continue.
```

```
React correctly and the cross flashes green: that is a hit. Aim to get as many
hits as you can.

If you do not react in time you gain a miss or a late response; the next screen
explains the difference.

If you react to the wrong corner or to the wrong type of picture you gain a
false alarm. Aim to keep these low.

Press SPACE to continue.
```

### 7–8. How your responses are scored — 45 / 57 words, one page each

```
How your responses are scored

Hit: the right number key within 0.9 seconds of the target
appearing. The cross flashes green.

Late: the right number key, but after 0.9 seconds and within
1.4 seconds. A late response is not a miss.

Press SPACE to continue.
```

```
Miss: no key in the target's corner within 1.4 seconds.

False alarm: a key in the wrong corner, a key for a picture that is not your
target, or a key when no target is on screen.

Only 1, 2, 4 and 5 count as responses. Any other key is ignored.

Press SPACE to start the practice.
```

### 9. Practice intro — 23 words

```
Practice

Circles are targets. Squares are not.
Everyone sees this same practice. It is not part of your score.

Press SPACE to start.
```

### 10–13. Coached practice — 13 / 16 / 13 words, plus feedback lines

```
A circle is a target.
This one is in the top-right. Press 5.
```

```
A square is not a target.
Do not press a number key.
Press SPACE to continue.
```

```
Press only for the circle.
The circle is in the top-left. Press 4.
```

Appended under the current prompt after a wrong press:

```
That would be a false alarm. Squares are not targets.
That corner has a square. Squares are not targets.
That key is a different corner. This circle is the top-right (5).
```

and `Correct.` flashes with the green cross after a correct press.

### 14. Now at the real speed — 23 words

```
Now at the real speed.
Circles only. You have 0.9 seconds.
The cross flashes green when you are correct.

Press SPACE to start.
```

### 15. Paced practice caption — 2 words

```
Circles only.
```

### 16. Practice summary — 87 words

Counts now use the same four lines as every trial recap (one definition in
[scoring.py](scoring.py#L130)), so practice and the real task cannot drift apart:

```
Practice complete.

You correctly responded to 4 out of 5 targets!
You responded too slowly on 1 target.
You completely missed the reaction time window for 0 targets.
You either reacted at the wrong time or to the wrong corner 1 time.

Remember to respond to all targets quickly and accurately!

The real task is the same, with animal photos and object photos
instead of circles and squares. Some pictures play a sound.
You still respond only to the target pictures.

Press SPACE to begin the study.
```

### 17. Block intro — 24 words (×2)

Targets are now named as a group, not "one":

```
Block 1 of 2: ANIMALS
Your target group is animals. Press the matching numpad key when you see any animal.

Press SPACE to continue.
```

`OBJECTS` uses "any object". `screens.BLOCK_TARGET_PHRASE` derives the singular
from `config.BLOCK_LABELS`, so the wording cannot drift from the block name; it
sits in `screens.py` rather than `config.py` because every config constant is
part of the snapshot that existing participant plans are validated against
(`session_io.load_timeline`), and a plan that fails that check will not run.

### 18. Trial recap — 58 words (×8, after every trial)

```
OBJECTS — Trial 3 complete.

You correctly responded to 5 out of 7 targets!
You responded too slowly on 1 target.
You completely missed the reaction time window for 1 target.
You either reacted at the wrong time or to the wrong corner 2 times.

Remember to respond to all targets quickly and accurately!

Press SPACE to continue.
```

Counts pluralize ("1 target" / "2 targets", "1 time" / "2 times") and zero counts
still show, so a clean trial says `0 targets` rather than hiding the line.

### 19. Break — 28 words (counts down from 30 s, ends on its own)

```
Break — the study continues on its own in «30» seconds.

Rest your eyes and hands, then carry on when you are ready.

Press SPACE to continue now.
```

### 20. Study complete — 34 words

```
Study complete — thank you!

Participant: «participant_08»
Target appearances: «91»
Valid hits: «…»
Late responses: «…»
Misses: «…»
False alarms: «…»

Data saved in:
«/home/dogwood/av_study/avrebuild/data/participant_08/session_01»

Please inform the experiment lead that you have finished.
```

---

## B. The wall, before and after

| Screen | Before | After | Note |
| --- | --- | --- | --- |
| Instructions (one page, two blocks) | 165 words, 24 lines | 44 + 47 + 69 across 3 SPACE-gated pages | the wall; longest page now 69 |
| How your responses are scored | 98 words, 13 lines | 45 + 57 across 2 pages | split correct outcomes from errors |
| Hand Placement | 56 words | 62 words | + the keyboard photo; two sentences dropped (see note) |
| Block intro | 19 words | 24 words | names the target group |
| Trial recap | 19 words | 58 words | now says what happened, in words |
| Practice summary | 49 words | 87 words | shares the recap wording |

Longest single page in the study is now the practice summary (87 words, shown
once) and the longest instruction page is 69; before, two consecutive pages ran
82–98 words with no task action between them.

Notes on what was dropped rather than moved, so it can be restored if you want
it back:

- Screen 1 no longer says "Reach up for the top number or down for the bottom
  number in each pair." The diagram and photo show the finger positions.
- Screen 1 condenses "Keep your fingers resting on the number pad between
  responses, so you can respond quickly" to "Keep your fingers on the number pad
  between responses."
- The `IE if your target is animals…` sentence became "In the animals part, for
  example, do not react to pictures of objects."

Still open, if you want to go further: the practice summary and the 8 trial
recaps are the two longest pages left, and the recap repeats the reminder line
every trial.

---

## C. Participant 8 vs participant 10 — branch and commit

Both participants ran **identical code**. The recorded `git_commit` in
`participant_metadata.json` and `session_metadata.json` is `ca2c99d` for both
(and for participants 7, 9 and 11 as well — every session collected so far).

| | participant_08 | participant_10 |
| --- | --- | --- |
| Recorded commit | `ca2c99d6bc33064b23bb8eff4f642c39482baccc` | same |
| Branch checked out in the study folder | `cursor/shape-practice` | `clean-start` |
| Plan generated (UTC) | 2026-10-26 20:03:52 | 2026-10-27 15:12:35 |
| Session start → end (UTC) | 20:05:12 → 20:13:44 | 15:13:06 → 15:20:06 |
| Session outcome | `completed` (8 min 32 s) | `aborted` (7 min 0 s) |
| Block order | ANIMALS → OBJECTS | OBJECTS → ANIMALS |
| Trials per block | 4 + 4 | 4 + 4 |
| Debug overlay | false (participant run) | false (participant run) |
| Display / volume | 1920×1080 @120 Hz, 50 % | identical |

The branch name is not stored in the data — only the commit hash is. The branch
**at run time** is reconstructed from the study folder's `HEAD` reflog, which is
unambiguous here:

- `2026-10-26 13:03:52 -0700` (P8): `HEAD` had been on `cursor/shape-practice`
  since 2026-10-19 16:24:11 and had not moved since → **cursor/shape-practice**
  → P7, P8 and P9 all ran there.
- `2026-10-27 08:09:07 -0700`: `HEAD` moved `cursor/timing-log-rounding` →
  `clean-start`. P10's preflight was `08:12:10 -0700` and P11's later still, so
  **both ran on clean-start**.

The two participants differ in branch *name*, not in code: both branches pointed
at the same commit, `ca2c99d`.

### Branch creation and commit times

Branch creation is not stored in git objects, so these are reflog timestamps
(`branch: Created from …`), local time (`-0700`):

| Branch | Created | Created from |
| --- | --- | --- |
| `cursor/shape-practice` | 2026-10-19 16:24:11 | `origin/cursor/shape-practice` |
| `cursor/practice-difficulty-stages` | 2026-10-26 16:37:57 | `cursor/shape-practice` |
| `cursor/timing-log-rounding` | 2026-10-26 16:51:58 | `cursor/shape-practice` |
| `backup-oct26` | 2026-10-27 08:07:53 | `cursor/timing-log-rounding` |
| `clean-start` | 2026-10-27 08:09:07 | `ca2c99d` |
| `feat/participant-text-audit` | 2026-10-27 (this worktree) | `clean-start` |

The commit the participants actually ran:

| Commit | Committed | Subject |
| --- | --- | --- |
| `ca2c99d` | 2026-10-20 11:16:54 -0700 | Name the response categories participants are actually scored on. |

Newer commits exist on the other branches but **no participant has run them**:
`e9b661f` (2026-10-26 16:36:45, "Tell participants how each trial went in the
words they were taught"), `14da234` (2026-10-26 16:37:53) and `5546c74`
(2026-10-27 08:08:46) were all made while `HEAD` sat on branches participants
never ran, and `clean-start` was deliberately rolled back to `ca2c99d` before
P10. So the "trial went in the words they were taught" work is not in any
participant's data.

One caveat worth knowing: the block-order difference between P8 and P10 is not a
branch effect. It is the counterbalancing rule
(`completed session count: even → animals first, odd → objects first`); P8 was
allocated at completed-count 2, P10 at 3.
