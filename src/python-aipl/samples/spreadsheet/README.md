# WebSpreadsheet — AIPL implementation (round 3, in progress)

進化計算 round 1-2 で採掘された設計を実装に落とすブランチ.
具体的な選択は:

- Round 1: `aice-pi-evolution/experiments/2026-05-18_web_spreadsheet/RESULTS.md`
- Round 2: `aice-pi-evolution/experiments/2026-05-18_web_spreadsheet_impl/RESULTS.md`

| 項目 | 選定 |
|---|---|
| T (cell 表現)  | T4 ActorPerCell |
| C (計算位置)   | C1 ClientFull |
| S (同期)       | S1 SingleUser (MVP) |
| U (UI)         | U2 Canvas_2D |
| CA (spawn)     | CA4 HybridSpawn |
| FE (eval)      | FE4 ActorEval |
| P  (永続化)    | P3 DistCheckpoint |
| R  (renderer)  | R3 LayerComposite |
| PA (parser)    | PA4 LevelCPort |
| IT (topology)  | IT2 EventBus |

## Phase 進捗

| Phase | 内容 | サンプル | 状態 |
|---|---|---|---|
| 0 | AST-formula eval (parser なし) | `HelloSheet.abcl` | ✅ 5 assertion |
| 1 | PA4 formula parser (`A1`, `+`, `SUM(...)`) | `StringFormulaSheet.abcl` | ✅ 4 assertion |
| 2 | CA4 cell actors + FE4 ActorEval | `ActorSheet.abcl` | ⏳ |
| 3 | P3 persistence (save/load) | `PersistedSheet.abcl` | ⏳ |
| 4 | R3 renderer + IT2 event bus | browser-abcl 統合 | ⏳ |

## smoke

```sh
bash src/python-aipl/samples/spreadsheet/_smoke.sh
# → pass=9  fail=0 (Phase 0 + 1)
```

## 進化計算 → 実装の橋渡し

- `RESULTS.md` の LOC 内訳と推奨 6-tuple は **そのまま実装の北極星**
- 各 phase で増分実装、smoke で前 phase が破綻していないことを確認
- ≤2500 LOC ceiling は round 1-2 で何度も繰り返し確認された制約
