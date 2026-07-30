# Acoustic source localization on an STM32 wireless sensor node

**Leke, undergraduate EE, University of Virginia. Summer 2026. Supervisor: Ben.**
Status as of 2026-07-30.

## 1. What this is

A wireless acoustic sensor node that listens with four microphones and reports the bearing of a sound source. A NUCLEO-L552ZE-Q (STM32L552, Cortex-M33 at 96 MHz) samples four MEMS microphones in a 9.25 cm by 9.90 cm rectangle. When a clap happens, the node measures the small differences in arrival time between microphones and turns them into a direction. Capture, cross correlation and the direction fit all run on the microcontroller, with a matching Python implementation kept as the reference the firmware is checked against.

The headline result: on an 8-angle sweep in a real room, mean absolute bearing error was **1.11 degrees**, matching what simulation of the same array predicts. The remaining error appears to come from how accurately the source was marked on the floor, not from the array.

### Summary of key numbers

| Quantity | Value |
| --- | --- |
| Microphones | 4 x MP34DT01-M PDM, 16 kHz PCM via DFSDM |
| Array | 9.25 cm x 9.90 cm rectangle, ruler measured to about 0.5 mm |
| Aperture (diagonal) | 13.549 cm, which is 6.32 samples of delay |
| Condition number / rank | 1.070 / 2 (no blind directions) |
| Mean absolute bearing error | 1.11 deg over 39 claps, 8 angles |
| Worst single clap | 4.04 deg |
| Trial to trial spread | 0.99 deg mean |
| Simulation on same geometry | 0.99 deg mean |
| Firmware vs Python | delays 0.000 samples, bearing within 0.004 deg, 44 captures |
| Flash, release (-O2) | 55,712 bytes of 512 KB |
| Flash / RAM, debug build | 87,904 / 217,448 bytes (256 KB RAM) |
| CMSIS-DSP FFT tables | cut from 712 KB to 44 KB |

## 2. Hardware and capture

Each MP34DT01-M is a PDM microphone: a one bit stream at a high rate that a digital filter turns into ordinary PCM. The STM32L5's DFSDM peripheral is built for this. One 2.4 MHz clock feeds all four microphones, and a sinc3 filter with oversampling ratio 150 gives 16 kHz, 16 bit audio per channel.

**The two-wire trick.** The MP34DT01-M has a SEL pin choosing which half of the clock cycle it drives its data line on: SEL to ground drives while the clock is high, SEL to 3V3 while it is low. Two microphones therefore share one data wire without colliding, so four microphones need only two data pins. That matters because the DFSDM here has exactly four channels and Nucleo pin routing is limited.

**Sample alignment.** GCC-PHAT measures delays to a fraction of a sample, so one sample of channel misalignment would be a large fraction of the array's whole aperture. Filters 1, 2 and 3 are armed with a sync trigger and filter 0 is started last, so all four begin converting on the same clock edge. The four DMA buffers are then handled as one synchronized frame: the code acts only once all four transfer flags of a phase are up, and treats all four identically. No path exists by which one channel can advance a frame ahead of another.

**Clap triggering.** A button press arms the array, 4000 warm-up samples (0.25 s) are discarded so the microphones and filters settle, and then the first sample above a threshold becomes sample 0 of a stored one second, four channel recording. That recording is analysed either on the board or offline over UART.

## 3. How the algorithms work

Two algorithms: one measures the delay between a pair of microphones, the other turns six such delays into a direction.

### 3.1 GCC-PHAT: measuring the delay between two microphones

**The problem.** Two microphones 9.25 cm apart hear the same clap at slightly different times. At 343 m/s that difference is at most 270 microseconds, which at 16 kHz is 4.3 samples. For bearing accuracy around a degree we need that delay to a small fraction of a sample. One sample corresponds to 2.14 cm of path difference, so integer sample resolution is far too coarse on its own.

**Plain cross correlation, computed through the FFT.** The classical way to find a delay is cross correlation: slide one signal against the other and find the shift where they overlap best. Done directly this is O(n^2). Correlation in time is multiplication in frequency, so there is a shortcut: FFT both windows, multiply one by the complex conjugate of the other, inverse FFT. That is O(n log n), and for the 2048 sample window used here it is the difference between millions of operations and tens of thousands.

**Why zero pad to twice the length.** The FFT computes *circular* correlation: it treats each window as wrapping from end back to start. A genuine peak near the edge of the buffer would wrap around and reappear at completely the wrong lag. Padding both windows with zeros out to at least twice their length makes the circular correlation equal the linear one over the lags we care about. The firmware uses `LOC_WINDOW_LEN = 2048` (256 samples before the onset, 1792 after) and `LOC_FFT_LEN = 2 * LOC_WINDOW_LEN = 4096` for exactly this reason. The Python does the same by asking numpy for `n = len(a) + len(b)`.

**The PHAT weighting.** This is what makes the method work in a real room. After forming the cross spectrum `R = A * conj(B)`, every frequency bin is divided by its own magnitude, so only phase survives: `R[k] = R[k] / (|R[k]| + 1e-12)`.

Phase is *when* and magnitude is *what*, and only *when* carries direction information. Practically, this flattens the spectrum. Without it, a loud narrow band, or a reflection that happens to reinforce one band, dominates the sum and smears or shifts the correlation peak. With it, every band votes equally on the delay and the peak stays sharp.

The cost is real. Dividing by magnitude also amplifies bins containing nothing but noise, since a nearly empty bin is scaled up to the same weight as one full of signal. PHAT therefore works best on broadband impulsive sources where most bins genuinely carry the event. A clap is close to ideal; a narrowband hum or a quiet source would be much harder, and that is one of the main limits on generalising these results. The `1e-12` guard keeps a silent bin from dividing by zero and leaves it near zero, which is correct since it carries no timing.

One more detail: each window has its mean subtracted before the FFT. DC is a large spike in the zero frequency bin, and PHAT would normalise that spike up to the same weight as everything else and let it dominate.

**Sub-sample interpolation.** The inverse FFT gives a correlation curve at integer lags, but the true peak almost never lands on a sample. Both implementations fit a parabola through the peak bin and its two neighbours and take the vertex:

`offset = 0.5 * (y0 - y2) / (y0 - 2*y1 + y2)`

with y0, y1, y2 the magnitudes at peak-1, peak and peak+1. The reported delay is `best_lag + offset`. Both skip the interpolation when the peak sits on the edge of the searched range, since there is no neighbour on one side, and both guard a near zero denominator. This step takes resolution from 2.14 cm to well under a centimetre. Without it, single degree accuracy on an array this small would be impossible.

**The physical search limit.** The delay between two microphones cannot exceed their spacing divided by the speed of sound: 4.31 samples for the 9.25 cm baseline, 6.32 for the 13.549 cm diagonal. `Geom_MaxTauSamples()` computes this per pair and the peak search runs only over lags inside that window plus a sample of margin. Anything outside is not a possible arrival and is discarded for free. In an echoey room this kills most spurious peaks, and it is the cheapest robustness measure in the pipeline.

### 3.2 The direction estimate

**Far field assumption.** If the source is far enough away compared to the array size, the arriving wavefront is effectively flat across the array. Distance then stops mattering and all that survives is the direction, a unit vector `u = (ux, uy)` pointing from the array toward the source.

**The model.** For a plane wave, arrival times at microphones i and j satisfy

`t_j - t_i = ((pos_i - pos_j) . u) / c`

In words: take the vector between the two microphones, project it onto the direction the sound comes from, and divide by the speed of sound. That projection is the extra distance the wave travels to reach the later microphone. A microphone further along `u` is closer to the source and hears the clap earlier.

**Six equations, two unknowns.** The left side is measured by GCC-PHAT; the right side is linear in `u`. Each pair gives one equation in two unknowns, and four microphones give six unique pairs, so the system is 6 by 2, overdetermined by four equations. **That redundancy is the point.** If one pair's correlation peak is pulled onto the wrong lobe by a reflection, the other five outvote it and the direction barely moves.

**Least squares.** Stack the baselines into a matrix A (row p is `pos_i - pos_j`) and the delays, converted from samples to metres of path difference, into a vector b, then solve `A u = b` in the least squares sense. Python calls `numpy.linalg.lstsq`. The firmware forms the normal equations `(A'A) u = A'b`, where `A'A` is only 2 by 2 and inverts in closed form with a determinant and four multiplications. No iteration, no library. Bearing is `atan2(uy, ux)`, wrapped to 0..360. The length of `u` is discarded, since noise makes it drift from 1 and only its direction carries information.

**Why the condition number matters.** It is the ratio of A's two singular values, and it measures how evenly the baselines cover direction space. Near 1 means every direction is constrained about equally, so accuracy is uniform with no blind spots. This array scores **1.070**. A high value means narrow cones of bearing where a small delay error produces a large angle error: an earlier, much thinner 2.8 cm by 10 cm layout had four such cones reaching 8 degrees. The extreme case is a collinear array, where every baseline is parallel, A is rank 1, the across-axis component of `u` is unconstrained, and the angle collapses to 0 or 180 regardless of truth. Both implementations compute the rank and refuse to answer if it is 1, rather than printing a plausible looking number.

**The triangle residual, honestly.** A single plane wave forces every triangle of delays to close: `d(i,j) + d(j,k)` must equal `d(i,k)`. The code checks all four triangles and reports the worst residual. It costs almost nothing and reliably flags a corrupted capture. But the project measured how well it predicts bearing error, and the answer is poorly. Trials with residuals up to 2.5 samples still gave bearings within a degree, while the one catastrophic capture in the dataset, 101 degrees off because the trigger caught something that was not the clap, had a clean residual of 0.070. It is a corruption detector, not an error bar, and the 0.3 sample warning threshold in the bench check is already stricter than the data justifies.

## 4. Getting it onto the microcontroller

**The FFT table problem.** CMSIS-DSP ships twiddle tables for every FFT size it supports. Built as delivered that is about **712 KB** of tables on a chip with 512 KB of flash, so the project does not fit at all. The fix was a vendored copy of only `arm_rfft_fast_f32` and its dependencies plus a `cmsis_dsp_config.h` naming only the three tables a 4096 point real FFT needs, taking the set to **44 KB**. A 16x reduction, and the difference between the project existing and not. Adding the library by hand rather than through CubeMX also stops regeneration undoing it. Details in `docs/CMSIS_DSP_SETUP.md`.

**Float printing without float printf.** The project links `--specs=nano.specs`, whose printf omits float support. The first hardware run came back with `BEARING  deg` and six blank pair delays while every integer field printed fine: a silent total loss of exactly the numbers the port exists to produce. Enabling float printf works but costs roughly 10 KB of flash and is an IDE linker setting, precisely the kind of state a CubeMX regeneration resets. Instead a small `f2s()` helper formats floats with integer arithmetic, and there is no `%f` anywhere in the firmware.

**Where the memory actually is.**

| Item | Size |
| --- | --- |
| `recording[4][16000]` int16, one second four channels | 128,000 bytes |
| `dma_buf[4][2048]` int32 | 32,768 bytes |
| Those two together | about 96% of `.bss` |
| FFT working buffers in `.ram2` | 49,152 bytes |
| Debug flash (87,760 text + 144 data) | 87,904 bytes |
| Debug RAM | 217,448 bytes |
| Release flash at -O2 | 55,712 bytes |

The three 16 KB FFT buffers live in `.ram2`, a separate 64 KB bank nothing else uses, because the main 192 KB bank is nearly full once the capture buffers are placed. They are marked NOLOAD so startup does not zero 48 KB that gets overwritten immediately.

**Where the time goes.** Cycle level profiling using the Cortex-M33 DWT counter costs 932 bytes of flash and 40 bytes of RAM. Measured on hardware at 96 MHz:

| Stage | Cycles | Time | Share |
|---|---|---|---|
| `find_clap` | 8,677,046 | 90.4 ms | 22% |
| GCC-PHAT, all six pairs | 29,526,954 | 307.6 ms | 77% |
| Fit and triangle residual | 2,312 | 0.024 ms | 0% |
| **Total** | **38,206,623** | **398.0 ms** | **100%** |

Three things stand out. The least squares fit, which is the part that looks like the actual localization, is free: 2,312 cycles, four ten thousandths of the total. All the cost is in the signal processing that produces the six delays. GCC-PHAT dominates at 77%, which is 51.3 ms per pair, and that cost scales with the number of PAIRS rather than microphones. Dropping to three microphones would halve it, saving roughly 154 ms, about 39% of the total. That is the real argument for fewer microphones, and it is a compute argument, not a memory one.

One caveat that matters: this is the **Debug build, compiled at -O0**. The Release build at -O2 is 55,712 bytes and would be substantially faster, but it has not been profiled, so no speedup factor is claimed here. Treat 398 ms as an upper bound rather than the shippable figure.

## 5. Validating the port against the reference

The Python implementation came first and was verified in simulation: delay bias under 0.001 samples, angle error under 0.1 degrees on synthetic sources with known ground truth. The firmware is an independent implementation of the same math in C, using CMSIS-DSP rather than numpy, float32 rather than float64, hand rolled 2x2 normal equations rather than `lstsq`, and a histogram median rather than `np.median`.

`compare_board.py` runs both on **the same recorded samples**, field by field, across **44 captures**. Every pair delay agrees to **0.000 samples**, every bearing to within **0.004 degrees**, and onset and transient peak indices are **exact everywhere**. That is a strong claim because the two implementations share no code, and because the Python side was independently verified against known ground truth in simulation. Agreement at this level means neither carries a bug the other does not, on this data.

Two caveats, documented rather than hidden:

- **peak/noise cannot be compared with a flat percentage.** The firmware estimates the noise floor as the median of a 2048 bin histogram of the envelope, because storing the full 16000 sample envelope as float would take 64 KB that does not exist. That binning quantizes the estimate, and the error propagates into the reported SNR as roughly `snr^2 / (2 * (BINS - 1))` on top of float32 effects, so the comparison uses a modelled margin. Onset is the far stricter test of the same quantity anyway, since the walk-back threshold depends on the noise estimate directly, and onset matches exactly.
- **The window rows disagree by construction when the onset lands below sample 256.** Python clamps with `max(0, onset - 256)` and uses a shorter window, letting numpy re-derive the FFT length. The firmware has fixed size buffers, so it slides the window instead to keep the FFT length at 4096. Clap triggered capture makes this common, not rare. The comparison prints "slid", checks the slide is legitimate, and excuses that row. Everything else still has to match.

## 6. Results: the angle sweep

Session `2026-07-29-sweep`: 8 angles at 45 degree spacing, 5 claps each, source 1.1 m from the array, array 2.1 m from the nearest wall. 39 claps passed the bench quality check and were kept.

| Metric | Value |
| --- | --- |
| Mean absolute bearing error | 1.11 deg |
| Worst single clap | 4.04 deg |
| Mean trial to trial spread within an angle | 0.99 deg |
| Simulation, same geometry | 0.99 deg |

Reverberation was expected to cost several degrees over the simulation and did not. The hardware sits at the simulation's own accuracy floor, which was not the expected outcome and is the most encouraging result in the project.

**The per-angle bias, and why it indicts the ground truth.** Per-angle mean errors run from **-1.43 to +0.17 degrees**, while the spread *within* each angle stays between **0.38 and 1.82 degrees**. That shape is diagnostic. If the array were the limit, error would scatter randomly within each angle. Instead each angle has its own consistent offset shared by all five of its claps, which is the signature of a fixed setup error per angle: each mark was placed on the floor by hand, and every clap at that angle inherits its offset.

At 1.1 m, a 5 cm placement error is already 2.6 degrees, more than the entire measured mean. Working backwards, the marks must have been good to roughly 2 cm for the observed numbers to be possible. That is a bound on the marks, not a measurement of them, but it does establish that ground truth is at least as tight a constraint as the array. Repeatability is better than accuracy against the marks, so the array is probably better than 1.11 degrees and the current setup cannot prove it.

## 7. Two studies

### 7.1 Does the fourth microphone earn its place?

A paired comparison on the same 39 claps, dropping one channel in software and re-running the fit through the surviving triangle.

| Configuration | Mean abs error | Worst | Spread |
| --- | --- | --- | --- |
| 4 mic | 1.11 deg | 4.04 deg | 0.99 deg |
| Best 3 mic triangle | 1.76 deg | 7.70 deg | 0.86 deg |
| Worst 3 mic triangle | 2.19 deg | 17.64 deg | 1.72 deg |

Pooled over all four triangles and 39 claps (156 trial-configs), the paired change was **mean +0.88 degrees, median +0.11, worst single degradation +17.04**, with 93 of 156 getting worse.

The gap between mean and median is the finding. The typical clap barely notices the missing microphone; a minority collapse and drag the average. The failures concentrate **by direction**, and a per bearing noise gain derived from the baseline matrix predicts which: the worst bucket holds only 38 of the 156 trial-configs but contains 20 of the 24 trials that degraded past 2 degrees, with mean change +2.56 there against +0.31 and +0.39 elsewhere. Each triangle is worst along the diagonal that does not pass through the microphone it dropped, and predicted bad angles matched observed ones.

Geometry explains it. Condition number goes from **1.070** (4 mics, 6 pairs) to **1.740** (any 3 mics, 3 pairs, all four triangles identical by symmetry). Spare equations over the 2 unknowns drop from 4 to 1, and independent triangles for the residual check from 4 to 1.

The savings do not justify it. Dropping a microphone **in the localizer only** saves 36 bytes of flash and 32 bytes of RAM, essentially nothing, because the cost sits in the capture and FFT buffers and neither scales with microphone count. A genuine three microphone node, with the DFSDM channel removed in CubeMX, would save 40,192 bytes of RAM. Compute does scale: pairs go 6 to 3, halving the dominant stage.

**Recommendation: keep the fourth microphone.** A node accurate in six directions and unreliable in two is worse than its mean error suggests, and with one spare equation there is nothing left to outvote a reflection-corrupted pair. It costs one DFSDM filter on a chip that already has four.

### 7.2 Near field: a correction to an earlier belief

The far field assumption has a textbook bound, `2*D^2/lambda`, which for this 13.549 cm aperture at 8 kHz gives **0.856 m**. Anything closer was assumed suspect.

That bound is correct but very conservative for this layout, because of symmetry. This array is **centrosymmetric**: mic0 is opposite mic3 through the centre, mic1 opposite mic2. The leading wavefront curvature term is identical at a microphone and at its opposite corner, so it **cancels** when least squares projects the delays onto the baselines. Bearing error from curvature therefore falls as **1/r^2**, not 1/r: worst case `0.0345/r^2` degrees, which is **0.222 degrees at 40 cm** and 0.016 at 1.5 m. Proved by counterexample, moving mic3 to break the symmetry restores 1/r and multiplies the 40 cm error by 8. **This does not generalise** to arrays without that symmetry. The practical consequence is that placement error dominates curvature at every usable range: for 5 cm of hand placement error the two cross at 2.3 cm.

This **corrects an earlier belief**. The 315 degree angle was once thought poor because of near field effects plus placement error. It was placement alone: curvature at 40 cm and 315 degrees is 0.027 degrees against the 2.12 and 6.38 degrees observed, a factor of 29. A useful diagnostic settled it independently. Every pair has a null direction where its delay should read zero (pairs 0-1 and 2-3 at 90/270, pairs 0-2 and 1-3 at 0/180, pair 1-2 at 316.94, pair 0-3 at 136.94), so clapping near a null tests the setup before any analysis runs. Pair 1-2 nulls at 316.94 degrees, and using its delay alone to locate each clap put the two bad trials at 316.81 and 322.84 degrees, matching what the array reported to within 1.5 degrees. The source was not where it was assumed to be. Re-run further out, 315 degrees scores -1.41 degrees mean, in line with every other angle. The triangle residual could never have caught this, because exact spherical delays satisfy the triangle identity exactly, so the residual is structurally blind to curvature.

## 8. What is not done

The single node pipeline works end to end and is validated on hardware. The project is **not** finished, and these limits are real.

- **One room, one sitting.** Every number in section 6 is from a single session in one room. Nothing tests whether 1.11 degrees survives a different environment, reverberation time, or noise floor. This is the most important next measurement.
- **Accuracy is bounded by hand-placed floor marks, not by the array.** Improving the headline number needs better ground truth before it needs anything on the board.
- **The array is planar, so it gives bearing in the plane only.** A source above the plane is indistinguishable from its mirror below. Elevation needs a non-planar layout such as a tetrahedron. Cheap to accept now, expensive to undo later, so it deserves an explicit decision.
- **Single node, so bearing only, not position.** Crossing bearings from two nodes gives a position fix, but that needs inter-node time synchronization, which is its own hard problem and is not started.
- **Claps only.** A clap is the easiest possible source, broadband and impulsive, which is exactly what PHAT weighting and the trigger and window design assume. Speech or machinery would need rethinking at the trigger, the window, and probably the weighting.
- **Only the Debug build has been profiled.** The 398 ms total is measured at -O0. The Release build at -O2 has not been timed, so how much faster it runs is unknown.

### Suggested order of work

1. Nothing is blocking. The remaining work is scope, not repair.
2. Repeat the sweep in a second room, or at a second distance, to test whether 1.11 degrees is a property of the array or of that room. 1.5 m or more is recommended for future sessions, purely for placement accuracy.
3. Improve ground truth if the headline number matters.
4. Profile the Release build at -O2, to find out what the pipeline actually costs when it is not compiled for debugging.
5. Open questions for Ben: multi-node with time synchronization, continuous rather than triggered operation, or harder sources than claps.
