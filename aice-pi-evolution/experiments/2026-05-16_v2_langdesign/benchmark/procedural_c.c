/* procedural_c.c  — π to N decimal digits via Chudnovsky binary
 *                   splitting (Haible–Papanikolaou form) in plain C
 *                   with GMP + MPFR.
 *
 *   Build:
 *     clang -O2 -I/opt/homebrew/include procedural_c.c \
 *           -L/opt/homebrew/lib -lmpfr -lgmp -o procedural_c
 *
 *   Run:   ./procedural_c 10000        ( default if no arg )
 *
 *   Algorithm — for each leaf k ≥ 1:
 *       p_k = -(6k-5)(2k-1)(6k-1)
 *       q_k =  k^3 · (C^3 / 24)              with C = 640320
 *       t_k =  p_k · (A + B·k)               A = 13591409, B = 545140134
 *   For the special leaf k=0:  p_0 = q_0 = 1,  t_0 = A.
 *   Combine [a, b) := combine( bsplit(a, m), bsplit(m, b) ):
 *       P = P_l · P_r
 *       Q = Q_l · Q_r
 *       T = Q_r · T_l + P_l · T_r
 *   Then  S = T_root / Q_root   and   π = 426880·√10005 / S
 *                                   = 426880·√10005 · Q_root / T_root .
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <gmp.h>
#include <mpfr.h>

static const long A_const = 13591409L;
static const long B_const = 545140134L;
static const long C_const = 640320L;
static const long C3_24   = 10939058860032000L;   /* C^3 / 24 */

typedef struct { mpz_t P, Q, T; } pqt;

static void pqt_init (pqt *r) { mpz_inits (r->P, r->Q, r->T, NULL); }
static void pqt_clear(pqt *r) { mpz_clears(r->P, r->Q, r->T, NULL); }

static void leaf(pqt *r, long k) {
    if (k == 0) {
        mpz_set_ui(r->P, 1);
        mpz_set_ui(r->Q, 1);
        mpz_set_si(r->T, A_const);
    } else {
        /* p_k = -(6k-5)(2k-1)(6k-1) */
        mpz_set_si(r->P, -(6*k - 5));
        mpz_mul_si (r->P, r->P, 2*k - 1);
        mpz_mul_si (r->P, r->P, 6*k - 1);
        /* q_k = k^3 · (C^3 / 24) */
        mpz_set_si (r->Q, k);
        mpz_mul_si (r->Q, r->Q, k);
        mpz_mul_si (r->Q, r->Q, k);
        mpz_mul_si (r->Q, r->Q, C3_24);
        /* t_k = p_k · (A + B·k) */
        mpz_set_si (r->T, A_const + B_const * k);
        mpz_mul    (r->T, r->T, r->P);
    }
}

static void bsplit(pqt *r, long a, long b) {
    if (b - a == 1) { leaf(r, a); return; }
    long m = (a + b) / 2;
    pqt L, R;
    pqt_init(&L); pqt_init(&R);
    bsplit(&L, a, m);
    bsplit(&R, m, b);
    mpz_t tmp;
    mpz_init(tmp);
    /* T = Q_r · T_l + P_l · T_r   (do this BEFORE overwriting P, Q) */
    mpz_mul(r->T,  L.T, R.Q);
    mpz_mul(tmp,   L.P, R.T);
    mpz_add(r->T,  r->T, tmp);
    mpz_mul(r->P,  L.P, R.P);
    mpz_mul(r->Q,  L.Q, R.Q);
    mpz_clear(tmp);
    pqt_clear(&L); pqt_clear(&R);
}

int main(int argc, char **argv) {
    long digits = (argc > 1) ? atol(argv[1]) : 10000;
    long N      = digits / 14 + 2;
    /* bits = ceil(digits·log2(10)) + small guard */
    long prec   = (long)(digits * 3.33) + 64;

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    pqt root;
    pqt_init(&root);
    bsplit(&root, 0, N);

    mpfr_t pi, sqrt10005, num, q_mp, t_mp;
    mpfr_set_default_prec(prec);
    mpfr_inits(pi, sqrt10005, num, q_mp, t_mp, (mpfr_ptr)0);

    mpfr_sqrt_ui(sqrt10005, 10005, MPFR_RNDN);                /* √10005 */
    mpfr_mul_ui (sqrt10005, sqrt10005, 426880, MPFR_RNDN);    /* 426880·√10005 */

    mpfr_set_z(q_mp, root.Q, MPFR_RNDN);
    mpfr_set_z(t_mp, root.T, MPFR_RNDN);
    mpfr_mul (num,  sqrt10005, q_mp, MPFR_RNDN);
    mpfr_div (pi,   num,       t_mp, MPFR_RNDN);

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed_ms = (t1.tv_sec - t0.tv_sec) * 1000.0
                      + (t1.tv_nsec - t0.tv_nsec) / 1e6;

    mpfr_printf("%.*Rf\n", (int)digits, pi);
    fprintf(stderr, "elapsed_ms=%.3f\n", elapsed_ms);

    mpfr_clears(pi, sqrt10005, num, q_mp, t_mp, (mpfr_ptr)0);
    pqt_clear(&root);
    return 0;
}
