# Reference capture: first spaced-array clap, with true angle

Recorded 2026-07-23. First clap on the real 9.25 x 9.9 cm array, and the
first capture that produces a meaningful, ground-truthed bearing.
Companion to the retired in-line fixture capture in
../2026-07-22-inline-clap/, which only proved channel sync.

File: square_clap_4mic.npy, int16, shape (4, 16000), 16 kHz, 1 second.

    python check_sync.py       captures/2026-07-23-square-clap/square_clap_4mic.npy
    python localize_capture.py captures/2026-07-23-square-clap/square_clap_4mic.npy --true-angle 90

## Conditions

- Array: 9.25x9.9-measured layout, mic0 top-left, mic1 top-right, mic2
  bottom-left, mic3 bottom-right, measured with a ruler.
- Firmware as of the WARMUP_SAMPLES build (commit 484aff7).
- One clap, TRUE ANGLE 90 degrees (straight off the top edge of the
  array).

## Result

- Estimated bearing 93.3 degrees against a true 90.0, so **error +3.3
  degrees**. This is the first real accuracy number for the project. It
  sits right in the expected real-world band: the simulation's clean-room
  ceiling is about 0.8 degrees, and several degrees of degradation from
  room echo, mic mismatch, and clap position is normal.

## Supporting checks

- All four channels healthy: matched within 1.38x on room noise, no
  clipping, flat pre-clap DC. Transient to noise 149.8.
- Sync survived the longer spaced-array wiring. Bottom pair (mic2, mic3)
  lags the top pair (mic0, mic1) by about 4 samples, which is the real
  9.9 cm aperture, not a fault.
- Plane-wave self-consistency: fitting one arrival direction back through
  all six pair delays gives an RMS residual of 0.368 samples (about 23
  microseconds). Every mic pair is explained to under half a sample,
  which is the signature of a correctly built and correctly mapped array.
  A wiring swap or geometry error would blow this up to several samples.

## Note toward the validation sweep

This is one angle. The deliverable plot needs a spread of true angles,
each saved as its own capture (this one is the only one kept so far,
because catch_audio4.py overwrites capture.npy every run). Copy each
capture aside before the next clap, or the sweep loses all but the last.
The active layout has no blind directions, so any angle is fair game.
