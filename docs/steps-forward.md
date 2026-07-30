# Steps forward: handoff

Working document. Audience is whoever picks the project up next, or whoever is
standing at the bench with the board. Read the one page `bench-checklist.md`
alongside this.

## Where the project stands

The single-node pipeline is complete and validated on hardware. Proven:
single mic capture, four mic synchronized capture, clap triggering, the built
and ruler-measured 9.25 x 9.9 cm array, guided sweep capture, and localization
of real claps both offline in Python and on the board itself.

The result, session `2026-07-29-sweep`: eight angles at 45 degree spacing,
five claps each, source 1.1 m out, 2.1 m of wall clearance. 39 good claps,
mean absolute error 1.11 deg, worst 4.04 deg, mean trial-to-trial spread
0.99 deg. The same estimator on synthetic claps through the same geometry
gives 0.99 deg, so the real array sits at the simulation's own accuracy floor.

The CMSIS-DSP on-board localizer is validated. `compare_board.py` passes on all
44 captures taken since the current firmware was flashed: every one of the six
pair delays agrees with the Python reference to 0.000 samples, every bearing to
within 0.004 deg, and onset, transient peak and analysis window are exact
everywhere. Flash image 55,712 bytes at -O2, 48 KB of FFT buffers in `.ram2`.

Nothing is blocking. What remains is scope, not repair.

## What is open

- **Accuracy is bounded by the ground truth, not by the array.** Per-angle
  means run from -1.43 to +0.17 deg while the spread within any one angle stays
  between 0.38 and 1.82. That shape says each angle's hand-placed floor mark
  carries its own fixed offset which every clap from that mark inherits. The
  array is more repeatable than it is accurate against those marks, so it is
  probably better than 1.11 deg and this data cannot prove it.
- **One room, one sitting, one distance.** All 39 claps came from the same room
  at 1.1 m in a single session. Nothing tests whether the number survives a
  change of environment.
- **The array is planar,** so it gives bearing in the plane only. A source above
  the plane cannot be told from its mirror below. Elevation would need a
  non-planar layout such as a tetrahedron.
- **Only claps.** A broadband impulsive source is the easiest possible case.
- **Nothing is wireless and there is one node.** One node gives a bearing.
  Crossing bearings from several nodes to get a position is future work.
- **The triangle residual is a weak predictor of bearing error.** Trials with
  residuals up to 2.5 samples still gave bearings within a degree, while the one
  catastrophic capture in the sweep, 101 deg off because the trigger caught
  something that was not the clap, had a clean 0.070 residual. It reliably flags
  a corrupted capture but is not an error estimate. The 0.3 sample threshold
  `trial_quality.py` uses is already stricter than the data justifies, so do not
  tighten it further without a reason.

## The cheap experiments, in order

1. **A second room, or a second distance.** This is the cheapest experiment with
   the most to say about whether 1.11 deg generalises. Record a full sweep in a
   different room with the same command, keep it in its own session folder, and
   compare the two tables. Room setup is a property of the data: a session at a
   different wall distance is different data, not more of the same.
2. **Better ground truth, if the headline number matters.** The per-angle bias
   says the floor marks are the limit, so a more careful protractor setup, or a
   fixed source at a surveyed position, is what would raise the ceiling.
   Re-measuring the array with calipers belongs in the same piece of work: at
   today's accuracy the ruler is not the limiting factor, but it would become
   one if the ground truth improved.

## The open direction, to decide with Ben

This is a decision, not a task. All three are real projects and only one fits
the time available.

| Option | What it needs | Main risk |
|---|---|---|
| Multi-node, cross bearings to get a position | A second node built, plus inter-node time synchronization. That sync is the hard part and is its own problem: bearings can be crossed only if the two nodes agree on when things happened. | Time sync could consume all the remaining time and produce nothing demonstrable. |
| Continuous or streaming operation | Move from one second analysed once to a running buffer, per-frame localization, and a decision about what to do with frames containing no event. The RAM budget is already 128 KB/s against 256 KB total. | Less novel, but it makes the node look like a product instead of a demo. |
| Harder sources than claps | Speech, or continuous sources. GCC-PHAT is used on speech routinely, but the whole trigger and window design assumes a transient. | Likely exposes weaknesses in `find_clap` rather than in the localizer. |

Worth raising in the same conversation: the array is planar, so elevation is out
of reach as built. That is the one limitation that is cheap to accept now and
expensive to undo later, so it deserves an explicit decision rather than a
default.

---

## At the bench

### Recording a session

Set the room up per `bench-checklist.md`. The parts that matter most: at least
2 m from the nearest wall, source 1.5 m or more from the array and at array
height, +x axis (the mic1/mic3 edge) pointed at 0 deg.

Start the capture script BEFORE pressing the button. Only one process can hold
the COM port, so close any serial terminal first.

    python run_session.py COM4 --session <name> \
        --angles 0,45,90,135,180,225,270,315 --trials 5 \
        --notes "wall 2.1 m, clap 1.5 m"

Then:

    python plot_validation.py --session <name>
    python compare_board.py --session <name>

`run_session.py` runs both of those itself at the end of a session, so this is
only for re-running them later.

### What a good capture looks like

| Field | Expected | Source of the expectation |
|---|---|---|
| Channel health, all four mics | rms well above 5, no clipped samples, pre-clap rms spread under 2x | `check_sync.py` thresholds |
| GCC-PHAT lag of each channel vs mic0 | all within 8.32 samples (6.32 aperture plus 2.0 slack) | `check_sync.py`, derived from the ACTIVE geometry |
| peak/noise | comfortably above 20 | `localize_capture.py` warns below 20 |
| Bearing error on one clap | within a few degrees of truth. The sweep's mean was 1.11 deg and its worst 4.04 | session `2026-07-29-sweep` |
| Board's own report | same onset, window, delays and bearing as the Python reference on the same samples | `compare_board.py`, which passes on all 44 captures so far |

### Capture failure modes

| What you see | What it means |
|---|---|
| Green LED never goes out, capture script times out, nothing else | The trigger never fired. This is the documented silent failure. Either the board is running older firmware with a higher TRIGGER_LEVEL, or the clap really was too quiet. Clap harder and closer first, then confirm the flash actually took. |
| No report at all after the audio dump | Either firmware older than the localizer, or `Localize_Init` failed at boot. `catch_audio4.py` prints "(no bearing report from the board...)" in this case. |
| `FAILED: ...` line at the top of the report | The localizer bailed. The status texts are: localizer not initialised, array is collinear (rank 1), capture shorter than the window, least squares matrix is singular. Collinear or singular means the compiled-in `array_geometry.c` is wrong, not the room. |
| Flash size jumped by about 10 KB | Someone added `-u _printf_float` to the link. The report formats floats with integer arithmetic precisely so that is never needed. Take it back out. |
| One channel near silent (rms under 5) | SEL wiring on that mic, or the DFSDM channel's clock edge does not match that mic's SEL level. Not a software problem. |
| A channel alive but tens of samples off mic0 | Filter sync. Filters 1, 2, 3 must be armed with the sync trigger and filter 0 started LAST. `check_sync.py` prints the same list of causes on FAIL. |
| High triangle residual with a bearing that still looks plausible | Reflection. Measure the clearance again, including furniture, not just walls. |
| "weak transient" warning | Clap harder or closer. The firmware warns below a peak/noise ratio of 14.7, `localize_capture.py` below 20. |
| "very quiet, clap harder or closer" (peak under 2000) or "clipped" (peak at or above 32700) | Adjust distance. A clipped peak makes the transient position unreliable. |
| Bearing about 180 deg away from truth, everything else clean | Corner labelling. The mic wired as channel 0 must be the one entered as mic0 in `array_geometry.py`. A mislabelled corner reflects the bearing while every delay is right. |

### Sweep-level failure modes

| What you see | What it means |
|---|---|
| One angle much worse than its neighbours | Investigate it rather than averaging it away. See the worked example below. |
| Error grows smoothly toward a particular direction | Something directional in the room: a wall, a whiteboard, a monitor. Note where it is and re-run the sweep with the array moved. |
| Wide trial-to-trial spread at every angle | Clap consistency, or a source distance that keeps changing. Tape a mark for the source position at each angle. |
| Errors mirrored about an axis | Corner labelling or a swapped mic pair. Check the physical labels against the mic map. |

### The acceptance test

    python compare_board.py --session <name>

With no arguments it walks every trial on disk that has a saved board report.
Exit status is 0 when every compared trial passes and 1 otherwise, so it works
as a regression check after touching either implementation.

Each trial carries two independent answers to the same question: the board's
report saved as `trial<K>_bearing.txt`, and whatever the Python reference
produces from the stored `trial<K>.npy`. Same samples, two implementations.

| Field | Tolerance | Why |
|---|---|---|
| onset, transient peak, window start, window end | exact match required | integers on both sides from the same deterministic search |
| each of the six pair delays | 0.05 samples | the board is float32 and the Python float64, so they can never be bit identical. 1 mm of array position error is already 0.047 samples, and real captures miss truth by degrees, so a hundredth of a sample of numerical drift is irrelevant. The board also prints delays to 3 decimals, so quantization alone is 0.0005 samples |
| worst triangle residual | 0.05 samples | same reasoning |
| bearing | 0.5 degrees | far below the degrees of real-room error, and the board prints the bearing to 2 decimals |
| peak/noise | derived from the firmware's histogram noise estimate, not a flat percentage | the firmware bins the envelope into 2048 bins instead of sorting for a true median, so its quantization propagates as the square of the ratio. Onset is the far stricter test of the same quantity anyway |

A pass means "the CMSIS-DSP port agrees with the Python reference on every
trial above". That is a strong claim: it says the embedded arithmetic, the
vendored 4096 point FFT, the PHAT weighting, the least squares fusion and the
residual all reproduce a reference that was itself verified in simulation to
under 0.001 samples of delay bias. It does NOT say the bearing is correct in
the room.

| What you see | What it means |
|---|---|
| A delay or bearing row marked BAD | A genuine port bug. The same samples went into both sides, so this cannot be a room problem. Start from the first BAD row in report order, since a wrong delay explains a wrong residual and a wrong bearing downstream. |
| Only a window row is BAD, and there is a NOTE line above about windows differing | Documented divergence, not a bug. Both sides cut 2048 samples around the onset, but near a buffer end the Python shrinks the window while the firmware slides it to keep the FFT length fixed. Clap triggering makes this common rather than rare. `compare_board.py` re-runs the Python pinned to the board's window before comparing delays, so the delays stay honest and the window difference shows up as its own flagged row. Read the NOTE before hunting a bug. |
| `board reported FAILED: ...` so the trial is skipped | See the `FAILED` row in the capture failure modes above. |

The script has been verified against synthetic reports: an injected 0.817
sample delay error and a 6.6 deg bearing error were both caught, and a matching
report passed. So a clean pass is meaningful rather than a test that cannot
fail.

---

## Worked example: the 315 degree anomaly, closed

Worth reading before chasing the next angle that looks wrong, because the
answer turned out not to be the array.

315 deg looked for several days like a real direction-dependent defect: it was
consistently worse than 0 deg, and two trials disagreed with each other by
4.26 deg, far more scatter than a stable source should produce. The array has
condition number 1.07, so it has no blind directions and `POOR_CONES` is empty,
which ruled out the layout early and pointed at the measurement setup.

It was hand placement, and it came from clapping only 40 cm from the array.
Angular error from hand placement scales as 1/distance, so 5 cm of it is 7 deg
at 40 cm but under 2 deg at 1.5 m. At 40 cm it was simply not possible to place
a clap accurately enough to test a 2 degree effect.

The proof came from a diagnostic worth keeping. Each microphone pair has a null
direction where its delay should be zero, and for pair 1-2 on this array that
null sits at 316.94 deg, right next to the 315 being aimed at. That pair's delay
therefore locates the clap independently of the estimator, and it put the two
suspect trials at 316.8 and 322.8 deg, matching what the array had reported to
within 1.5 deg. The array had been right both times and the ground truth was
wrong. Re-run at 1.1 m from a taped mark in the sweep, 315 deg scores -1.41 deg,
in line with every other angle.

Wavefront curvature was the other suspect at 40 cm, and it is ruled out. The
textbook plane-wave bound `2D^2/lambda` is 0.856 m for this 13.549 cm aperture,
which would make 40 cm look marginal, but this array is centrosymmetric and the
leading curvature term cancels in the least squares fit. The predicted bearing
error at 315 deg and 40 cm is 0.027 deg against the 2.12 and 6.38 deg actually
seen, a factor of 29 too small to be the cause. The writeup has the detail,
including why this does not generalise to other layouts.

**The general diagnostic:** pairs 0-1 and 2-3 null at 90 and 270, pairs 0-2 and
1-3 at 0 and 180, pair 1-2 at 316.94, pair 0-3 at 136.94. Clap near a null and
that pair's delay should be near zero. If it is not, the source is not where you
think it is, and you know that before any analysis runs.

---

## Tooling note: run_session.py

`run_session.py` walks the sweep angle by angle, prompts you between angles,
quality checks every trial with a retake offer, resumes an interrupted sweep,
and runs the validation plot and the board-vs-Python comparison at the end.

Two extras worth knowing:

    python run_session.py --summary --session <name>

shows which angles are done and how many good trials each has, and opens no COM
port, so it is safe to run while thinking about something else. And

    python trial_quality.py <npy> --true-angle 315

runs the same bench check on any capture already on disk.

A trial you retake is renamed to `rejected<N>.npy` rather than deleted. Every
analysis script globs `trial*.npy`, so a rejected capture stays next to the good
ones as evidence but never reaches the plot. The reason is recorded in
`captures/<session>/quality_log.txt`.

The thresholds the check uses are all borrowed from code that already existed
rather than invented for the bench: clipping at 32700 and a silent channel below
rms 5 from `check_sync.py`, the weak transient ratio of 20 from
`localize_capture.py`, and the 0.3 sample triangle residual that `localize.c`
itself prints "inconsistent" at.

The manual path is not going away. `catch_audio4.py` with `--tag`, `--trials`,
`--session` and `--notes` does the same job, saves to the same
`captures/<session>/angle<NNN>/trial<K>.npy` layout through `capture_paths.py`,
and continues trial numbering past whatever is already on disk. If the guided
runner is missing or misbehaves, use `catch_audio4.py` and nothing downstream
notices the difference.
