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
- WARMUP_SAMPLES = 4000 (0.25 s) is discarded per mic before storing
  starts, so the stored second is past mic turn-on and filter settling.
  At RECORD_SECS 1 there is no room to trim that offline. Every mic drops
  the same count from its own stream, so channel alignment is untouched.
  Practical effect: the useful window is about 0.25 s to 1.25 s after the
  green LED, so clap about half a second after pressing the button.

## Array geometry

Current bench setup is a TEMPORARY in-line fixture: four mics in a
straight line, packed tight on the small breadboard, for four-channel
bring-up only. A larger breadboard is coming; final geometry is TBD.
localization_sim.py still holds the default 10 cm square MIC_POS.

- Leave MIC_POS and estimate_direction() alone until the real array
  exists. The bring-up fixture only needs the clap sync check, which does
  not depend on geometry.
- The fixture cannot localize. At ~2 cm pitch the whole aperture spans
  under about 3 samples at 16 kHz, so there is no angular resolution to
  extract. That same tightness makes it a good sync test: all four clap
  onsets should coincide, so any channel off by several samples is a
  filter sync bug rather than geometry.
- When the real array is built, set MIC_POS from measured port-to-port
  positions before analyzing any capture.
- Prefer a non-collinear final layout. A straight line cannot resolve
  front from back (sources mirrored across the mic line give identical
  delays, so bearing is only recoverable in a half plane), and it breaks
  estimate_direction() as written: parallel baselines make the least
  squares matrix rank 1, the across-axis component of u comes back ~0,
  and the reported angle collapses to 0 or 180 regardless of truth. A
  linear array would need the reduced 1D solve (direction cosine, then
  arccos).
- For a linear layout, angular sensitivity is best broadside (source
  perpendicular to the mic line) and worst at endfire, since the delay
  derivative goes as sin of the angle off axis. Aim test claps broadside.
- Spatial aliasing bound: at FS 16 kHz, Nyquist 8 kHz gives a half
  wavelength of about 2.1 cm. Wider spacing than that can produce
  ambiguous correlation peaks at high frequency. Broadband claps plus
  the max_tau search window make GCC-PHAT tolerant well past this in
  practice, but wide spacing trades aliasing risk for resolution.

## Repo layout

- mic_test/  STM32CubeIDE project (config in mic_test.ioc)
- mic_sims_files/catch_audio.py   single-mic serial capture -> WAV ("WAV0")
- mic_sims_files/catch_audio4.py  4-channel capture -> mic0..3.wav + capture.npy
  (port defaults to COM4, override with argv: python catch_audio4.py COM7)
- mic_sims_files/check_sync.py    bring-up check on capture.npy: per-channel
  health, clap onset, GCC-PHAT lag of each channel vs mic0. Geometry free
  on purpose; imports gcc_phat from localization_sim.py so the bring-up
  test and the reference implementation cannot drift apart.
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
