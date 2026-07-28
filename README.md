# WASN Node: 4-mic acoustic source localization on an STM32L552

Firmware and analysis tooling for a wireless acoustic sensor network node built
on the NUCLEO-L552ZE-Q with four MP34DT01-M PDM MEMS microphones. Summer
research project, University of Virginia. The node records a clap on four
synchronized channels and estimates the direction it came from using TDOA with
GCC-PHAT, both offline in Python and on the board itself with CMSIS-DSP.

**This project is not finished.** What is described below works and has been
measured, but the validation set is thin (two angles), the on-board float
output has not been confirmed since the last firmware fix, and nothing has been
made wireless yet. See "What is not done" at the bottom for the honest list.

## What works today

| Stage | Status | Evidence |
|-------|--------|----------|
| Single mic record and dump | Working | Playable WAV over serial, tag `v0.1-single-mic` |
| Four mic simultaneous capture | Working | Sync proven by clap test 22 July |
| Channel synchronization | Working | Delays linear in mic position, residual 0.131 samples |
| Clap-triggered capture | Working | Board waits for the clap, so it no longer has to be timed |
| Spaced array built and measured | Working | 9.25 x 9.9 cm, calipered port to port |
| Offline localization from real claps | Working | +0.58 deg error at 0 deg, 2.1 m from the nearest wall |
| On-board localization (CMSIS-DSP) | Runs, partly validated | Onset and analysis window match Python exactly; delays not yet confirmed |

### Measured result

One clap at a known 0 degrees, array 2.1 m from the nearest wall:

| Quantity | Value |
|----------|-------|
| Estimated bearing | 0.58 deg |
| Error against truth | +0.58 deg |
| Worst triangle residual | 0.119 samples |

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
  catch_audio4.py                4-channel serial capture -> wav + npy + board report
  check_sync.py                  per-channel health and channel alignment
  localize_capture.py            one real capture -> bearing
  compare_board.py               board's answer vs Python, on identical samples
  compare_geometries.py          scores every registered layout
  plot_validation.py             estimated vs true bearing plot
  captures/<session>/angle<NNN>/ recorded trials, grouped by room setup then angle
docs/
  CMSIS_DSP_SETUP.md             how CMSIS-DSP was vendored and why not via CubeMX
  supervisor-update-2026-07-22.md
```

## Usage

Recording a clap:

1. Build and flash `mic_test` from STM32CubeIDE.
2. `python catch_audio4.py COM4 --tag angle000 --trials 5`, started **before**
   the button press. Only one process can hold the COM port, so close any
   serial terminal first.
3. Press the blue user button. Green LED means armed and listening. Clap once,
   sharply, at least 1 m away and at array height. Timing does not matter, the
   board waits.
4. Blue LED means it is dumping, about 11 s per trial at 115200 baud.

Analysis:

```
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

- **The on-board float path is unverified.** The board's first hardware run
  printed every float as blank, because the project links `--specs=nano.specs`
  and its `printf` drops floating point support. That is fixed in firmware by
  formatting floats with integer arithmetic, but the fix has not been flashed
  yet, so no bearing has ever actually printed from the board. Until it does,
  `compare_board.py` reports every trial as skipped.
- **The validation set is two angles.** Ground truth exists at 0 and 315
  degrees only, three trials total. The deliverable plot needs a full sweep,
  and 315 degrees was noticeably worse than 0 in both trials (+2.12 and +6.38
  deg) for reasons not yet understood.
- **No wireless, and only one node.** The "wireless sensor network" part of the
  title is the eventual goal, not something built. A single node estimates a
  bearing; multiple nodes cross-bearing to a position is future work.
- **No live or continuous operation.** Capture is one second, triggered by one
  clap, analysed once. Not a stream.
- **Elevation is out of reach** with a planar array, as noted above.

## Hardware notes

- Board: NUCLEO-L552ZE-Q, TrustZone disabled.
- Mics: four Adafruit MP34DT01-M breakouts at 3.3 V.
- One clock net (PF10) fans out to all four microphones. Mics 0 and 1 share
  data pin PE7, mics 2 and 3 share PB1. SEL is tied to GND on mics 0 and 2 and
  to 3V3 on mics 1 and 3, which is what separates the two mics sharing a wire.
- 100 nF decoupling close to each mic VDD, and keep the shared data stubs short.
