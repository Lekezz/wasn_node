# HANDOFF: project history and pending work

This file holds the story, the open work, and the debugging history that
explains why things are the way they are. Read together with CLAUDE.md,
which holds the compact always-true facts. Last updated 2026-07-22
(four-mic capture proven on hardware, geometry moved into a registry,
active layout 9.25 x 10 cm on two glued breadboards).

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
- The four-mic user code is in mic_test/Core/Src/main.c as of commit
  b21479e. Sync-order filter start, per-mic circular DMA drain via a
  filter->mic map, "WAV4" UART dump. RECORD_SECS dropped 4 -> 1 for the
  RAM budget. 0 errors, 0 warnings, bss 164040 bytes.
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

## Reference: the 4-mic user code, as landed in main.c

DONE, committed in b21479e. This listing is kept as a backup because
CubeMX regeneration wipes anything outside the USER CODE fences, and this
is the fastest way to restore it. If main.c and this listing ever
disagree, main.c wins. All of it lives inside USER CODE fences in
mic_test/Core/Src/main.c.

USER CODE BEGIN PD:

    #define SAMPLE_RATE   16000
    #define RECORD_SECS   1
    #define NUM_MICS      4
    #define TOTAL_SAMPLES (SAMPLE_RATE * RECORD_SECS)
    #define DMA_BUF_LEN   2048
    #define WARMUP_SAMPLES 4000

USER CODE BEGIN PV (replaces the single-mic buffers):

    int32_t dma_buf[NUM_MICS][DMA_BUF_LEN];
    int16_t recording[NUM_MICS][TOTAL_SAMPLES];
    volatile uint32_t rec_index[NUM_MICS];
    volatile uint32_t warmup_left[NUM_MICS];
    volatile uint8_t half_flag[NUM_MICS], full_flag[NUM_MICS];
    volatile uint8_t recording_active = 0;
    extern UART_HandleTypeDef hcom_uart[];

USER CODE BEGIN 0 (replaces store_samples):

    /* filter0=ch2 PE7 rising -> mic0, filter1=ch1 PE7 falling -> mic1,
       filter2=ch0 PB1 rising -> mic2, filter3=ch3 PB1 falling -> mic3 */
    static int filter_to_mic(DFSDM_Filter_HandleTypeDef *f)
    {
        if (f == &hdfsdm1_filter0) return 0;
        if (f == &hdfsdm1_filter1) return 1;
        if (f == &hdfsdm1_filter2) return 2;
        return 3;
    }

    static void store_samples(int mic, int32_t *src, uint32_t count)
    {
        uint32_t i = 0;
        while (i < count && warmup_left[mic] > 0) {   /* burn off warm-up */
            warmup_left[mic]--;
            i++;
        }
        for (; i < count && rec_index[mic] < TOTAL_SAMPLES; i++) {
            recording[mic][rec_index[mic]++] = (int16_t)(src[i] >> 8);
        }
    }

USER CODE BEGIN 2 (new, forces filter sync even if CubeMX did not):

    hdfsdm1_filter1.Init.RegularParam.Trigger = DFSDM_FILTER_SYNC_TRIGGER;
    hdfsdm1_filter2.Init.RegularParam.Trigger = DFSDM_FILTER_SYNC_TRIGGER;
    hdfsdm1_filter3.Init.RegularParam.Trigger = DFSDM_FILTER_SYNC_TRIGGER;
    if (HAL_DFSDM_FilterInit(&hdfsdm1_filter1) != HAL_OK) Error_Handler();
    if (HAL_DFSDM_FilterInit(&hdfsdm1_filter2) != HAL_OK) Error_Handler();
    if (HAL_DFSDM_FilterInit(&hdfsdm1_filter3) != HAL_OK) Error_Handler();

USER CODE BEGIN 4 (replaces the two callbacks):

    void HAL_DFSDM_FilterRegConvHalfCpltCallback(DFSDM_Filter_HandleTypeDef *f)
    {
        half_flag[filter_to_mic(f)] = 1;
    }

    void HAL_DFSDM_FilterRegConvCpltCallback(DFSDM_Filter_HandleTypeDef *f)
    {
        full_flag[filter_to_mic(f)] = 1;
    }

USER CODE BEGIN WHILE (replaces the whole single-mic state machine):

    if (!recording_active && BspButtonState == BUTTON_PRESSED)
    {
      BspButtonState = BUTTON_RELEASED;
      for (int m = 0; m < NUM_MICS; m++) {
        rec_index[m] = 0;
        warmup_left[m] = WARMUP_SAMPLES;
        half_flag[m] = 0;
        full_flag[m] = 0;
      }
      recording_active = 1;
      BSP_LED_On(LED_GREEN);
      /* sync-armed filters first, trigger filter LAST */
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter1, dma_buf[1], DMA_BUF_LEN) != HAL_OK) Error_Handler();
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter2, dma_buf[2], DMA_BUF_LEN) != HAL_OK) Error_Handler();
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter3, dma_buf[3], DMA_BUF_LEN) != HAL_OK) Error_Handler();
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter0, dma_buf[0], DMA_BUF_LEN) != HAL_OK) Error_Handler();
    }

    if (recording_active)
    {
      for (int m = 0; m < NUM_MICS; m++) {
        if (half_flag[m]) { half_flag[m] = 0; store_samples(m, &dma_buf[m][0], DMA_BUF_LEN / 2); }
        if (full_flag[m]) { full_flag[m] = 0; store_samples(m, &dma_buf[m][DMA_BUF_LEN / 2], DMA_BUF_LEN / 2); }
      }

      uint8_t all_done = 1;
      for (int m = 0; m < NUM_MICS; m++)
        if (rec_index[m] < TOTAL_SAMPLES) all_done = 0;

      if (all_done)
      {
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter0);
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter1);
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter2);
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter3);
        recording_active = 0;
        BSP_LED_Off(LED_GREEN);
        BSP_LED_On(LED_BLUE);

        uint32_t nbytes = TOTAL_SAMPLES * 2u;
        uint8_t header[8] = { 'W','A','V','4',
                              (uint8_t)nbytes, (uint8_t)(nbytes >> 8),
                              (uint8_t)(nbytes >> 16), (uint8_t)(nbytes >> 24) };
        HAL_UART_Transmit(&hcom_uart[COM1], header, 8, HAL_MAX_DELAY);
        for (int m = 0; m < NUM_MICS; m++)
          HAL_UART_Transmit(&hcom_uart[COM1], (uint8_t *)recording[m],
                            (uint16_t)nbytes, HAL_MAX_DELAY);

        BSP_LED_Off(LED_BLUE);
      }
    }

Notes on this code (all already applied, kept as rationale):
- The warm-up discard exists because two notes in this file contradicted
  each other: trim the first second of settling, but RECORD_SECS is 1 so
  there is nothing left to trim. Dropping 0.25 s in firmware before
  storing starts resolves it. Sync is safe because every mic drops the
  same count from its own stream, so the channels shift together.
- 32000 bytes per channel fits a single HAL_UART_Transmit (uint16_t size
  limit is 65535), so no chunking loop needed at RECORD_SECS 1. If the
  duration ever grows, reintroduce chunking (this bug bit us once: the
  size arg silently truncated 128000 to 62464).
- Verify against the generated code that handle names match (hdfsdm1_filter0
  through hdfsdm1_filter3, hdfsdm1_channel0/1/2/3). Adjust if CubeMX named
  them differently.
- Before building, confirm in stm32l5xx_hal_msp.c: all four DMA inits say
  DMA_CIRCULAR and WORD alignment, and GPIO comments list PF10, PE7, PB1.

## Reference: 4-channel capture script

DONE, committed in e6058c1 as mic_sims_files/catch_audio4.py. Syncs on
magic "WAV4", reads the 4-byte little-endian per-channel length, then
reads four sequential channel blocks. Saves mic0.wav..mic3.wav plus
capture.npy, an int16 array shaped (4, nsamples) matching the mic_signals
layout localization_sim.py expects, so a capture feeds gcc_phat with no
reshaping. The single-mic "WAV0" version is still there as catch_audio.py.

## Milestones from here

1. DONE. Mics 1-3 wired on the temporary in-line breadboard.
2. First 4-mic run. This is the first time this firmware executes at all,
   so expect to debug the code as much as the wiring. Sequence:
     - flash the current main.c (the warm-up change needs a rebuild)
     - python catch_audio4.py COM4    (start it BEFORE the button press)
     - press the blue button, wait about half a second for the warm-up to
       pass, then one sharp clap 30 to 50 cm away, broadside to the line
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
