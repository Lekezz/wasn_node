# WASN Node: 4-mic acoustic localization on STM32L552

Summer research project (UVA). Wireless acoustic sensor node: NUCLEO-L552ZE-Q
plus four MP34DT01-M PDM mics, targeting TDOA source localization (GCC-PHAT).
Supervisor: Ben. Owner: Leke (undergrad EE). Reference design: SpeechCompass
(CHI 2025), same MCU family and mics.

## Ground rules for Claude Code

- NEVER edit outside USER CODE BEGIN/END fences in CubeMX-generated files
  (main.c, stm32l5xx_hal_msp.c, stm32l5xx_it.c). Regeneration wipes
  everything else. Peripheral config changes go through CubeMX (the .ioc),
  not hand edits to generated init code.
- Never touch mic_test/Drivers/ (HAL library) or Debug/ (build output).
- Propose a plan before multi-file changes. Small, reviewable diffs.
- Commit before and after every CubeMX regeneration so git diff exposes
  what the generator changed. It has silently reverted settings twice
  (DMA mode Normal, DMA width Byte).
- Explanations should match an undergrad-built project: plain language,
  no em dashes in written documents.

## Hardware truth table (verified working unless noted)

- Clock: MSI 4 MHz x PLLN 48 / PLLR 2 = 96 MHz HCLK. Flash latency 4.
- Mic clock: DFSDM CKOUT on PF10, divider 40 -> 2.4 MHz (morpho CN12).
- Audio: sinc3, Fosr 150, Iosr 1 -> 16 kHz, right bit shift 7, offset 0.
  In code, each 32-bit result >> 8 gives int16 PCM.
- DFSDM1 on this chip: 4 channels (0-3), 4 filters (0-3). No channel 4.
- Pin redirection: channel y may read the pin of channel y+1 (ch3 wraps
  to ch0's pin, verified available in CubeMX).
- Mic map (SEL=GND samples on rising edge, verified empirically):
  mic0: PE7 (DATIN2), ch2, rising, SEL=GND, filter0  [WORKING]
  mic1: PE7 shared, ch1 redirected from ch2, falling, SEL=3V3, filter1
  mic2: PB1 (DATIN0), ch0, rising, SEL=GND, filter2
  mic3: PB1 shared, ch3 redirected from ch0, falling, SEL=3V3, filter3
- Per-mic wiring (MP34DT01-M has VDD, GND, CLK, DOUT, SEL):
  CLK  -> PF10 on every mic (one clock net fanned out to all four)
  DOUT -> PE7 for mics 0 and 1; PB1 for mics 2 and 3
  SEL  -> GND for mics 0 and 2; 3V3 for mics 1 and 3
  VDD  -> 3V3, GND -> GND, 100 nF decoupling close to each VDD pin.
  DOUT is a shared half-duplex bus: the SEL=GND mic drives it while the
  clock is high, the SEL=3V3 mic while it is low, so two mics on one wire
  never collide. Keep the shared DOUT stubs short.
- PB12 is not routed to any connector on this board. PC7 carries the green
  LED. Avoid both for data.
- Filters 1-3 must use sync trigger (start armed, all begin when filter0
  starts). Start order in code: filters 1,2,3 first, filter 0 LAST.
- All DMA: Circular mode, Word width both sides. Check after every regen.
- UART dump via BSP handle hcom_uart[COM1] at 115200. HAL_UART_Transmit
  size arg is uint16_t: chunk anything over 65535 bytes.
- Serial protocol: magic bytes + 4-byte little-endian payload length,
  then raw int16 samples. Single mic used "WAV0", four-mic uses "WAV4"
  with per-channel length, channels sent sequentially in mic order.
- RAM budget: 256 KB total. Four channels at 16 kHz int16 = 128 KB/s.
  RECORD_SECS = 1 for the 4-mic build.
- WARMUP_SAMPLES = 4000 (0.25 s) is discarded before storing starts, so
  the stored second is past mic turn-on and filter settling. At RECORD_SECS
  1 there is no room to trim that offline. Warm-up is now a single global
  counter (not per-mic): the four channels are drained in lockstep, so one
  counter keeps them identical and channel alignment is untouched.
- Capture is CLAP-TRIGGERED, so you no longer time the clap. Button press
  arms the array (green LED); it discards the warm-up, then LISTENS
  indefinitely; the first frame with any sample past TRIGGER_LEVEL (1000,
  int16 domain after >>8) becomes sample 0 of the stored second. Measured
  room noise is RMS 10 to 18 per mic (peaks 100 to 200), so 1000 keeps 5 to
  10x headroom. It was 2500 until 2026-07-27: that was sized when the array
  sat 65 cm from a wall and claps peaked near 15000, but with the wall
  reflection gone the same clap peaks near 4400 and 2500 was too close to
  the signal. A trigger set too high shows up as a green LED that never goes
  out and a capture script that times out with no other symptom. Green
  LED covers both listening and storing, so there is no visual cue for the
  exact trigger instant. The four channels are handled as one synchronized
  frame (act only when all four DMA flags of a phase are up, treat all four
  identically), so the clap can never start one channel a frame ahead of
  another. Alignment, which GCC-PHAT depends on, is exact.
- Capture logic lives in mic_test/Core/Src/capture.c + Core/Inc/capture.h,
  NOT in main.c. These are user files CubeMX does not own, so regeneration
  cannot touch them. main.c only calls Capture_Arm() on button press and
  Capture_Poll() every loop pass, both inside USER CODE fences. The DFSDM
  DMA callbacks live in capture.c and override the HAL weak defaults from
  there. capture.c owns the buffers and the config #defines (SAMPLE_RATE,
  RECORD_SECS, NUM_MICS, DMA_BUF_LEN, WARMUP_SAMPLES, TRIGGER_LEVEL).

## Array geometry

Geometry lives in mic_sims_files/array_geometry.py, NOT hardcoded in the
analysis scripts. Changing layout means editing ACTIVE there. Layouts are
expected to change: treat any specific dimension below as current, not
permanent.

Build surface as of 2026-07-22: TWO full-size breadboards glued together.
Usable area is about 16 cm along the long axis (63 columns) by about
9.25 cm across (10 rows plus rails, both boards).

Current ACTIVE layout: 9.25x9.9-measured, the BUILT array, 9.25 cm wide
x 9.9 cm tall, measured with calipers (measured=True). mic0 top-left,
mic1 top-right, mic2 bottom-left, mic3 bottom-right, +x right, +y up.
Condition number 1.07, no blind directions, sim mean error about 0.8 deg.
Edit BUILT_WIDTH_X / BUILT_HEIGHT_Y in array_geometry.py if re-measured.
Registry also holds nominal 9.25x10/12/16 and the superseded 2.8x10.

The mic row order in array_geometry.py MUST match the physical wiring:
the mic placed top-left is wired as channel 0 (PE7, SEL=GND). The firmware
always emits channels in order mic0..mic3, so a mislabelled corner
reflects the bearing even when every delay is right.

- Count holes along the LONG axis only: the 0.1 inch (2.54 mm) column
  pitch is exact and uninterrupted, so 10 cm is 39-40 pitches. Do NOT
  count across the WIDTH. The centre channel of each board, the power
  rails, and the glue seam all break the grid there, so width must be
  measured.
- Final numbers must come from calipers on the mic PORTS, not header
  pins: the port is offset from the pins on a breakout board. Put the
  measured numbers in array_geometry.py and set measured=True for that
  layout. 1 mm of error is about 0.047 samples, well under a degree.
- Non-collinear is the property that matters most, more than exact
  dimensions. A straight line cannot resolve front from back (sources
  mirrored across the mic line give identical delays) and it breaks
  estimate_direction() outright: parallel baselines make the least
  squares matrix rank 1, the across-axis component of u comes back ~0,
  and the angle collapses to 0 or 180 regardless of truth. array_geometry
  .describe() reports rank; localize_capture.py hard-fails on rank 1.
- Condition number is the blind-direction test. Near 1 means accuracy is
  uniform in all directions. Above about 2 means narrow bearings where
  error blows up: the superseded 2.8x10 single-board rectangle had four
  such cones roughly 30 deg off the long axis, reaching 8 deg error.
  localize_capture.py derives POOR_CONES from the condition number, so
  this stays correct automatically when the layout changes.
- localization_sim.py keeps its own 10 cm square MIC_POS and must NOT be
  repointed at the active layout. It is the validated reference the
  CMSIS-DSP port gets compared against. compare_geometries.py and
  localize_capture.py swap geometry in temporarily and restore it.
- Spatial aliasing bound: at FS 16 kHz, Nyquist 8 kHz gives a half
  wavelength of about 2.1 cm. Every layout here is well past that.
  Broadband claps plus the max_tau search window make GCC-PHAT tolerant
  of it in practice, but the simulation does not model reverberation, so
  wider apertures look better in sim than they may behave in a real room.
  This is the reason to build 10 cm first and try 16 cm after.
- The in-line bring-up fixture is RETIRED. It proved channel sync and
  could not localize (aperture under 3 samples). Its capture and results
  are archived in mic_sims_files/captures/2026-07-22-inline-clap/.

## Repo layout

- mic_test/  STM32CubeIDE project (config in mic_test.ioc)
- mic_test/Core/Src/capture.c + Core/Inc/capture.h  clap-triggered 4-mic
  capture: buffers, trigger/warm-up/frame state machine, UART "WAV4" dump,
  DFSDM DMA callbacks. User files, regeneration-safe. main.c just calls
  Capture_Arm() and Capture_Poll().
- mic_sims_files/catch_audio.py   single-mic serial capture -> WAV ("WAV0")
- mic_sims_files/catch_audio4.py  4-channel capture -> mic0..3.wav + capture.npy
  (port defaults to COM4, override with argv: python catch_audio4.py COM7)
- mic_sims_files/check_sync.py    bring-up check on capture.npy: per-channel
  health, clap onset, GCC-PHAT lag of each channel vs mic0. Geometry free
  on purpose; imports gcc_phat from localization_sim.py so the bring-up
  test and the reference implementation cannot drift apart.
- mic_sims_files/array_geometry.py  named array layouts + ACTIVE selection,
  measured flags, and describe() for rank/condition/aperture. Single source
  of truth for geometry; edit ACTIVE to try a different layout.
- mic_sims_files/compare_geometries.py  scores every registered layout
  through the reference estimator, plus a blind-direction check on ACTIVE.
- mic_sims_files/localize_capture.py  real capture -> bearing. Milestone 5
  deliverable. Hard-fails on a collinear array, warns on high condition
  number, flags pair delays exceeding physics, warns while the active
  layout is unmeasured. Validated on synthetic sources: mean 0.99 deg.
- mic_sims_files/localization_sim.py  GCC-PHAT reference implementation,
  verified (delay bias < 0.001 samples, angle error < 0.1 deg in
  simulation, for the square geometry). The embedded port must match this
  file's outputs on identical input.

## Current status and next steps

See HANDOFF.md for full history and milestone details.
Single-mic record/dump works end to end (tag v0.1-single-mic). The CubeMX
4-mic config and the 4-mic user code are both DONE and committed. All four
mics are now wired on the temporary in-line fixture, but the 4-mic
firmware has still NEVER been run on hardware. Next: flash, first 4-mic
capture (catch_audio4.py then check_sync.py), clap sync check, build the
real spaced array, set MIC_POS, offline GCC-PHAT validation from known
angles, CMSIS-DSP embedded port.
