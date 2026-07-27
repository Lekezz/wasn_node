/* cmsis_dsp_config.h - trim CMSIS-DSP down to the one transform we use.
 *
 * NOT part of CMSIS-DSP. Added for this project, and included from the top of
 * arm_common_tables.h and arm_const_structs.h so every vendored source sees it
 * no matter which header it reaches first.
 *
 * WHY THIS EXISTS
 *
 * arm_common_tables.c carries twiddle and bit-reversal tables for every FFT
 * length and every data type (q7, q15, q31, f32). Compiled whole it is 707 KB,
 * larger than this part's entire 512 KB of flash. The generic
 * arm_rfft_fast_init_f32() dispatcher references all of them, so --gc-sections
 * cannot drop the unused ones: they are genuinely reachable.
 *
 * CMSIS-DSP's own answer is ARM_DSP_CONFIG_TABLES, which switches the tables
 * from "all of them" to "only the ones named by ARM_TABLE_* defines". Turning
 * it on takes the same object from 707 KB to 40 KB, and the whole DSP set from
 * 712 KB to 44 KB.
 *
 * WHICH DEFINES, AND WHY EXACTLY THESE
 *
 * We call arm_rfft_fast_init_f32(&S, 4096). Its `case 4096` is compiled in
 * only when all three table defines below are present, and a 4096-point real
 * FFT is internally a 2048-point complex FFT, which is why the twiddle and
 * bit-reversal tables are the 2048 ones while only the rfft twiddle is 4096.
 * Drop any one and the case vanishes, arm_rfft_fast_init_f32 returns
 * ARM_MATH_ARGUMENT_ERROR at run time, Fft_Init() returns 0, and
 * Localize_Init() reports failure at boot.
 *
 * ARM_FFT_ALLOW_TABLES is separate and easy to miss. arm_common_tables.h line
 * 34 hides the entire FFT table block behind it whenever ARM_DSP_CONFIG_TABLES
 * is set, so without it the build fails with
 * "ARMBITREVINDEXTABLE_2048_TABLE_LENGTH undeclared".
 *
 * IF YOU CHANGE LOC_FFT_LEN
 *
 * These defines are tied to the 4096-point transform. Changing LOC_WINDOW_LEN
 * in loc_config.h changes LOC_FFT_LEN, and the table set below has to follow:
 * for an N-point real FFT you need TWIDDLECOEF_F32_(N/2),
 * BITREVIDX_FLT_(N/2) and TWIDDLECOEF_RFFT_F32_N. Getting it wrong is a clean
 * boot-time failure, not a wrong answer.
 */
#ifndef CMSIS_DSP_CONFIG_H
#define CMSIS_DSP_CONFIG_H

/* Select tables individually instead of compiling in every one. */
#define ARM_DSP_CONFIG_TABLES

/* Expose the FFT table declarations at all under selective mode. */
#define ARM_FFT_ALLOW_TABLES

/* Exactly the tables a 4096-point real FFT needs. */
#define ARM_TABLE_TWIDDLECOEF_F32_2048
#define ARM_TABLE_BITREVIDX_FLT_2048
#define ARM_TABLE_TWIDDLECOEF_RFFT_F32_4096

#endif /* CMSIS_DSP_CONFIG_H */
