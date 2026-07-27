# Adding CMSIS-DSP to the project

The on-board localization needs a 4096-point real FFT. That comes from
CMSIS-DSP, which is **not** in the project yet: `Drivers/CMSIS/` currently
holds only `Device`, `Include` and the licence file.

Until this is done, `Core/Src/fft_backend.c` will fail to compile with

```
fatal error: arm_math.h: No such file or directory
```

That is the expected failure, and it is confined to that one file on purpose.
Everything else in the pipeline (`gcc_phat.c`, `localize.c`,
`array_geometry.c`) has no CMSIS dependency and compiles today.

## Commit first

CLAUDE.md: commit before and after every CubeMX regeneration, so `git diff`
shows exactly what the generator changed. It has silently reverted DMA mode to
Normal and DMA width to Byte twice. Adding a software pack is a regeneration.

```
git add -A
git commit -m "Before adding CMSIS-DSP"
```

## Add the pack

1. Open `mic_test/mic_test.ioc` in STM32CubeIDE.
2. Menu: **Software Packs > Select Components** (or `Alt+O`).
3. Expand **CMSIS** > **DSP**. Tick the **DSP Library** component.
   Select the **Library** variant if offered a choice of Library vs Source;
   Source also works and is easier to step through in the debugger.
4. **OK**, then regenerate (`Alt+K` or Project > Generate Code).

If the DSP component is not listed, install it first through
**Help > Manage Embedded Software Packages > STMicroelectronics**, or use the
CMSIS pack entry, then repeat step 2.

## Verify the generator did not undo anything

This is the step that matters, and the reason for the commit above.

```
git diff --stat
git diff mic_test/mic_test.ioc
```

Check specifically that all four DFSDM filters still read
`DMA_CIRCULAR` and `WORD` on both sides:

```
grep -E "Dma.DFSDM1_FLT[0-3].*(Mode|DataAlignment)" mic_test/mic_test.ioc
```

Expected, twelve lines, one `Mode` and two `DataAlignment` per filter:

```
Dma.DFSDM1_FLT0.0.MemDataAlignment=DMA_MDATAALIGN_WORD
Dma.DFSDM1_FLT0.0.Mode=DMA_CIRCULAR
Dma.DFSDM1_FLT0.0.PeriphDataAlignment=DMA_PDATAALIGN_WORD
... same for FLT1, FLT2, FLT3
```

Anything reading `DMA_NORMAL` or `..._BYTE` means the generator reverted it.
Fix it in CubeMX and regenerate before going further.

## Verify the linker script survived

Regeneration can also rewrite `STM32L552ZETXQ_FLASH.ld`, which carries the
`.ram2` section the FFT buffers live in:

```
grep -A3 "ram2" mic_test/STM32L552ZETXQ_FLASH.ld
```

If the section is gone, the link fails with an undefined `.ram2` placement.
That is the intended failure mode: loud at build time rather than silent at run
time. Restore it from git:

```
git checkout mic_test/STM32L552ZETXQ_FLASH.ld
```

## Then commit again

```
git add -A
git commit -m "After adding CMSIS-DSP"
```

## Build and check the memory fits

The FFT buffers need 48 KB of the 64 KB RAM2 bank. After a successful build:

```
grep -E "^\.ram2" mic_test/Debug/mic_test.map
```

Should show 48 KB (0xC000) placed at 0x20030000. The main RAM bank should be
unchanged at about 159 KB of 192 KB used.

## If you would rather not add the pack

`Core/Inc/fft_backend.h` is a four-function interface, and `fft_backend.c` is
about forty lines. Any real FFT can sit behind it, including a self-contained
radix-2 implementation with no external dependency. Nothing above that file
knows or cares which one is in use.
