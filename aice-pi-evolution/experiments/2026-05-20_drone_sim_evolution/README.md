# Drone Simulator Evolution

Round 0 seed: `drone_sim_v0.html` — copy of the live simulator at
https://lecture.site44.com/drone/ (1134 行, 41 KB, 2D Canvas +
3D Three.js dual view, faithful to M-006 (FIT2023 関口/加藤/神林)).

Working file: `index.html` — evolves through Round 1's 13 phases as
laid out in [`AIPL_DroneSim_Round1.aice`](./AIPL_DroneSim_Round1.aice).

## Phase log

| Phase | 内容 | Smoke |
|---|---|---|
| R0   | Round 0 base copy from the live URL | (baseline) |
| **A1** | **α/β/γ real-time sliders + reset button** | **10/10** |
| **A3** | **Statistics panel — cumulative rescued / remaining / per-trial time / UAV2 distance line chart** | **10/10** |
| **A4** | **Scenario selector — Table 1 / All Empty / Random (seeded) / Custom JSON** | **18/18** |
| **A2** | **UAV1 sweep: TSP + 2-opt + priority-bias + transit dedup** | **5/5** |
| **B2** | **Secondary-disaster events — cut 3 random edges + visual X marks + isolation warning** | **11/11** |
| **B3** | **SOS broadcasts — N-hop gossip + decaying priority bonus + golden halo** | **13/13** |
| B1 | … | — |
| B4 | … | — |
| C2 | … | — |
| C1 | … | — |
| D1 | … | — |
| D3 | … | — |
| D2 | … | — |

## Evolution artefacts

- `AIPL_DroneSim_Round1.aice` — Round 1 design (13 phases, all 4 directions)
- `AIPL_DroneSim_Round1.ga.json` — lowered IR (full 30 gen / 8 seed)
- `AIPL_DroneSim_Round1_ai.ga.json` — smaller variant for the OpenAI run
- `out/` — mock_v1 MAP-Elites results (38 individuals, 30 generations)
- `out_ai/` — gpt-4o-mini MAP-Elites results (14 individuals, 10 gen)

Both evaluators independently agree on `concurrency_model →
actor_messages` as the most-moved axis — supporting Direction C
(UAV as AIPL Cell actor).

## Quick test

```bash
open aice-pi-evolution/experiments/2026-05-20_drone_sim_evolution/index.html
```

Move the α / β / γ sliders — the Point State table's Pri. column
updates live, and node halos change intensity in real time.
