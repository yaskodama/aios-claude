# Mesh load-distribution evolution — N=10, M=4

- N-Queens(10) solutions: **724**
- serial (1 node): 7173 ms; perfect-balance bound: 1793 ms (x4)
- per-column cost ms: [620, 706, 748, 727, 775, 775, 732, 753, 710, 627]

| strategy | makespan ms | speed-up |
|---|---|---|
| naive-contiguous | 2260 | x3.17 |
| round-robin | 2107 | x3.40 |
| greedy-LPT | 2106 | x3.41 |
| evolved-GA | 2063 | x3.48 |

GA cut makespan **9%** below the naive contiguous split.
