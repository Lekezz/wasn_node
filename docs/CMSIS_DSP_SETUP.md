# CMSIS-DSP in this project

The on-board localization needs a 4096-point real FFT, which comes from
CMSIS-DSP. This document records how it got here and what to do if it ever
needs changing.

**Status: done.** Nothing is required of you to build. This is reference.

## What was done, and why not the CubeMX route

The obvious path is Software Packs > Select Components in CubeMX. That was
tried and abandoned for two reasons.

The only pack available locally that carries CMSIS-DSP is
**FP-SNS-STAIOTCFT**, an AI/IoT function pack. Selecting its CMSIS DSP entries
also switched on a USB Device CDC stack, a USB Device core, an AI_INERTIAL
application, PnPL and a pre-processing library. All of that would have landed
in the project and competed for the RAM the capture buffers need.

Beyond that, going through CubeMX means a regeneration, and CLAUDE.md records
that regeneration has silently reverted DFSDM DMA settings twice. The
localization work also depends on a hand-added `.ram2` section in the linker
script, which a regeneration can drop.

So instead the needed files were copied out of that pack into
`mic_test/Middlewares/CMSIS_DSP/`. No regeneration, no USB stack, and no
future CubeMX run can revert it. The `.ioc` was reverted to its committed
state and is untouched.

## What was copied

Source pack: `~/STM32Cube/Repository/Packs/STMicroelectronics/FP-SNS-STAIOTCFT/1.1.0/Drivers/CMSIS/DSP`

```
Middlewares/CMSIS_DSP/
    Inc/
        arm_math.h
        arm_common_tables.h        <- locally modified, see below
        arm_const_structs.h
        cmsis_dsp_config.h         <- ours, not upstream
    Src/
        arm_rfft_fast_f32.c        arm_rfft_fast_init_f32.c
        arm_cfft_f32.c             arm_cfft_radix8_f32.c
        arm_bitreversal2.c
        arm_common_tables.c        arm_const_structs.c
```

That is the complete dependency set for `arm_rfft_fast_f32`. It was verified
by linking: the only unresolved symbols across the whole pipeline are libc and
libm (`atan2f`, `sqrtf`, `printf`, `memset`), which the project already
provides.

## The one local modification

`arm_common_tables.h` has an added `#include "cmsis_dsp_config.h"` near the
top, before its `ARM_FFT_ALLOW_TABLES` guard. It is commented in place.

This matters more than it sounds. Compiled whole, `arm_common_tables.c` is
**707 KB**, larger than this part's entire 512 KB of flash, because it holds
twiddle and bit-reversal tables for every FFT length and every data type. The
generic `arm_rfft_fast_init_f32()` dispatcher references all of them, so
`--gc-sections` cannot drop the unused ones.

`cmsis_dsp_config.h` turns on CMSIS-DSP's own `ARM_DSP_CONFIG_TABLES` mode and
names only the three tables a 4096-point real FFT needs. Result:

| | before | after |
|---|---|---|
| `arm_common_tables.o` | 707 KB | 40 KB |
| whole DSP set | 712 KB | 44 KB |

Note that a 4096-point *real* FFT is internally a 2048-point *complex* FFT,
which is why two of the three defines say 2048. If `LOC_FFT_LEN` in
`loc_config.h` ever changes, the table defines must follow; the rule is in the
comments of `cmsis_dsp_config.h`. Getting it wrong is a clean boot-time
failure (`Localize_Init()` reports it), not a wrong answer.

## Project integration

`.cproject` gained four lines, two per build configuration:

```xml
<listOptionValue builtIn="false" value="../Middlewares/CMSIS_DSP/Inc"/>
<entry flags="VALUE_WORKSPACE_PATH|RESOLVED" kind="sourcePath" name="Middlewares"/>
```

The first puts the headers on the include path; the second makes CDT compile
the folder at all, since `sourceEntries` previously listed only `Core` and
`Drivers`. Both Debug and Release were updated identically.

## Verified

Built with the ARM toolchain at `-O2 -ffunction-sections -fdata-sections`,
linked against the project's real linker script:

```
flash image           55,712 bytes   (of 512 KB)
.ram2                 49,152 bytes   at 0x20030000, of RAM2's 64 KB
```

`.ram2` carries only the `ALLOC` flag, exactly like `.bss`, so the 48 KB of FFT
buffers cost **zero flash**. That is the `(NOLOAD)` in the linker script doing
its job, and it was confirmed by measuring the `.bin`.

## If CMSIS-DSP ever needs replacing

`Core/Inc/fft_backend.h` is a four-function interface and `fft_backend.c` is
about forty lines. It is the only file in the project that includes
`arm_math.h`. Any real FFT can sit behind it, including a self-contained
radix-2 implementation with no external dependency, without touching
`gcc_phat.c`, `localize.c` or `array_geometry.c`.

## If you ever do run CubeMX again

Commit first, then afterwards check that the generator did not undo anything:

```
grep -E "Dma.DFSDM1_FLT[0-3].*(Mode|DataAlignment)" mic_test/mic_test.ioc
grep -A3 "ram2" mic_test/STM32L552ZETXQ_FLASH.ld
grep -c "CMSIS_DSP" mic_test/.cproject
```

All twelve DMA lines must read `DMA_CIRCULAR` and `WORD`; the `.ram2` section
must still be there; `.cproject` must still show 4 CMSIS_DSP references.
Anything missing, restore it with `git checkout <file>`.
