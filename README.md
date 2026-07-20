# WASN Node: Distributed Spatial Audio Sensing

Firmware and tooling for a wireless acoustic sensor network node built on the
NUCLEO-L552ZE-Q with MP34DT01-M PDM MEMS microphones. Summer research project,
University of Virginia. The end goal is TDOA based source localization
(GCC-PHAT) running on a four microphone array per node.

## Current state (v0.1-single-mic)

Single microphone capture pipeline, working end to end:

- Button press records audio into RAM, then dumps it over the ST-LINK
  virtual COM port. A Python script saves it as a playable WAV file.
- Signal chain: PDM mic -> DFSDM (sinc3 decimation) -> DMA (circular,
  ping-pong halves) -> RAM -> UART.
- 96 MHz system clock, 2.4 MHz mic clock (divider 40), oversampling 150,
  giving 16 kHz 16-bit PCM.
- Serial protocol uses a small header (magic bytes plus payload length) so
  recording duration can change in firmware without editing the PC script.

Also included: a numpy-only simulation of the localization algorithm
(GCC-PHAT delay estimation with upsampled peak interpolation, least squares
direction fusion) that serves as the reference implementation for the
future embedded port.

## Repo layout

```
firmware/mic_test/    STM32CubeIDE project (config lives in the .ioc file)
python/
  catch_audio.py      captures a recording from the serial port, saves WAV
  localization_sim.py 4 mic GCC-PHAT localization simulation and tests
```

## Hardware setup

- Board: NUCLEO-L552ZE-Q (no TrustZone)
- Mic: Adafruit MP34DT01-M breakout at 3.3 V, SEL tied to GND
- Wiring: CLK to PF10 (DFSDM1_CKOUT), DAT to PE7 (DFSDM1_DATIN2),
  morpho headers soldered for pin access

## Usage

1. Build and flash `firmware/mic_test` from STM32CubeIDE.
2. Close any open serial terminals, then run `python python/catch_audio.py`
   (edit the COM port at the top of the script first).
3. Press the blue user button. Green LED = recording, blue LED =
   transmitting. The script saves `recording.wav`.

`python/localization_sim.py` runs standalone and prints estimated versus
true source angles for a simulated sweep.

## Next milestones

1. Extend capture to four microphones (paired mics per data line via the
   SEL pin, DFSDM filter synchronization for sample alignment)
2. Offline localization validation with real clap recordings at known angles
3. Embedded GCC-PHAT port using CMSIS-DSP, validated against the Python
   reference on identical input
