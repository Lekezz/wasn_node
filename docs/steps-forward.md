# Steps forward: from here to a validated result

Working document, written 2026-07-28. Audience is whoever is standing at the
bench with the board. Read the one page `bench-checklist.md` alongside this.

## Where the project actually is

Proven on hardware: single mic capture, four mic synchronized capture, clap
triggering, the built and calipered 9.25 x 9.9 cm array, and offline
localization from real claps. Best real result is +0.58 deg error at a true
0 deg with 2.1 m of wall clearance, worst triangle residual 0.119 samples.

The CMSIS-DSP on-board localizer is written, builds, links (55,712 bytes of
flash, 49,152 bytes of FFT buffers in .ram2) and ran on hardware on
2026-07-27. It is PARTLY validated, and the precise meaning of that is:

- Validated: the integer stages. Onset, transient peak and analysis window
  matched the Python reference EXACTLY on all three captures of that session
  (625 / 369..2417, 745 / 489..2537, 534 / 278..2326). That covers find_clap
  including the histogram median the firmware uses instead of np.median.
- Not validated: everything downstream. Every float field printed blank on
  that run, so no delay, no residual and no bearing has EVER printed from the
  board.

The one fact that gates everything below: commit f5c3d78 fixed the blank
floats (f2s integer formatting) and lowered TRIGGER_LEVEL from 2500 to 1000,
and it has NEVER been built or flashed. Until it is, compare_board.py reports
every trial as SKIPPED and the port's arithmetic is unproven.

---

## Step 1: build and flash the current tree

### What to do

1. Open the project in STM32CubeIDE. Make sure the working tree is at f5c3d78
   or later, and that `git status` shows no half-finished edits you did not
   make.
2. Before building, confirm the two things CubeMX has silently reverted
   before: in `mic_test/Core/Src/stm32l5xx_hal_msp.c`, all four DFSDM DMA
   inits must say `DMA_CIRCULAR` and `DMA_..._ALIGN_WORD` on both sides. If
   they do not, the capture is broken regardless of anything else.
3. Build. Read every compiler warning. In this project a warning has been the
   only clue to a real bug twice.
4. Flash to the NUCLEO over ST-LINK.
5. Open a terminal on the VCP at 115200 (or just run the capture script, which
   holds the port), press the blue user button, clap.

### What success looks like

- The build links at roughly 55,712 bytes of flash. A large jump upward means
  something pulled float printf back in, which is what the f2s work exists to
  avoid.
- The green LED comes on when you press the button and GOES OUT when you clap.
- The report block prints real numbers where blanks used to be. Compare to the
  saved pre-fix report in
  `mic_sims_files/captures/2026-07-27-wall-2m/angle000/trial1_bearing.txt`,
  where the lines read `worst triangle residual  samples` and `BEARING  deg`
  with nothing between the words. After the fix every one of those gaps holds
  a number: peak/noise, the six pair delays, the max physical column, the
  residual, and the bearing.
- The blue LED comes on for about 11 s while the audio dumps.

### Failure modes and what they mean

| What you see | What it means |
|---|---|
| Green LED never goes out, capture script times out, nothing else | The trigger never fired. This is the documented silent failure. Either the old firmware is still on the board (TRIGGER_LEVEL 2500) or the clap really was too quiet. Clap harder and closer first, then confirm the flash actually took. |
| Floats still blank, integers fine | You flashed an old image. That exact pattern is the nano.specs printf fingerprint and f5c3d78 removed every `%f` from the project, so a fixed build cannot show it. Rebuild clean and reflash. |
| No report at all after the audio dump | Either firmware older than the localizer, or `Localize_Init` failed at boot. catch_audio4.py prints "(no bearing report from the board...)" in this case. |
| `FAILED: ...` line at the top of the report | The localizer bailed. The status texts are: localizer not initialised, array is collinear (rank 1), capture shorter than the window, least squares matrix is singular. Collinear or singular means the compiled-in `array_geometry.c` is wrong, not the room. |
| Flash size jumped about 10 KB | Someone added `-u _printf_float` to the link. That is IDE state a regeneration resets, which is exactly why f2s was used instead. Take it back out. |

---

## Step 2: one capture at a true 0 degrees

This is the reproduction check. The offline answer for this exact setup is
already on record, so the board has a number to be compared against.

### What to do

1. Set the room up per `bench-checklist.md`. The parts that matter most: at
   least 2 m from the nearest wall, source 1 m or more from the array, source
   at array height, +x axis (the mic1/mic3 edge) pointed at the source.
2. Start the capture script BEFORE pressing the button. Only one process can
   hold the COM port.

   Guided runner (see the tooling note at the end of this document):

       python run_session.py COM4 --session 2026-07-29-flash-check --angles 0 --trials 1

   Manual fallback, which works today:

       python catch_audio4.py COM4 --tag angle000 --session 2026-07-29-flash-check --notes "wall 2.1 m, clap 1 m, first run of f5c3d78"

3. Press the blue button, wait for the green LED, clap once.
4. Then, offline:

       python check_sync.py
       python localize_capture.py --true-angle 0

### What success looks like

| Field | Expected | Source of the expectation |
|---|---|---|
| Channel health, all four mics | rms well above 5, no clipped samples, pre-clap rms spread under 2x | check_sync.py thresholds |
| GCC-PHAT lag of each channel vs mic0 | all within 8.32 samples (6.32 aperture + 2.0 slack) | check_sync.py, derived from ACTIVE geometry |
| peak/noise | comfortably above 20 | localize_capture.py warns below 20; the 2026-07-24 capture read 31.1 after the DC fix |
| Estimated bearing | near 0.58 deg, error near +0.58 deg | 2026-07-27 offline run at the same setup |
| Worst triangle residual | near 0.119 samples | same run |
| Board's own report | prints the same onset and window the Python does, and now prints its own bearing and residual too | integer stages already matched exactly on three captures |

Getting close to +0.58 deg and 0.119 samples again means the room, the array
and the firmware are all where they were, and the new float path is producing
numbers in the right neighbourhood. It is not yet an acceptance test. Step 3
is.

### Failure modes and what they mean

| What you see | What it means |
|---|---|
| One channel near silent (rms under 5) | SEL wiring on that mic, or the DFSDM channel's clock edge does not match that mic's SEL level. Not a software problem. |
| A channel alive but tens of samples off mic0 | Filter sync. Filters 1, 2, 3 must be armed with the sync trigger and filter 0 started LAST. check_sync.py prints the same list of causes on FAIL. |
| Residual well above 0.119, say 0.3 to 0.9, with a bearing that still looks plausible | Reflection. This is exactly the 2026-07-24 signature: -3.40 deg error with a 0.875 sample residual from a wall 65 cm away. Measure the clearance again, including furniture, not just walls. |
| "weak transient" warning | Clap harder or closer. The firmware warns below a peak/noise ratio of 14.7, localize_capture.py below 20. |
| catch_audio4.py says "very quiet, clap harder or closer" (peak under 2000) or "clipped" (peak at or above 32700) | Adjust distance. A clipped peak makes the transient position unreliable. |
| Bearing about 180 deg away from truth, everything else clean | Corner labelling. The mic wired as channel 0 must be the one entered as mic0 in array_geometry.py. A mislabelled corner reflects the bearing while every delay is right. |

---

## Step 3: run compare_board.py, the acceptance test

This is the milestone 7 gate. Everything before it is evidence; this is the
pass or fail.

### What to do

    python compare_board.py --session 2026-07-29-flash-check

With no arguments it walks every trial on disk that has a saved board report.
Exit status is 0 when every compared trial passes and 1 otherwise, so it can
be used as a regression check after touching either implementation.

### What it actually does, and why that is fair

Each trial carries two independent answers to the same question: the board's
report saved as `trial<K>_bearing.txt`, and whatever the Python reference
produces from the stored `trial<K>.npy`. Same samples, two implementations.
compare_board.py reads both and compares field by field.

Tolerances, and where they come from:

| Field | Tolerance | Why |
|---|---|---|
| onset, transient peak, window start, window end | exact match required | integers on both sides from the same deterministic search |
| each of the six pair delays | 0.05 samples | the board is float32 and the Python float64, so they can never be bit identical. 1 mm of array position error is already 0.047 samples, and real captures miss truth by degrees, so a hundredth of a sample of numerical drift is irrelevant. The board also prints delays to 3 decimals, so quantization alone is 0.0005 samples |
| worst triangle residual | 0.05 samples | same reasoning |
| bearing | 0.5 degrees | far below the degrees of real-room error, and the board prints the bearing to 2 decimals |
| peak/noise | 2 percent relative, floor 0.05 | ratio, not an absolute level |

### What a pass means

"The CMSIS-DSP port agrees with the Python reference on every trial above."
That is the whole claim, and it is a strong one: it says the embedded
arithmetic, the vendored 4096 point FFT, the PHAT weighting, the least squares
fusion and the residual all reproduce a reference that was itself verified in
simulation to under 0.001 samples of delay bias. It does NOT say the bearing
is correct in the room. Room accuracy is step 4's job.

### Failure modes and what they mean

| What you see | What it means |
|---|---|
| `summary: 0 passed, 0 failed, N skipped`, with "this report has no float fields" | Step 1 did not actually happen. The board is still running pre-f5c3d78 firmware. Reflash and re-record. |
| A delay or bearing row marked BAD | A genuine port bug. The same samples went into both sides, so this cannot be a room problem. Start from the first BAD row in report order, since a wrong delay explains a wrong residual and a wrong bearing downstream. |
| Only a window row is BAD, and there is a NOTE line above about windows differing | Documented divergence, not a bug. Both sides cut 2048 samples around the onset, but near a buffer end the Python shrinks the window (numpy re-derives the FFT length) while the firmware slides it (LOC_FFT_LEN is fixed and the buffers are sized for it). compare_board.py already re-runs the Python pinned to the board's window before comparing delays, so the delays stay honest and the window difference shows up as its own flagged row. Read the NOTE before hunting a bug. |
| `board reported FAILED: ...` so the trial is skipped | See the FAILED table in step 1. |
| "Nothing was actually validated" | Every trial skipped. Same as the first row. |

The script has been verified against synthetic reports: an injected 0.817
sample delay error and a 6.6 deg bearing error were both caught, and a
matching report passed. So a clean pass is meaningful rather than a test that
cannot fail.

---

## Step 4: the 8 angle by 5 trial sweep, then the plot

The current validation plot rests on 3 trials at 2 angles, which is thin for a
deliverable. 8 angles at 45 degree steps, 5 trials each, is 40 claps.

### What to do

Keep the whole sweep in ONE session folder, and do not move the array
partway through. Room setup is a property of the data: a session recorded
against a different wall distance is different data, not more of the same.
plot_validation.py takes `--session` for exactly this reason.

Guided runner (see the tooling note):

    python run_session.py COM4 --session 2026-07-29-sweep --angles 0,45,90,135,180,225,270,315 --trials 5

Manual fallback, one command per angle, which works today:

    python catch_audio4.py COM4 --tag angle000 --session 2026-07-29-sweep --trials 5 --notes "wall 2.1 m, clap 1 m, source at array height"
    python catch_audio4.py COM4 --tag angle045 --session 2026-07-29-sweep --trials 5
    ... and so on through angle315

Trial numbers continue past whatever is already saved for that angle, so if an
angle gets interrupted you just rerun the same command and it picks up where
it left off. Rotate the SOURCE around the array, or rotate the array, but be
consistent and write down which in the notes.

Then:

    python plot_validation.py --session 2026-07-29-sweep
    python compare_board.py --session 2026-07-29-sweep

### What success looks like

- The printed table shows 8 angles and 40 claps, with a per-angle mean error,
  a standard deviation, and a mean and max absolute error.
- No angle has fewer than 2 trials. plot_validation.py prints a NOTE naming
  any angle with a single trial, because its error bar is zero and that is not
  real spread.
- `validation_plot.png` has red measured points sitting near the black ideal
  line and near the blue simulation curve, with visible but small error bars.
- compare_board.py passes on all 40 trials, which turns the sweep into 40
  independent confirmations of the port rather than one.

A note on what number to expect: there is no agreed pass threshold for the
sweep, and I am not going to invent one. For scale, the simulation reference
for this layout is about 0.8 deg mean error, the offline estimator scored a
mean of 0.99 deg on synthetic sources through the real geometry, and the one
clean real capture was +0.58 deg. Simulation models no reverberation, so real
numbers should be worse than that, and the honest deliverable is the measured
mean and spread plus the room conditions they were taken under. Agree a target
with Ben rather than back-filling one.

### Failure modes and what they mean

| What you see | What it means |
|---|---|
| One angle much worse than its neighbours | The 315 deg situation. Do not average it away, investigate it. Step 5. |
| Error grows smoothly toward a particular direction | Something directional in the room: a wall, a whiteboard, a monitor. Note where it is and re-run the sweep with the array moved. |
| Wide trial-to-trial spread at every angle | Clap consistency, or a source distance that keeps changing. Tape a mark for the source position at each angle. |
| Errors mirrored about an axis | Corner labelling or a swapped mic pair. Check the physical labels against the mic map in CLAUDE.md. |

---

## Step 5: investigate 315 degrees

315 deg was worse than 0 deg on both trials and it is not understood.

| Trial | True | Estimated | Error | Residual | Firmware flagged? |
|---|---|---|---|---|---|
| angle000/trial1 | 0 | 0.58 | +0.58 | 0.119 | no |
| angle315/trial1 | 315 | 317.12 | +2.12 | 0.347 | yes, inconsistent |
| angle315/trial2 | 315 | 321.38 | +6.38 | 0.499 | yes, inconsistent |

Two things stand out. First, the residual tracks the error monotonically, and
the firmware called both 315 trials inconsistent on its own (it prints
"(inconsistent: suspect a reflection)" whenever the worst residual exceeds 0.3
samples). Second, the two 315 trials disagree with EACH OTHER by 4.26 deg,
which is far more scatter than one setup with a stable source should produce.

The array has condition number 1.07, so it has no blind directions and
POOR_CONES is empty. That rules out the layout as the cause and points at
something physical on that diagonal.

### What to do, in order

1. Write down what is physically on the 315 degree diagonal from the array:
   a wall, a table edge, a monitor, a chair, a laptop, and the position of
   your own body when clapping. Reflectors close to the source are as bad as
   reflectors close to the array.
2. Re-record 315 with 5 trials, in the same session as the rest of the sweep,
   and see whether the scatter reproduces.
3. Look at which PAIR is bad, not just the total. On the 2026-07-24 wall
   session the failure was one pair: pair 1-2 read +3.201 samples where the
   other five implied +4.076, and the per-triangle residuals were -0.875 and
   -0.750 on the two triangles containing that pair while the other two
   triangles were fine at -0.065 and +0.060. Refitting without the bad pair
   took the error from -3.40 to -0.55 deg. If 315 shows the same one-pair
   pattern, it is a reflection, and which pair it is tells you roughly where
   the reflector sits.
4. Predict the echo and look for it. Image source method: a surface d metres
   away adds 2d of path, which is 2d / 343 seconds, which is 2d / 343 * 16000
   samples. On 2026-07-24 that predicted 60.6 samples for a 65 cm wall and the
   envelope showed a bump at +57 samples at 0.42 of the direct peak. Do the
   same arithmetic for whatever sits on the 315 diagonal and check the
   envelope at that offset.
5. Rotate the whole array by 45 degrees so that the same physical spot in the
   room becomes 0 deg in the array frame, and re-record. If the error follows
   the ROOM position, it is acoustics. If it follows the ARRAY direction, it
   is the array or the geometry table, and the condition number argument needs
   revisiting.
6. Only if all of that comes up clean, look at the estimator: check that the
   pair delays at 315 do not sit near the max physical column (the report
   flags EXCEEDS PHYSICS when they do), since a delay pinned at the search
   limit biases the fit.

### What success looks like

Either a reproducible explanation written into the session notes.txt ("the
315 diagonal points at the metal cabinet 1.2 m away, echo predicted at 112
samples, visible in the envelope, pair 1-3 corrupted"), or 315 comes back
clean after moving the array and the original result is attributed to a room
feature that has been recorded. Both are acceptable outcomes. "It got better
when we re-ran it" with no reason written down is not.

---

## Step 6: the open direction, to decide with Ben

This is a decision, not a task. All three are real projects and only one fits
the time left.

| Option | What it needs | Main risk |
|---|---|---|
| Multi-node, cross bearings to get a position | A second node built, plus inter-node time synchronization. This is the hard part and it is its own problem: bearings can be crossed only if the two nodes agree on when things happened. | Time sync could consume all the remaining time and produce nothing demonstrable. |
| Continuous or streaming operation | Move from one second analysed once to a running buffer, per-frame localization, and probably a decision about what to do with frames containing no event. RAM budget is already 128 KB/s against 256 KB total. | Less novel, but it makes the node look like a product instead of a demo. |
| Harder sources than claps | Speech, or continuous sources. A clap is the easiest possible case: broadband and impulsive. GCC-PHAT is used on speech routinely, but the whole trigger and window design assumes a transient. | Likely exposes weaknesses in find_clap rather than in the localizer. |

Worth raising in the same conversation: the array is PLANAR, so it gives
bearing in the plane only and a source above the plane is indistinguishable
from its mirror below. Elevation needs a non-planar layout such as a
tetrahedron. That is the one limitation that is cheap to accept now and
expensive to undo later, so it deserves an explicit decision rather than a
default.

---

## Tooling note: run_session.py

`run_session.py` now exists in `mic_sims_files/` and the commands shown in
steps 2 and 4 are its real interface, checked against the built version on
2026-07-28. It walks the sweep angle by angle, prompts you between angles,
quality checks every trial with a retake offer, resumes an interrupted sweep,
and runs the validation plot and the board-vs-Python comparison at the end.

Two extras worth knowing:

    python run_session.py --summary --session <name>

shows which angles are done and how many good trials each has, and opens no
COM port, so it is safe to run while thinking about something else. And

    python trial_quality.py <npy> --true-angle 315

runs the same bench check on any capture already on disk.

A trial you retake is renamed to `rejected<N>.npy` rather than deleted. Every
analysis script globs `trial*.npy`, so a rejected capture stays next to the
good ones as evidence but never reaches the plot. The reason is recorded in
`captures/<session>/quality_log.txt`.

The thresholds the check uses are all borrowed from code that already existed
rather than invented for the bench: clipping at 32700 and a silent channel
below rms 5 from `check_sync.py`, the weak transient ratio of 20 from
`localize_capture.py`, and the 0.3 sample triangle residual that `localize.c`
itself prints "inconsistent" at.

The manual path is not going away. `catch_audio4.py` with `--tag`, `--trials`,
`--session` and `--notes` does the same job today, saves to the same
`captures/<session>/angle<NNN>/trial<K>.npy` layout through capture_paths.py,
and continues trial numbering past whatever is already on disk. If the guided
runner is missing or misbehaves, use catch_audio4.py and nothing downstream
notices the difference.
