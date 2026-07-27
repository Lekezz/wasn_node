/* fft_backend.c - CMSIS-DSP implementation of the FFT interface.
 *
 * REQUIRES CMSIS-DSP, WHICH IS NOT IN THE PROJECT BY DEFAULT.
 * If this file fails to compile with "arm_math.h: No such file or directory",
 * the library has not been added yet. See docs/CMSIS_DSP_SETUP.md.
 *
 * This is the only file in the localization pipeline that includes arm_math.h.
 */
#include "fft_backend.h"

#include "arm_math.h"

static arm_rfft_fast_instance_f32 s_rfft;
static int s_length = 0;


int Fft_Init(int length)
{
    /* arm_rfft_fast_init_f32 accepts 32,64,...,4096 and rejects anything
       else, which is exactly the check we want. */
    if (arm_rfft_fast_init_f32(&s_rfft, (uint16_t)length) != ARM_MATH_SUCCESS) {
        s_length = 0;
        return 0;
    }
    s_length = length;
    return 1;
}


int Fft_Length(void)
{
    return s_length;
}


void Fft_RealForward(float *in, float *out)
{
    /* Third argument 0 selects the forward transform. CMSIS uses `in` as
       scratch, which is why the header documents it as destroyed. */
    arm_rfft_fast_f32(&s_rfft, in, out, 0);
}


void Fft_RealInverse(float *in, float *out)
{
    arm_rfft_fast_f32(&s_rfft, in, out, 1);
}
