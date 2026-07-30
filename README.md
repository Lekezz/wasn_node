# WASN Node: 4-mic acoustic source localization on an STM32L552

Firmware and analysis tooling for a wireless acoustic sensor network node built
on the NUCLEO-L552ZE-Q with four MP34DT01-M PDM MEMS microphones. Summer
research project, University of Virginia. The node records a clap on four
synchronized channels and estimates the direction it came from using TDOA with
GCC-PHAT, both offline in Python and on the board itself with CMSIS-DSP.

**This project is not finished**, but the single-node pipeline now works end to
end and is validated: a full 8 angle sweep localizes real claps to a mean error
of 1.11 degrees, and the on-board CMSIS-DSP port agrees with the Python
reference on all 44 captures compared. What remains is that nothing has been
made wireless, there is only one node, and only claps have been tested. See
"What is not done" at the bottom.

## What works today

| Stage | Status | Evidence |
|-------|--------|----------|
| Single mic record and dump | Working | Playable WAV over serial, tag `v0.1-single-mic` |
| Four mic simultaneous capture | Working | Sync proven by clap test 22 July |
| Channel synchronization | Working | Delays linear in mic position, residual 0.131 samples |
| Clap-triggered capture | Working | Board waits for the clap, so it no longer has to be timed |
| Spaced array built and measured | Working | 9.25 x 9.9 cm, calipered port to port |
| Localization from real claps | Working | 8 angles, 39 claps, mean error 1.11 deg, worst 4.04 deg |
| On-board localization (CMSIS-DSP) | Validated | 44 captures compared, all six delays match Python to 0.000 samples, bearings to 0.004 deg |
| Guided capture sessions | Working | One command per sweep, quality check and retake at the bench, resumable |

### Measured result

Full sweep, 2026-07-29. Eight angles at 45 degree spacing, five claps each,
source 1.5 m out, array 2.1 m from the nearest wall:

| True angle | Trials | Mean error | Spread (std) | Worst |
|-----------:|-------:|-----------:|-------------:|------:|
| 0 | 5 | -1.42 deg | 1.17 | 3.31 |
| 45 | 5 | -1.07 deg | 1.06 | 2.20 |
| 90 | 5 | -0.17 deg | 0.57 | 0.86 |
| 135 | 5 | +0.17 deg | 0.65 | 0.82 |
| 180 | 5 | -1.43 deg | 0.90 | 2.80 |
| 225 | 4 | -1.32 deg | 1.82 | 3.87 |
| 270 | 5 | -0.40 deg | 0.38 | 0.99 |
| 315 | 5 | -1.41 deg | 1.41 | 4.04 |
| **all** | **39** | **1.11 deg mean \|error\|** | 0.99 | **4.04** |

For scale, the same estimator on synthetic claps through the same geometry, with
no reverberation and exact geometry handed to it, gives mean 0.99 deg and worst
2.41 deg. The real array is performing at close to the simulation's own accuracy
floor, which is better than expected: reverberation was predicted to cost
several degrees.

Note the pattern in the per-angle means. Within any one angle the spread is
small (0.38 to 1.82 deg), but the mean shifts by angle, from -1.43 to +0.17.
That shape points at ground truth rather than the array: each angle's floor mark
was placed by hand and carries its own fixed offset, which a whole angle then
inherits. The array's repeatability is visibly better than its accuracy against
those marks, so better protractor work would likely improve the headline number.

The board computes all of this itself, in float32 with CMSIS-DSP, and agrees
with the float64 numpy reference on identical samples across all 44 captures
compared: every pair delay to 0.000 samples and every bearing to within 0.004
degrees.

For comparison, the same array in the same room but 65 cm from a wall gave
-3.40 deg with a residual of 0.875 samples. The wall reflection was corrupting
one microphone pair, and moving away from it was the whole fix. That is the
single most useful practical lesson from the project so far.

## Signal chain

```
4x PDM mic  ->  DFSDM (sinc3, Fosr 150)  ->  DMA (circular, ping-pong)
            ->  RAM  ->  clap trigger  ->  1 s of 4-channel int16
            ->  on-board GCC-PHAT + least squares  ->  bearing over UART
                and raw samples over UART -> Python for offline checking
```

- 96 MHz system clock, 2.4 MHz microphone clock, 16 kHz 16-bit PCM per channel.
- Two microphones share each data line. The SEL pin puts one on the rising
  clock edge and the other on the falling edge, so four mics need only two
  data pins. DFSDM on this part has four channels and four filters, which is
  exactly enough and no more.
- The four filters are started in sync mode (followers first, trigger filter
  last) so every channel begins on the same clock. Without this there is an
  unknown per-channel offset and no timing based localization is possible.

## Array geometry

The built array is a 9.25 x 9.9 cm near-rectangle on two glued breadboards,
measured port to port with calipers. Aperture 13.5 cm, which is 6.32 samples
at 16 kHz. Condition number 1.07, meaning accuracy is close to uniform in every
direction and the array has no blind cones.

Geometry lives in `mic_sims_files/array_geometry.py` as a registry of named
layouts with one marked active. It is not hardcoded in the analysis scripts,
because during the build the layout changed twice for purely physical reasons
(how many breadboards were available). Trying a different array is a one line
change there, and `compare_geometries.py` scores every registered layout
automatically.

The array is planar, so it gives bearing in the plane only. A source above the
plane cannot be told from its mirror below. Elevation would need a non-planar
layout such as a tetrahedron.

## Repo layout

```
mic_test/                        STM32CubeIDE project (config in mic_test.ioc)
  Core/Src/capture.c             clap-triggered 4-mic capture, DMA drain, UART dump
  Core/Src/localize.c            on-board localizer: find_clap, fusion, report
  Core/Src/gcc_phat.c            GCC-PHAT delay estimation
  Core/Src/fft_backend.c         arm_rfft_fast_f32 wrapper
  Core/Src/array_geometry.c      geometry, mirrors the Python registry
  Middlewares/CMSIS_DSP/         vendored FFT, trimmed to the tables actually used
mic_sims_files/
  localization_sim.py            reference implementation, the thing everything is checked against
  array_geometry.py              layout registry and active selection
  capture_paths.py               where captures live on disk
  run_session.py                 guided sweep: one command for a whole session
  trial_quality.py               is this capture good enough to keep
  wav4_stream.py                 the WAV4 serial protocol, shared by the capture tools
  replay_source.py               fake serial and fault injection, so the path runs with no board
  catch_audio4.py                4-channel serial capture -> wav + npy + board report
  check_sync.py                  per-channel health and channel alignment
  localize_capture.py            one real capture -> bearing
  compare_board.py               board's answer vs Python, on identical samples
  compare_geometries.py          scores every registered layout
  plot_validation.py             estimated vs true bearing plot
  captures/<session>/angle<NNN>/ recorded trials, grouped by room setup then angle
docs/
  summer-writeup-2026.md         full project writeup: method, results, what is unfinished
  steps-forward.md               the ordered path from here to a validated result
  bench-checklist.md             one page to print and keep at the bench
```

## Usage

Recording a session. One command walks the whole sweep, prompts you between
angles, checks each trial at the bench and offers a retake, and resumes if you
stop partway:

```
python run_session.py COM4 --session 2026-07-29-sweep \
    --angles 0,45,90,135,180,225,270,315 --trials 5 \
    --notes "wall 2.1 m, clap 1.5 m"
```

Per trial: press Enter when the source is placed, press the blue user button,
then clap once, sharply. Green LED means armed and listening, and timing does
not matter because the board waits for the clap. Blue LED means it is dumping,
about 11 s per trial at 115200 baud.

Two things that matter more than they look:

- **Start the script before pressing the button.** Only one process can hold
  the COM port, so close any serial terminal first.
- **Clap from 1.5 m or more, from a marked spot.** Closer than about 0.9 m puts
  the top of a clap's band inside the near field, where the plane-wave model the
  estimator assumes breaks down. Distance also cuts the angular error from
  imprecise hand placement, which goes as 1/distance: 5 cm of it is 7 degrees at
  40 cm but under 2 degrees at 1.5 m.

`python catch_audio4.py COM4 --tag angle000 --trials 5` still records a single
angle by hand if you want it.

Analysis:

```
python run_session.py --summary --session NAME   # progress, opens no COM port
python trial_quality.py --true-angle 0           # re-check the newest capture
python check_sync.py          # are the four channels healthy and aligned
python localize_capture.py --true-angle 0
python compare_board.py       # does the firmware agree with the reference
python plot_validation.py     # estimated vs true bearing, all sessions
```

`localization_sim.py` also runs standalone and prints estimated versus true
angles for a simulated sweep, with no hardware involved.

## Validation approach

The Python implementation in `localization_sim.py` is the reference. It was
verified in simulation first: delay bias under 0.001 samples, angle error under
0.1 degrees, degrading gracefully to about 0.4 degrees at 0 dB SNR. Everything
else is checked against it rather than against intuition.

- `check_sync.py` imports `gcc_phat` from the reference rather than
  reimplementing it, so the bring-up test and the reference cannot drift apart.
- `compare_board.py` reads the report the board prints after each capture and
  compares it against the reference run on the same stored samples, field by
  field. Delays must agree within 0.05 samples and the bearing within 0.5
  degrees. This is the acceptance test for the embedded port.

Real world accuracy is worse than simulation and is expected to be. The
simulation has no reverberation and hands the estimator the exact geometry, so
its roughly 1 degree is a clean room ceiling, not a prediction.

## What is not done

- **Accuracy is limited by the ground truth, not measured against a better
  reference.** The angles come from a protractor and floor marks placed by hand,
  and the per-angle bias pattern above suggests those marks carry roughly a
  degree of error themselves. The array is probably better than 1.11 degrees; we
  cannot currently prove it.
- **One room, one session, one source type.** All 39 claps were recorded in the
  same room at the same 1.5 m distance in a single sitting. Nothing tests a
  different room, a different distance, or a source that is not a clap.
- **The triangle residual is a weak predictor of error.** Trials with residuals
  up to 2.5 samples still produced bearings within a degree, while the one
  catastrophic trial (101 degrees off, the trigger caught something other than
  the clap) had a clean 0.070 residual. It reliably flags a corrupted capture
  but should not be read as an error estimate, and the 0.3 sample threshold the
  bench check uses is stricter than the data justifies.
- **No wireless, and only one node.** The "wireless sensor network" part of the
  title is the eventual goal, not something built. A single node estimates a
  bearing; multiple nodes cross-bearing to a position is future work.
- **No live or continuous operation.** Capture is one second, triggered by one
  clap, analysed once. Not a stream.
- **Elevation is out of reach** with a planar array, as noted above.

## Hardware notes

- Board: NUCLEO-L552ZE-Q, TrustZone disabled.
- Mics: four MP34DT01-M breakouts at 3.3 V.
- One clock net (PF10) fans out to all four microphones. Mics 0 and 1 share
  data pin PE7, mics 2 and 3 share PB1. SEL is tied to GND on mics 0 and 2 and
  to 3V3 on mics 1 and 3, which is what separates the two mics sharing a wire.
- Kept the shared data stubs short.
