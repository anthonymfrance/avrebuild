# Participant text audit

Every piece of text a participant can see during a session, in the order it
appears, with its word count. Generated from the source by
[tools/participant_text_inventory.py](tools/participant_text_inventory.py), which
evaluates the real string expressions against `config`, so the wording below is
the wording on screen (run-time numbers appear as `«placeholders»`).

```bash
python3 tools/participant_text_inventory.py          # word/char counts
python3 tools/participant_text_inventory.py --full    # counts + full wording
```

19 participant-visible strings, 624 words in total. Nothing here has been
changed yet — this is the map we pick edits from.

---

## A. Screen order

Operator screens (the study-setup plan listing and the per-frame debug overlay)
are **not** participant-visible and only appear when preflight is run with the
*Debug run* button; they are excluded.

| # | Screen | Source | Words | When |
| --- | --- | --- | --- | --- |
| 1 | Hand Placement | [screens.py:100](screens.py#L100) | 56 | once, before the plan exists |
| 2 | Number Key Check | [screens.py:137](screens.py#L137) | 29 | once |
| 3 | Sound Check | [screens.py:156](screens.py#L156) | 27 | once |
| 4 | Instructions (part 1) | [screens.py:246](screens.py#L246) | 83 | once |
| 5 | Instructions (part 2) | [screens.py:249](screens.py#L249) | 82 | once, same page as 4 |
| 6 | How your responses are scored | [screens.py:265](screens.py#L265) | 98 | once |
| 7 | Practice intro | [practice.py:112](practice.py#L112) | 23 | once |
| 8 | Practice coach step 1 (circle) | [practice.py:30](practice.py#L30) | 13 | once |
| 9 | Practice coach step 2 (square) | [practice.py:35](practice.py#L35) | 16 | once |
| 10 | Practice coach step 3 (both) | [practice.py:44](practice.py#L44) | 13 | once |
| 11 | Coach feedback notices | [practice.py:287](practice.py#L287), [practice.py:299](practice.py#L299) | 1–9 | after each coached press |
| 12 | Now at the real speed | [practice.py:173](practice.py#L173) | 23 | once |
| 13 | Paced practice caption | [practice.py:341](practice.py#L341) | 2 | during the 5-item practice round |
| 14 | Practice complete | [practice.py:389](practice.py#L389) | 49 | once |
| 15 | Block 1 of 2 intro | [experiment.py:390](experiment.py#L390) | 19 | once per block (×2) |
| 16 | Trial complete recap | [experiment.py:430](experiment.py#L430) | 19 | after every trial (×8) |
| 17 | Break | [screens.py:313](screens.py#L313) | 28 | once, after block 1 |
| 18 | Study complete | [experiment.py:469](experiment.py#L469) | 34 | once, at the end |

Between blocks 15/16 repeat with the other block label, so a full session shows
**17 distinct screens, 23 text pages, 8 of which are the trial recap**.

### 1. Hand Placement — 56 words

![](Finger%20Placement%20Screen%20Visual.png) *(left: text, right: finger diagram)*

```
Hand Placement

Rest your index finger between 4 and 1.
Rest your middle finger between 5 and 2.

Reach up for the top number or down for the bottom number in each pair.

Keep your fingers resting on the number pad between responses, so you can respond quickly.

Press SPACE when your hand is in place.
```

### 2. Number Key Check — 29 words

*(left: text, right: numpad diagram)*

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

### 4 + 5. Instructions — 83 + 82 words (one page, two text blocks)

*(top block)*

```
The experiment has two parts: an animals part and an objects part. You will be told which will come first for you.

During the animals task, all animals will be your targets.
During the objects task, all objects will be your targets.

When a target appears, press the number key corresponding to the corner where it appeared.
Do not press for distracting, non-target pictures. IE if your target is animals aim to not react to objects with the numpad.
Respond within 0.9 seconds.
```

*(bottom block, same page)*

```
Every time you correctly react to your target, the cross will flash green and you will gain a point or a correct hit. Aim to maximize these.
If you do not react in time you will gain a miss or a late response; the next screen explains the difference.
If you react to the wrong corner or the wrong object type (reacting to objects in the animals block) you will gain a false alarm. Aim to minimize these.

Press SPACE to continue.
```

### 6. How your responses are scored — 98 words

```
How your responses are scored

Hit: the right number key within 0.9 seconds of the target appearing.
     The cross flashes green.
Late: the right number key, but after 0.9 seconds and within 1.4 seconds.
     A late response is not a miss.
Miss: no key in the target's corner within 1.4 seconds.
False alarm: a key in the wrong corner, a key for a picture that is not your target,
     or a key when no target is on screen.

Only 1, 2, 4 and 5 count as responses. Any other key is ignored.

Press SPACE to start the practice.
```

### 7. Practice intro — 23 words

```
Practice

Circles are targets. Squares are not.
Everyone sees this same practice. It is not part of your score.

Press SPACE to start.
```

### 8–11. Coached practice — 13 / 16 / 13 words, plus feedback lines

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

Appended under the current prompt when the participant presses wrongly:

```
That would be a false alarm. Squares are not targets.
That corner has a square. Squares are not targets.
That key is a different corner. This circle is the top-right (5).
```

and, on a correct press, the word `Correct.` flashes with the green cross.

### 12. Now at the real speed — 23 words

```
Now at the real speed.
Circles only. You have 0.9 seconds.
The cross flashes green when you are correct.

Press SPACE to start.
```

### 13. Paced practice caption — 2 words

```
Circles only.
```

### 14. Practice complete — 49 words

```
Practice complete.

Correct hits: «hits»
Late responses: «late»
Misses: «misses»
False alarms: «false_alarms»

The real task is the same, with animal photos and object photos
instead of circles and squares. Some pictures play a sound.
You still respond only to the target pictures.

Press SPACE to begin the study.
```

### 15. Block intro — 19 words (×2, e.g. animals first)

```
Block 1 of 2: ANIMALS
Your target group is animals. Press the matching numpad key when you see one.

Press SPACE to continue.
```

### 16. Trial complete recap — 19 words (×8)

```
ANIMALS — Trial 1 complete.
Correct hits: «hits»
Late responses: «late»
Misses: «misses»
False alarms: «false_alarms» (please minimize these).

Press SPACE to continue.
```

### 17. Break — 28 words (counts down from 30 s, ends on its own)

```
Break — the study continues on its own in «30» seconds.

Rest your eyes and hands, then carry on when you are ready.

Press SPACE to continue now.
```

### 18. Study complete — 34 words

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

## B. Where the word wall actually is

Ranked by words on a single page:

| Rank | Screen | Words | Lines |
| --- | --- | --- | --- |
| 1 | How your responses are scored | 98 | 13 |
| 2 | Instructions part 1 | 83 | 7 |
| 3 | Instructions part 2 | 82 | 4 |
| 4 | Hand Placement | 56 | 7 |
| 5 | Practice complete | 49 | 10 |
| 6 | Study complete | 34 | 11 |
| 7 | Sound Check | 27 | 6 |
| 8 | Number Key Check | 29 | 6 |
| 9 | Break | 28 | 5 |

Screens 4–6 sit back to back before any picture appears, so the participant
reads **263 words / ~24 lines in three consecutive presses of SPACE**, with no
task action in between. That is the main wall. Screen 4 also carries an
unexplained abbreviation (`IE`), rests on jargon (`distracting, non-target
pictures`, `wrong object type`), and teaches four scoring words (hit, late,
miss, false alarm) that are then re-taught in full one screen later.

The secondary wall is repetition: the trial recap (×8) and practice summary
show the same four counters again, and block intro/recap repeat the block rule.

### Proposal (not applied yet)

1. **Instructions, 2 screens → 1**, ~165 words → ~70. Keep: two parts, animals
   then objects, press the corner key, do not press for non-targets, 0.9 s.
   Drop: forward references to "the next screen", the parenthetical re-explaining
   the block rule, and "Aim to maximize/minimize these".
2. **Scoring screen: four definitions → a 4-line aligned recap** that reuses the
   exact wording the recap screens already show (`Correct hits / Late / Misses /
   False alarms`), ~98 words → ~45, and make it the last thing before practice.
3. **Hand Placement: 56 → ~30 words.** The diagram already shows finger
   positions; the text only needs "index between 4 and 1, middle between 5 and 2,
   keep them there, SPACE when ready."
4. **Trial recap: 19 → 8 words.** `Trial 1 of 4 complete.` plus only the counter
   that is off (or a single compact line), because it appears 8 times.
5. **Practice complete: cut the "real task is the same" paragraph** (already said
   on the instructions screen) → ~25 words.
6. **Hand Placement / Num Key Check / Sound Check** are hardware checks, not
   instructions; they could gain a small "Setup 1 of 3" header so participants
   know where they are.
7. Consistent voice: screen 1 uses "index finger", screen 12 uses "you have
   0.9 seconds", the recaps use "please minimize these" (an instruction in a
   results table).

Ready to apply once you pick which of these to take.

---

## C. Participant 8 vs participant 10 — branch and commit

Both participants ran **identical code**. The recorded `git_commit` in
`participant_metadata.json` and `session_metadata.json` is `ca2c99d` for both
(and for participants 7, 9 and 11 as well — every session in `data/` today).

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
  since 2026-10-19 16:24:11 and had not moved since. → **cursor/shape-practice**
  → P7, P8, P9 all ran here.
- `2026-10-27 08:09:07 -0700`: `HEAD` moved `cursor/timing-log-rounding` →
  `clean-start`. → P10's preflight was `08:12:10 -0700` and P11's later still, so
  **both ran on clean-start**.

So the two participants differ in branch *name*, not in code: both branches
pointed at the same commit, `ca2c99d`.

### Branch creation and commit times

Branch creation is not stored in git objects, so these are reflog timestamps
(`branch: Created from …`), all local time (`-0700`):

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
(2026-10-27 08:08:46) were all made while `HEAD` sat on branches that participants
never ran, and `clean-start` was deliberately rolled back to `ca2c99d` before
P10. That means **the "trial went in the words they were taught" text change is
not in any participant's data** — the recap wording above is still the
`ca2c99d` wording.

One caveat worth knowing: the block-order difference between P8 and P10 is not a
branch effect. It is the counterbalancing rule
(`completed session count: even → animals first, odd → objects first`); P8 was
allocated at completed-count 2, P10 at 3.
