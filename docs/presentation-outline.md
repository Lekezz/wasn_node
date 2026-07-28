# Presentation build sheet: summer research talk

Slide by slide content for the PowerPoint. Each slide gives the title, the
bullets to put on the slide, what visual belongs there, and speaker notes for
what to say out loud. Keep the bullets short: what is written below under
"On the slide" is meant to be the whole slide, and the notes are what you say,
not what you show.

Sized for about 12 to 15 minutes, which is 15 slides plus backup. If you have
only 8 minutes, cut slides 7, 12 and 13 and move them to backup.

The talk should be honest that this is unfinished work. Slide 14 does that
explicitly, and the title slide says it too, so nobody has to guess.

---

## Slide 1: Title

**On the slide**
- Acoustic Source Localization on a Wireless Sensor Node
- Leke, undergraduate EE, University of Virginia
- Supervisor: Ben
- Summer 2026, work in progress

**Visual:** photo of the actual array on the breadboard pair, wires and all.

**Notes:** Set expectations in one sentence: this is a progress report on a
project that works end to end but is not finished, and you will be clear about
which parts are proven and which are not.

---

## Slide 2: The goal

**On the slide**
- A small node that hears a sound and reports the direction it came from
- Several nodes cross their bearings to locate a source
- This summer: one node, microphone to bearing in degrees

**Visual:** simple diagram, a sound source with two or three nodes around it,
dashed bearing lines crossing at the source.

**Notes:** Explain the eventual system briefly so the audience knows where this
is heading, then narrow immediately to what was actually built. Say the network
part is not started, so it is not a surprise later.

---

## Slide 3: How direction comes out of timing

**On the slide**
- Sound reaches the four mics at slightly different times
- Those differences depend on direction
- At 16 kHz, one sample is 62.5 microseconds, about 2.1 cm of travel
- So delays must be measured to a fraction of a sample

**Visual:** a plane wave arriving at an angle onto four mic dots, with the
wavefront hitting them in sequence and small delay labels.

**Notes:** This is the physical core of the talk and worth spending time on.
The punchline is the last bullet: whole-sample accuracy is not enough, which is
why the method is GCC-PHAT with interpolation rather than simple peak finding.
Mention that PHAT weights by phase, which makes it robust to the fact that a
clap has very uneven frequency content.

---

## Slide 4: System overview

**On the slide**
- 4x PDM MEMS mic, 16 kHz per channel
- STM32L552 at 96 MHz, DFSDM decimation, DMA into RAM
- Clap trigger, one second stored
- Bearing computed on the board, raw audio also dumped for checking

**Visual:** the block diagram, left to right:
mics, DFSDM, DMA, RAM, then splitting to "on-board GCC-PHAT then bearing over
UART" and "raw samples over UART to Python".

**Notes:** Walk it left to right once. Emphasise that both paths exist on
purpose: the board computes its own answer, and the raw audio still comes out
so the same samples can be checked against the reference implementation on a
PC. That dual path is what makes validation possible at all.

---

## Slide 5: Four microphones on two data pins

**On the slide**
- The chip has four DFSDM channels, not eight
- Each mic's SEL pin picks the rising or falling clock edge
- Two mics with opposite SEL share one wire without colliding
- Mics 0 and 1 on PE7, mics 2 and 3 on PB1, one clock net to all four

**Visual:** clock waveform with mic A driving during the high half and mic B
during the low half, plus the small wiring table.

**Notes:** A good "clever bit" slide. The original plan assumed eight channels;
the part has four. Rather than change parts, the SEL trick fits four
microphones into the available pins. Worth saying that this is the
manufacturer's intended use of SEL, not a hack.

---

## Slide 6: The problem that had to be solved first

**On the slide**
- The four digital filters must start on the same clock edge
- If they do not, every channel has an unknown offset
- An unknown offset is indistinguishable from real acoustic delay
- Fix: synchronized start, followers armed first, trigger filter last

**Visual:** two small plots side by side, one showing four aligned channels and
one showing a channel offset by an arbitrary amount.

**Notes:** This is the single point of failure of the whole approach. Everything
downstream measures time differences, so a constant per-channel offset poisons
every result and looks perfectly plausible. Say clearly that the design cannot
detect this from the data alone, which is why it was tested directly.

---

## Slide 7: Proving synchronization, before trusting anything

**On the slide**
- Mics packed in a tight line, about 2 cm apart
- At that spacing, true delay across the whole array is under 3 samples
- So a large offset could only be a sync fault, not physics
- Measured: 0.000, -0.481, -1.354, -1.801 samples, linear to 0.131 samples

**Visual:** photo of the in-line bring-up fixture next to the measured delay
numbers plotted against mic position, showing a straight line.

**Notes:** The design of the test is the point worth making. A spread out array
would have confounded a sync fault with real geometry; packing the mics tight
made the two separable. Note that this fixture could never localize anything
and was retired the moment it had done its job.

---

## Slide 8: Array geometry, and why it is not hardcoded

**On the slide**
- Built array: 9.25 x 9.9 cm, measured port to port with calipers
- Layout changed twice during the build, for physical reasons only
- So geometry lives in one registry file, not in the analysis scripts
- Condition number 1.07, meaning no blind directions

**Visual:** the layout scoring table (aperture, condition number, mean, p90,
worst) with the built layout highlighted.

**Notes:** Two lessons. First, mean error alone is misleading: the single-board
rectangle had a decent mean of 1.87 degrees but a p90 of 7.87 degrees because
its error piles up in four narrow cones. Second, condition number predicts that
directly, so the code warns based on it rather than on a hardcoded list of bad
angles. Mention the extreme case: a straight line of mics is rank 1 and returns
0 or 180 degrees no matter what, so the script refuses to run on one.

---

## Slide 9: How correctness was established

**On the slide**
- Build one trusted reference, check everything against it
- 1. Verify in simulation where truth is known
- 2. Prove channel sync separately from geometry
- 3. Share code between the test and the reference so they cannot drift
- 4. Compare the embedded port to the reference on identical samples

**Visual:** a simple chain diagram: simulation, then sync test, then real
capture, then embedded port, with each stage checked against the reference.

**Notes:** This is the methodology slide and arguably the most important one
for a research audience. The temptation with a localization project is to judge
results by whether the angle looks about right. That does not work, because
plenty of bugs produce plausible angles. Simulation numbers to quote: delay
bias under 0.001 samples, angle error under 0.1 degrees, degrading to about
0.4 degrees at 0 dB SNR.

---

## Slide 10: Result, and what dominated the error

**On the slide**

| Wall clearance | True | Estimated | Error | Residual |
|---|---|---|---|---|
| 65 cm | 0 deg | -3.40 deg | -3.40 | 0.875 |
| 2.1 m | 0 deg | 0.58 deg | +0.58 | 0.119 |

- Same code, same array, same room. Only the wall distance changed

**Visual:** the table large, plus a small sketch of direct path versus wall
reflection arriving inside the analysis window.

**Notes:** The best story in the project. At 65 cm the reflection arrived soon
enough to overlap the direct sound inside the analysis window and corrupted one
specific microphone pair. Moving to 2.1 m of clearance took the error to +0.58
degrees, which is at the simulation's own accuracy floor. Nothing in the code
changed. Point out that this is why the capture folders record the room setup:
the distance to the nearest wall is a property of the data, not of the run.

---

## Slide 11: A self-check that needs no ground truth

**On the slide**
- Delay is antisymmetric: A to B, plus B to C, must equal A to C
- It does not, when a reflection has corrupted a pair
- Worst violation across all triangles flags a bad capture
- Residual tracked the error: 0.119, 0.347, 0.499 samples against 0.6, 2.1, 6.4 deg

**Visual:** three mic dots in a triangle with the three delays labelled, and the
residual numbers beside the corresponding errors.

**Notes:** Make the point that this works without knowing the true angle, which
is what makes it usable in the field rather than only in a validation run. The
firmware prints a warning on its own when the residual passes 0.3 samples, and
it flagged both bad captures unprompted.

---

## Slide 12: Putting it on the microcontroller

**On the slide**
- Needs a 4096-point real FFT, so CMSIS-DSP
- Vendored by hand, not through the config tool, to avoid pulling in a USB stack
- The FFT tables alone compiled to 707 KB, against 512 KB of total flash
- Selective table mode: 707 KB to 40 KB, whole DSP set 712 KB to 44 KB
- Final image 55.7 KB, FFT buffers 48 KB in a separate RAM section

**Visual:** a before and after bar chart of the flash budget, with the 512 KB
limit drawn as a line the "before" bar crosses.

**Notes:** Good slide for showing that embedded work is about budgets. The
tables covered every FFT length and data type, and the generic initializer
referenced all of them so the linker could not drop any. Naming only the three
tables a 4096-point real FFT needs solved it. Timing estimate is about 10 ms of
FFT work per 32 ms frame, roughly 3x headroom.

---

## Slide 13: Failures were silent

**On the slide**
- Config regeneration reverted DMA settings twice, with no error
- UART size argument was 16-bit, so 128000 bytes truncated to 62464
- Every float printed as blank because of a linker specs choice
- Trigger threshold too high: the board just listened forever

**Visual:** none needed, or a screenshot of the blank-float report next to a
correct one.

**Notes:** The honest engineering slide. None of these announced themselves.
What worked as defence: committing before and after every regeneration so a
diff exposes changes, treating every compiler warning as guilty, and building
checks like the triangle residual that flag a bad result without needing to
know the right answer. Mention the blank float root cause since it is a good
story: integers printed fine, floats printed nothing, which is the exact
fingerprint of nano.specs printf without float support.

---

## Slide 14: What is not done

**On the slide**
- The board's own bearing has never actually printed, fix written but not flashed
- Ground truth exists at two angles only, three trials
- 315 degrees is worse than 0 degrees and it is not understood why
- Nothing is wireless, and there is one node
- Claps only. One second at a time. No continuous operation

**Visual:** none. Let the list stand on its own.

**Notes:** Do not rush this slide or apologise through it. Being precise about
what is unproven is what makes the proven parts credible. The most important
one is the first: the integer stages of the embedded port match the reference
exactly, but its arithmetic output is unvalidated because of the printf bug, so
the port should be described as partly validated and not as working.

---

## Slide 15: Next steps

**On the slide**
- Flash the current firmware, confirm the report prints
- Run the board-versus-reference comparison on a fresh capture
- Sweep eight angles, five trials each, produce the validation plot
- Then: multi-node, continuous operation, or harder sources

**Visual:** the four steps as a simple numbered path, with the first two marked
as blocking the rest.

**Notes:** Close by naming the decision you want input on: which of the three
directions in the last bullet is most useful to the group. Multi-node needs
time synchronization between nodes, which is a substantial problem in itself,
so it is worth raising rather than assuming.

---

## Backup slides

Keep these ready for questions rather than in the main flow.

- **B1: GCC-PHAT in more detail.** The correlation, the phase weighting, the
  interpolated peak. For anyone who asks why not plain cross correlation.
- **B2: The full geometry table.** All seven layouts scored, for anyone who
  asks why this shape.
- **B3: Signal chain detail.** DFSDM sinc3, Fosr 150, the shift to int16, the
  DMA ping-pong and how a whole frame is drained across four channels at once.
- **B4: Why the array is planar.** Bearing only, mirror ambiguity above and
  below the plane, and what a tetrahedron would cost.
- **B5: Capture file layout.** Sessions, angles, trials, and why the room setup
  is recorded with the data.

## Things to have ready but not on a slide

- A photo of the array with mics labelled 0 to 3, since people always ask which
  corner is which.
- One audio file of a clean clap, in case someone asks what the input sounds
  like.
- The bearing convention stated in one sentence: counterclockwise from +x,
  where +x points toward the mic1 and mic3 edge.
