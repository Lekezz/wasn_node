/* fft_backend.h - the one place that knows which FFT library we use.
 *
 * Everything above this line (gcc_phat.c, localize.c) is written against this
 * four-function interface and includes no CMSIS-DSP headers. That is
 * deliberate: CMSIS-DSP is an external dependency that has to be added to the
 * project through CubeMX, and if it is missing or its API shifts between
 * versions, the compile error lands in fft_backend.c alone instead of
 * scattering across the pipeline. Swapping in a different FFT later means
 * rewriting one file.
 *
 * SPECTRUM LAYOUT. Fft_RealForward writes CMSIS-DSP's packed real-FFT format,
 * and the helpers below are the only things that need to understand it:
 *
 *     out[0]       = Re X[0]        (DC, imaginary part is always zero)
 *     out[1]       = Re X[N/2]      (Nyquist, likewise real)
 *     out[2k]      = Re X[k]        for k = 1 .. N/2-1
 *     out[2k + 1]  = Im X[k]
 *
 * so an N-point real transform produces exactly N floats, with the two
 * purely-real bins folded into the slot the imaginary part of DC would have
 * used. Numpy's rfft instead returns N/2+1 genuine complex bins. The maths is
 * identical; only the storage differs.
 *
 * SCALING. CMSIS and numpy do not agree on where the 1/N of the inverse
 * transform goes, and different CMSIS-DSP versions have not always agreed
 * with each other either. It does not matter here: GCC-PHAT only ever takes
 * the argmax of the correlation and a parabolic interpolation built from
 * ratios of three neighbouring samples. Both are invariant under a positive
 * global scale factor, so a missing or doubled 1/N cannot move the answer.
 * See the note in gcc_phat.c.
 */
#ifndef FFT_BACKEND_H
#define FFT_BACKEND_H

/* Prepare the transform for a given length. Must be called once before any
   other function here. length must be a power of two that the backend
   supports (32..4096 for CMSIS-DSP's fast real FFT).
   Returns 1 on success, 0 if the backend refused the length. */
int Fft_Init(int length);

/* Forward real FFT. in[] holds `length` real samples and IS DESTROYED.
   out[] receives `length` floats in the packed layout described above.
   in and out must not overlap. */
void Fft_RealForward(float *in, float *out);

/* Inverse real FFT. in[] holds `length` floats in the packed layout and IS
   DESTROYED. out[] receives `length` real samples.
   in and out must not overlap. */
void Fft_RealInverse(float *in, float *out);

/* The length passed to Fft_Init, or 0 if it has not been called. */
int Fft_Length(void);

#endif /* FFT_BACKEND_H */
