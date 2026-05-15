10 REM ----------------------------------------------------------------
20 REM  pi_spigot.bas  - 10000 digits of pi via Rabinowitz-Wagon spigot.
30 REM  Reference baseline (paradigm=BASIC, type_safety=low,
40 REM  state_representation=global_num) for Pi_Phase0.aice.
50 REM ----------------------------------------------------------------
100 N = 10000
110 LEN = INT(10 * N / 3) + 1
120 DIM A(LEN)
130 FOR I = 0 TO LEN - 1 : A(I) = 2 : NEXT I
140 NINES = 0 : PRED = 0
150 PRINT "3";
160 FOR J = 1 TO N
170   Q = 0
180   FOR I = LEN - 1 TO 1 STEP -1
190     X = 10 * A(I) + Q * I
200     A(I) = X - INT(X / (2 * I + 1)) * (2 * I + 1)
210     Q    = INT(X / (2 * I + 1))
220   NEXT I
230   X = 10 * A(0) + Q
240   A(0) = X - INT(X / 10) * 10
250   Q    = INT(X / 10)
260   IF Q = 9 THEN NINES = NINES + 1 : GOTO 350
270   IF Q <> 10 THEN GOTO 310
280     PRINT CHR$(48 + PRED + 1);
290     FOR K = 1 TO NINES : PRINT "0"; : NEXT K
300     PRED = 0 : NINES = 0 : GOTO 350
310   IF J > 1 THEN PRINT CHR$(48 + PRED);
320     FOR K = 1 TO NINES : PRINT "9"; : NEXT K
330     PRED = Q : NINES = 0
340     IF J = 1 THEN PRINT ".";
350 NEXT J
360 PRINT CHR$(48 + PRED)
370 END
