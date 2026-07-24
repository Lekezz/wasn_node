# HANDOFF: project history and pending work

This file holds the story, the open work, and the debugging history that
explains why things are the way they are. Read together with CLAUDE.md,
which holds the compact always-true facts. Last updated 2026-07-24
(capture made clap-triggered so the clap no longer has to be timed, and
the capture logic moved out of main.c into a regeneration-safe capture.c /
capture.h module). Prior milestone 2026-07-22: four-mic capture proven on
hardware, geometry moved into a registry, active layout 9.25 x 10 cm on
two glued breadboards.

## Where the project stands

Working and proven on hardware:
- Single-mic pipeline end to end: button press records to RAM, dumps over
  ST-LINK VCP, Python saves a playable WAV. Tagged v0.1-single-mic.
- Localization simulation (mic_sims_files/localization_sim.py) verified:
  isolated delay estimator worst error 0.0007 samples, full-sweep angle
  error under 0.1 degrees at 2 m and 20 m, graceful degradation to ~0.4
  deg at 0 dB SNR. Note this was all for the default 10 cm SQUARE
  geometry, which is not the array actually being built (see below).
  It is the reference the firmware port will be validated against.
- GitHub repo with README and .gitignore.

- Four-mic capture, PROVEN ON HARDWARE 2026-07-22. Channel sync verified
  by clap test: delays 0.000, -0.481, -1.354, -1.801 samples, monotonic
  across the in-line fixture and linear in mic position to a max residual
  of 0.131 samples. Reference capture archived in
  mic_sims_files/captures/2026-07-22-inline-clap/.

Working, committed, and now exercised on hardware:
- CubeMX four-mic configuration (channels 0,1,3 added, filters 1-3, three
  new DMA requests), plus commit 9f179e1 fixing channel 3 RightBitShift
  to 0x07.
- The four-mic user code now lives in mic_test/Core/Src/capture.c +
  Core/Inc/capture.h (moved out of main.c 2026-07-24). Sync-order filter
  start, circular DMA drain via a filter->mic map, "WAV4" UART dump.
  RECORD_SECS dropped 4 -> 1 for the RAM budget. As landed in main.c it was
  0 errors, 0 warnings, bss 164040 bytes; the module refactor and the
  clap-trigger change have not been built on hardware yet (see below).
- Capture is now CLAP-TRIGGERED (2026-07-24), so the clap no longer has to
  be timed against a fixed window. Button press arms the array, warm-up is
  discarded, then it listens indefinitely and the first frame past
  TRIGGER_LEVEL becomes sample 0 of the stored second. Wire format ("WAV4")
  is unchanged, so catch_audio4.py and check_sync.py are untouched. NOT yet
  built or run on hardware.
- mic_sims_files/catch_audio4.py as of commit e6058c1. Syncs on "WAV4",
  reads the per-channel length, saves mic0.wav..mic3.wav plus capture.npy
  shaped (4, nsamples) to match what localization_sim.py expects.

- mic_sims_files/check_sync.py, the bring-up analysis for a capture.
  Smoke tested against a synthetic capture with a deliberate
  1-sample-per-channel stagger; it recovered +0.000, +1.000, +2.000,
  +3.000 exactly. Never yet run on real data.

- mic_sims_files/array_geometry.py, compare_geometries.py, and
  localize_capture.py. Geometry registry, layout scoring, and real
  capture to bearing. localize_capture.py validated against synthetic
  sources on the active layout: mean 0.99 deg, worst 1.77 deg. Not yet
  run on a real spaced array, because the array is not built.

Cleared:
- All four mics wired, and the four-mic firmware run and verified. Both
  were blockers.

Not started:
- The spaced array itself, offline localization on real data, CMSIS-DSP
  port.

## The in-line bring-up fixture is RETIRED

It was four mics in a straight line, packed as tight as the parts allow,
on the small breadboard. Its only job was proving all four channels work
and start in sync, and it did that on 2026-07-22. It could never localize:
at roughly 2 cm pitch the whole aperture spans under 3 samples at 16 kHz,
so there is no angular resolution to extract, and any direction estimate
from it is meaningless.

That tightness was exactly what made it a good sync test. True acoustic
delay end to end was under 3 samples, so any channel sitting far off had
to be a filter sync bug rather than geometry. A spread out array would
have confounded the two.

Its capture and full results are archived in
mic_sims_files/captures/2026-07-22-inline-clap/. Geometry for the real
array is covered in the next section.

## Geometry: how it was decided, and why it changed twice

The build surface drove this, and it moved twice in one day. Keeping the
history because it explains why the code is structured the way it is.

1. Original plan: 10 cm square, matching localization_sim.py's validated
   MIC_POS.
2. Then: only ONE full-size breadboard was available. That board is about
   16.5 cm long but only about 2.8 cm across the usable rows, so a 10 cm
   square does not fit. Best available was a 2.8 x 10 cm rectangle.
3. Then: two boards were glued together, giving about 9.25 cm of width.
   A near-square fits again, and that is the current plan.

The lesson that stuck: geometry changes for physical reasons that have
nothing to do with the maths, so it was moved out of the scripts into
mic_sims_files/array_geometry.py. Layouts are named entries in a registry
with an ACTIVE selection and a per-layout measured flag. Adding a layout
gets it scored by compare_geometries.py automatically. More layouts are
expected; nothing below is permanent.

Scores from compare_geometries.py, simulation only (36 angles x 3 trials,
2 m source, 20 dB SNR). No reverberation, no measurement error, and the
estimator is handed the exact geometry, so these RANK layouts rather than
predict real accuracy:

| Layout                | Aperture | Cond | Mean    | p90     | Worst   |
|-----------------------|----------|------|---------|---------|---------|
| 9.25 x 10 cm (ACTIVE) | 13.6 cm  | 1.08 | 1.03deg | 2.09deg | 2.39deg |
| 9.25 x 12 cm          | 15.2 cm  | 1.30 | 0.70deg | 2.01deg | 2.16deg |
| 9.25 x 16 cm          | 18.5 cm  | 1.73 | 0.51deg | 1.10deg | 1.42deg |
| 10 cm square (ref)    | 14.1 cm  | 1.00 | 1.12deg | 2.32deg | 2.43deg |
| 9.0 cm square         | 12.7 cm  | 1.00 | 1.74deg | 2.83deg | 2.95deg |
| 2.8 x 10 cm (1 board) | 10.4 cm  | 3.57 | 1.87deg | 7.87deg | 8.43deg |
| 2.5 cm square         |  3.5 cm  | 1.00 | 6.33deg | 8.60deg | 9.20deg |

Reading the table: mean error alone is misleading. The 2.8 x 10 cm
single-board rectangle has a decent MEAN (1.87 deg) but a terrible p90
(7.87 deg), because its error is concentrated in four narrow cones about
30 deg off the long axis. Condition number predicts this directly, which
is why the code keys off it: near 1 means uniform accuracy, above about 2
means blind directions exist.

Why 9.25 x 10 is ACTIVE rather than the better-scoring 9.25 x 16: every
layout here is well past the spatial aliasing half-wavelength bound
(2.1 cm at 8 kHz), and the simulation does not model reverberation, so
wide apertures look better in sim than they may behave in a real room.
Build the 10 cm version first, confirm it works, then try 12 and 16 cm
since changing is now a one-line edit. Far field holds comfortably either
way: sources at 1 m or more against a 13.6 cm aperture.

Still true and worth keeping in mind: the array is PLANAR, so it gives
bearing in the plane only, and a source above the plane is
indistinguishable from its mirror below. Elevation would need a
non-planar layout such as a tetrahedron. That is the one limitation that
is expensive to undo later, so it is worth raising with Ben.

Build notes:
- Count holes along the LONG axis only. The 0.1 inch (2.54 mm) column
  pitch is exact and uninterrupted, so 10 cm is 39-40 pitches. Do NOT
  count across the width: the centre channel of each board, the power
  rails, and the glue seam break the grid. Measure the width.
- Measure port to port with calipers, not pin to pin. On a breakout board
  the mic port is offset from the header pins. Put measured numbers in
  array_geometry.py and set measured=True for that layout; until then
  localize_capture.py warns that any bearing is provisional.
- Keep all four ports coplanar and facing the same way. Label the mics
  physically 0 to 3.
- The CLK net now fans 2.4 MHz out to four mics over a longer run: put 33
  to 100 ohms in series at the MCU end and run a ground wire alongside the
  clock. Mics 0 and 1 share PE7 while mics 2 and 3 share PB1, so place
  each sharing pair on adjacent corners rather than diagonal ones to keep
  those shared DOUT stubs short.

## Reference: the 4-mic capture module (capture.c / capture.h)

The capture code lives in mic_test/Core/Src/capture.c and
Core/Inc/capture.h. capture.c is the source of truth: if anything here
disagrees with it, capture.c wins. Unlike the old arrangement, this no
longer needs to be reproduced as a restore backup, because capture.c and
capture.h are user files CubeMX does not own, so regeneration cannot wipe
them. main.c only holds two calls inside USER CODE fences: Capture_Arm()
on the button press and Capture_Poll() every loop pass.

What the module does:
- Owns the config #defines (SAMPLE_RATE, RECORD_SECS 1, NUM_MICS 4,
  DMA_BUF_LEN 2048, WARMUP_SAMPLES 4000, TRIGGER_LEVEL 2500), the buffers
  (dma_buf, recording, rec_index), and the flags, all file-private.
- Capture_Arm(): rewinds every mic, sets warm-up, clears the trigger,
  lights the green LED, and sync-starts the filters (slaves 1,2,3 first,
  filter0 LAST so all four release together). Ignored if already recording.
- Capture_Poll(): drains DMA a whole aligned frame at a time (the same half
  of all four channels, which arrive together because the filters are
  sync-started), runs the warm-up / watch / store state machine, and on
  completion stops the DMAs and dumps "WAV4" over UART.
- The two HAL_DFSDM_FilterRegConv*Callback functions live here and override
  the HAL weak defaults; they just raise per-mic half/full flags.

Design notes (kept as rationale):
- Clap trigger: after warm-up, the first frame with any sample past
  TRIGGER_LEVEL (int16 domain, after >>8) latches "triggered" and becomes
  sample 0. This removes the timed-clap window; the array listens as long
  as it takes. Room noise is under 1000, a clap peaks near 15000, so 2500
  has margin. Raise it if noise trips it, lower it if a real clap does not.
- Alignment is preserved by processing the four channels as ONE frame: act
  only when all four DMA flags of a phase are up, and treat all four
  identically. That way the clap can never start one channel a frame ahead
  of another. This is why warm-up is now a single global counter, not
  per-mic: the channels move in lockstep. GCC-PHAT depends on this.
- The warm-up discard exists because two notes contradicted each other:
  trim the first second of settling, but RECORD_SECS is 1 so there is
  nothing to trim. Dropping 0.25 s in firmware before storing resolves it.
- 32000 bytes per channel fits a single HAL_UART_Transmit (uint16_t size
  limit is 65535), so no chunking loop is needed at RECORD_SECS 1. If the
  duration ever grows, reintroduce chunking (this bug bit us once: the size
  arg silently truncated 128000 to 62464).
- capture.c externs the four filter handles and hcom_uart[] from the
  generated code / BSP. If CubeMX ever renames a handle, update the externs
  and filter_to_mic. Before building, still confirm in stm32l5xx_hal_msp.c
  that all four DMA inits say DMA_CIRCULAR and WORD alignment.
- STM32CubeIDE auto-compiles capture.c: the .cproject registers Core as a
  recursive source path, and Core/Inc is already on the include path, so no
  project-config change was needed to add the module.


## Reference: 4-channel capture script

DONE, committed in e6058c1 as mic_sims_files/catch_audio4.py. Syncs on
magic "WAV4", reads the 4-byte little-endian per-channel length, then
reads four sequential channel blocks. Saves mic0.wav..mic3.wav plus
capture.npy, an int16 array shaped (4, nsamples) matching the mic_signals
layout localization_sim.py expects, so a capture feeds gcc_phat with no
reshaping. The single-mic "WAV0" version is still there as catch_audio.py.

## Milestones from here

1. DONE. Mics 1-3 wired on the temporary in-line breadboard.
2. First 4-mic run. The clap-trigger and module refactor have not run on
   hardware yet, so expect to debug the code as much as the wiring.
   Sequence:
     - build and flash in STM32CubeIDE (capture.c is a new file; a clean
       build picks it up automatically)
     - python catch_audio4.py COM4    (start it BEFORE the button press)
     - press the blue button (green LED = armed and listening), then one
       sharp clap 30 to 50 cm away, broadside to the line. Timing no longer
       matters: it waits for the clap, so clap whenever you are ready.
     - blue LED means it is dumping, about 11 s at 115200
     - python check_sync.py
3. Clap sync check. check_sync.py prints per-channel RMS/peak/DC, finds
   the clap from the summed envelope, and reports each channel's GCC-PHAT
   lag against mic0 in samples. Because the mics are packed tight, true
   acoustic delay is under about 3 samples end to end, so a PASS means all
   four land within the 5 sample tolerance. A near-silent channel is
   almost always SEL wiring or a clock edge that does not match SEL on
   that channel. A channel that is alive but tens of samples off is filter
   sync. No offline trimming needed now that the firmware discards the
   warm-up.
4. Build the 9.25 x 10 cm array on the glued breadboard pair (see the
   geometry section below). Count holes along the long axis, measure the
   width. Then measure port-to-port with calipers, put the numbers in
   array_geometry.py, and set measured=True for that layout.
5. Re-run check_sync.py on the spaced array before anything else. The
   wiring is longer now, so confirm channel sync survived it. Expected
   delays are larger than the in-line fixture (aperture is 6.4 samples,
   not 3), so the pass criterion is physical consistency, not near-zero
   offsets: delays should agree with a plausible source position.
6. Offline validation: claps from known angles (protractor + tape measure,
   1 m or more away, source at array height, away from walls), then
   localize_capture.py --true-angle DEG on each capture. The active
   layout has no blind directions, so any bearing is fair game.
   Deliverable: estimated vs true angle plot. Expect several degrees of
   error in the real world; the sim's ~1 deg is the clean-room ceiling.
7. CMSIS-DSP port: reimplement gcc_phat (arm_rfft_fast_f32) and the least
   squares fusion in C. Validate by feeding identical capture.npy frames
   and comparing delays to Python within a fraction of a sample. Budget
   check from earlier analysis: ~10 ms of FFT work per 32 ms frame at
   96 MHz, roughly 3x headroom.

## Debugging history worth remembering

- CubeMX regeneration reverted DMA mode to Normal and later DMA width to
  Byte. Both fatal, both silent. Always diff generated files after regen.
- HAL_UART_Transmit uint16_t size truncation (128000 -> 62464 bytes,
  compiler warning was the only clue). Treat every warning as guilty.
- DFSDM is under Computing in this CubeMX version, not Analog.
- Original plan assumed 8 DFSDM channels; this chip has 4. The channel
  map in CLAUDE.md is the corrected version.
- First second of DFSDM output after start contains filter settling
  artifacts (pop or DC step). Normal; trim in analysis.
- Serial capture script must be started before pressing the button
  (reset_input_buffer eats boot text; script syncs on magic bytes).
- Mic orientation: MEMS mics are omnidirectional; all four flat on one
  plane, ports up, positions measured port-to-port. Direction info comes
  from timing only. Label mics physically 0-3.

## Context for tone and docs

Owner is an undergraduate; written deliverables should read like careful
undergrad work: plain sentences, no em dashes, explanations that show
reasoning rather than polish. Preference for tables in hardware
comparisons and staged step-by-step instructions.
