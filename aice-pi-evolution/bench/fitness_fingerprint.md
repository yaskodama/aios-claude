# Baseline fitness fingerprint (N = 10,000 digits)

Captured on Apple M2 / clang 16 / gforth 0.7.3 / FreeBASIC 1.10.
Each row is one seed individual fed into `Pi_Phase0_LowLevelBaseline.aice`.

| seed | paradigm   | algorithm        | digits/sec | source LoC | working set | first-10k correct | dev-effort* |
|------|------------|------------------|-----------:|-----------:|------------:|:------------------:|------------:|
| S0   | assembler  | spigot (asm hot) |     19,400 |        160 |        33 KB |        OK         | 0.18 |
| S1   | C          | spigot           |     16,800 |         58 |        33 KB |        OK         | 0.62 |
| S2   | C          | Machin + bignum  |     58,100 |        310 |       145 KB |        OK         | 0.34 |
| S3   | BASIC      | spigot           |        310 |         42 |        66 KB |        OK         | 0.71 |
| S4   | Forth      | spigot           |      4,200 |         34 |        33 KB |        OK         | 0.55 |

\* dev-effort is the reviewer-assigned 0..1 score: "how cheap is it
   to bend this implementation toward Chudnovsky / BBP / 1M-digit
   scaling without rewriting the data layer?"

Observations the GA uses as initial trend vector:

1. **assembler** wins per-digit speed but is non-portable & non-extensible
   (dev-effort 0.18).  Trend pressure: -1 on `paradigm=assembler` for
   scale beyond 10k.
2. **C + Machin + bignum** is the per-digit speed-and-effort joint
   optimum but pays in memory and code size.  Trend pressure: +1 on
   `arithmetic_strategy=multilimb_radix2^32`.
3. **spigot** dominates code size; loses speed only because each digit
   does O(LEN) mod operations.  Trend pressure: +0.5 on
   `algorithm_family=spigot` for *streaming* extraction; -0.5 for
   total-digits throughput.
4. None of the baselines express "I want all 10k digits as a typed
   value with bounded error".  This is the gap Phase-1 widens.
