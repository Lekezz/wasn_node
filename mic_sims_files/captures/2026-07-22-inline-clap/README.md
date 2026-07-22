# Reference capture: first clean 4-mic run

Recorded 2026-07-22. This is the capture that proved the four-mic chain
works end to end, kept as a regression reference. Capture outputs are
normally gitignored because they regenerate every run; this one is
committed on purpose under a name that does not match those patterns.

File: inline_clap_4mic.npy, int16, shape (4, 16000), 16 kHz, 1 second.
Same layout localization_sim.py expects, so it feeds gcc_phat directly.

    import numpy as np
    cap = np.load("inline_clap_4mic.npy")

To re-run the bring-up analysis against it:

    python check_sync.py captures/2026-07-22-inline-clap/inline_clap_4mic.npy

## Conditions

- Temporary in-line bring-up fixture, four mics in a straight line on the
  small breadboard, roughly 2 cm pitch, aperture about 6 cm. NOT the final
  array, and it cannot localize. See HANDOFF.md.
- One sharp clap, off toward the mic3 end of the line.
- Firmware as of commit 484aff7 (WARMUP_SAMPLES 4000, 0.25 s discarded per
  mic before storing).

## What it showed

Filter sync PASS, worst channel offset 1.80 samples against a roughly 3
sample physical aperture.

The result worth keeping it for is that the delays are physically
consistent, not just inside tolerance. Lags against mic0 were 0.000,
-0.481, -1.354, -1.801 samples: monotonic across the line and linear in
mic position to a maximum residual of 0.131 samples (about 8 us).

That linearity is the real proof. Four mics in a line hearing one distant
clap must produce delays that increase linearly with position. Nothing in
the firmware forces that. A sync bug, a swapped channel, or a wrong clock
edge would break either the ordering or the spacing. Getting a straight
line means the DFSDM sync start, the DMA drain, the filter-to-mic map, and
the serial protocol are all correct at once.

End to end is 1.80 samples, which is 3.9 cm of path difference across a
6 cm aperture, so a source about 50 degrees off the array axis. Sane, and
correctly inside the physical bound.

Other numbers: transient-to-noise 327x, peak 26803 of 32767 (82 percent,
no clipping but close), pre-clap DC flat at 35 to 117 across all blocks
before the transient, pre-clap rms spread 1.49x across channels.

The flat pre-clap DC confirms the warm-up discard works. The large DC that
appears after the clap is the front end recovering from the transient and
is normal; there is no DC blocking in the sinc path.

## Notes for whoever reads this later

- Room-noise correlation between channels is 0.60 to 0.83, which is
  expected here and not a duplicated-stream bug. At 2 cm spacing the mics
  are well inside a wavelength at low frequency so they genuinely hear
  correlated noise. The tells that these are four real streams: no two
  channels are bit-identical, correlation is highest between adjacent mics
  and falls off monotonically with distance, and no pair is near 1.00.
  The "should be near zero" expectation only holds for widely spaced mics.
- An earlier capture the same day gave lags of 0, -0.017, -0.056, -2.066,
  which is not physically consistent. That clap was weak
  (transient-to-noise 14.7). Clap strength was the limiting factor, not
  the array. Clap hard for any capture you intend to trust.
