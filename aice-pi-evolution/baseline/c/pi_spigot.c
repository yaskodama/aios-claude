/* pi_spigot.c — 10,000 digits of π via the Rabinowitz–Wagon spigot.
 *
 * Reference baseline used by Pi_Phase0_LowLevelBaseline.aice as the
 * mid-tier (paradigm=C, type_safety=low, ownership_model=none) seed.
 *
 *   gcc -O2 pi_spigot.c -o pi_spigot
 *   ./pi_spigot 10000
 *
 * Memory:  ~33 KB int[]    Time on M2:  ~0.6 s for N=10000
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void spigot(int N) {
    int LEN = (10 * N) / 3 + 1;
    int *A = malloc(sizeof(int) * LEN);
    for (int i = 0; i < LEN; i++) A[i] = 2;

    int nines = 0, predigit = 0;
    for (int j = 1; j <= N; j++) {
        long q = 0;
        for (int i = LEN - 1; i > 0; i--) {
            long x = 10L * A[i] + q * i;
            A[i] = (int)(x % (2 * i + 1));
            q    = x / (2 * i + 1);
        }
        long x = 10L * A[0] + q;
        A[0]  = (int)(x % 10);
        q     = x / 10;

        if (q == 9) {
            nines++;
        } else if (q == 10) {
            putchar('0' + predigit + 1);
            for (int k = 0; k < nines; k++) putchar('0');
            predigit = 0; nines = 0;
        } else {
            if (j > 1) putchar('0' + predigit);
            for (int k = 0; k < nines; k++) putchar('9');
            predigit = (int)q; nines = 0;
        }
        if (j == 1) putchar('.');
    }
    putchar('0' + predigit);
    putchar('\n');
    free(A);
}

int main(int argc, char **argv) {
    int N = (argc > 1) ? atoi(argv[1]) : 10000;
    printf("3");
    spigot(N);
    return 0;
}
