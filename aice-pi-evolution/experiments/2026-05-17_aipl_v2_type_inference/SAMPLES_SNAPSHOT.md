# AIPL Phase E-2 段階 — 全サンプル実行スナップショット

**実行日:** 2026-05-17
**コマンド:** `python3 src/python-aipl/aipl_main.py <FILE> --check`
**段階:** Phase C / D / E-α / E-β / E-γ / E-γ-R / E-2 すべて適用後

21 サンプル / 7 feature × 3 を `--check` (typeck + inference の統合 pass) で再実行したスナップショット。詳細ログは `sample_outputs/<feature>__<sample>.log` (gitignored)。

## Feature と Phase の対応

| Feature | 内容 | 関連 Phase |
|---|---|---|
| `feature_a_hm/` | Hindley-Milner 型推論 (Int → Int, Bool, Rat/Real) | Phase C |
| `feature_b_crossclass/` | actor 越境推論 (cross-class signatures) | Phase D-1 |
| `feature_c_refinement/` | Int refinement + Z3 | Phase C + E-α |
| `feature_d_actorfields/` | class field 共有 (cross-method) | Phase E-β |
| `feature_e_records/` | record structural typing | Phase E-γ |
| `feature_f_realrat/` | Real/Rat refinement (Z3 Real theory) | Phase E-γ-R |
| `feature_g_integration/` | typeck × inference 統合 (`--check`) | Phase E-2 |

## サマリ (21 サンプル)

| Feature | Sample | typeck | inference |
|---|---|---|---|
| a_hm | a_hm__sample1_arithmetic | `[type] no issues.` | `[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| a_hm | a_hm__sample2_predicates | `[type] no issues.` | `[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| a_hm | a_hm__sample3_rat_real | `[type] no issues.` | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| b_crossclass | b_crossclass__sample1_simple | `[type] no issues.` | `[infer] 2 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| b_crossclass | b_crossclass__sample2_chained | `[type] no issues.` | `[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| b_crossclass | b_crossclass__sample3_init_args | `[type] no issues.` | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| c_refinement | c_refinement__sample1_satisfiable | `[type] no issues.` | `[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| c_refinement | c_refinement__sample2_unsatisfiable | `[type] no issues.` | `[infer] 4 method(s), 0 unify issue(s), 4 refinement issue(s)` |
| c_refinement | c_refinement__sample3_mixed | `[type] no issues.` | `[infer] 6 method(s), 0 unify issue(s), 2 refinement issue(s)` |
| d_actorfields | d_actorfields__sample1_simple | `[type] no issues.` | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| d_actorfields | d_actorfields__sample2_inferred_from_writes | `[type] no issues.` | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| d_actorfields | d_actorfields__sample3_conflict | `[type] 2 issue(s).` | `[infer] 3 method(s), 1 unify issue(s), 0 refinement issue(s)` |
| e_records | e_records__sample1_basic | `[type] no issues.` | `[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| e_records | e_records__sample2_inferred_from_use | `[type] no issues.` | `[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| e_records | e_records__sample3_conflict | `[type] no issues.` | `[infer] 1 method(s), 1 unify issue(s), 0 refinement issue(s)` |
| f_realrat | f_realrat__sample1_real_sat | `[type] no issues.` | `[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| f_realrat | f_realrat__sample2_real_unsat | `[type] no issues.` | `[infer] 4 method(s), 0 unify issue(s), 4 refinement issue(s)` |
| f_realrat | f_realrat__sample3_rat_mixed | `[type] no issues.` | `[infer] 5 method(s), 0 unify issue(s), 1 refinement issue(s)` |
| g_integration | g_integration__sample1_typeck_catches | `[type] 3 issue(s).` | `[infer] 2 method(s), 3 unify issue(s), 0 refinement issue(s)` |
| g_integration | g_integration__sample2_inference_catches | `[type] no issues.` | `[infer] 3 method(s), 0 unify issue(s), 1 refinement issue(s)` |
| g_integration | g_integration__sample3_clean | `[type] no issues.` | `[infer] 2 method(s), 0 unify issue(s), 0 refinement issue(s)` |

## 集計

- **21 / 21 サンプル run 成功** (Traceback / parse error なし)
- **typeck issue**: 2 サンプルで意図的 (`d_actorfields/sample3_conflict` = field 型衝突, `g_integration/sample1_typeck_catches` = 注釈/builtin 誤用)
- **unify issue**: 3 サンプルで意図的 (上記 2 件 + `e_records/sample3_conflict` = record shape mismatch)
- **refinement issue**: 6 件 UNSAT 検出 (`c_refinement/sample2,3`, `f_realrat/sample2,3`, `g_integration/sample2`)

意図したエラー検出を除けば clean。

## 各サンプル詳細出力


### a_hm__sample1_arithmetic

```
# samples/feature_a_hm/sample1_arithmetic.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_a_hm/sample1_arithmetic.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Arithmetic.square ===
  params:
    x : Int
  return : Int

=== Arithmetic.cube ===
  params:
    x : Int
  return : Int

=== Arithmetic.sum_of_squares ===
  params:
    a : ι
    b : ι
  return : ι

=== Arithmetic.abs_diff ===
  params:
    a : Int
    b : Int
  return : Int

=== Arithmetic.power ===
  params:
    base : Int
    exp : Int
  return : Int

=== class fields ===

[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### a_hm__sample2_predicates

```
# samples/feature_a_hm/sample2_predicates.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_a_hm/sample2_predicates.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Predicates.is_zero ===
  params:
    n : Int
  return : Bool

=== Predicates.is_positive ===
  params:
    n : Int
  return : Bool

=== Predicates.is_negative ===
  params:
    n : Int
  return : Bool

=== Predicates.in_range ===
  params:
    n : Int
    lo : Int
    hi : Int
  return : Bool
  locals:
    lo_ok : Bool

=== Predicates.same_sign ===
  params:
    a : Int
    b : Int
  return : Bool
  locals:
    ap : Bool
    bp : Bool

=== class fields ===

[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### a_hm__sample3_rat_real

```
# samples/feature_a_hm/sample3_rat_real.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_a_hm/sample3_rat_real.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Numerics.half_plus_third ===
  return : Rat
  locals:
    a : Rat
    b : Rat

=== Numerics.ratio_to_real ===
  params:
    r : Rat
    prec : Int
  return : Real
  locals:
    x : Real

=== Numerics.pi_approx ===
  params:
    prec : Int
  return : Real
  locals:
    pi_num : Rat
    pi_real : Real
    two : Real
    half_pi : Real

=== Numerics.scale_real ===
  params:
    r : Real
    factor_int : Int
  return : Real
  locals:
    f : Real

=== class fields ===

[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### b_crossclass__sample1_simple

```
# samples/feature_b_crossclass/sample1_simple.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_b_crossclass/sample1_simple.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Adder.add ===
  params:
    x : Int
    y : Int
  return : Int

=== Bridge.use_adder ===
  params:
    other : Adder
    a : Int
    b : Int
  return : Int
  locals:
    s : Int

=== class fields ===

[infer] 2 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### b_crossclass__sample2_chained

```
# samples/feature_b_crossclass/sample2_chained.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_b_crossclass/sample2_chained.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Producer.make_value ===
  return : Int

=== Filter.positive ===
  params:
    n : Int
  return : Int

=== Pipeline.run ===
  params:
    prod : Producer
    filt : Filter
  return : Int
  locals:
    v : Int
    p : Int

=== class fields ===

[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### b_crossclass__sample3_init_args

```
# samples/feature_b_crossclass/sample3_init_args.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_b_crossclass/sample3_init_args.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Counter.init ===
  params:
    initial : Int
  return : δ

=== Counter.get ===
  return : Int

=== Counter.bump ===
  params:
    delta : Int
  return : Int

=== CounterUser.exercise ===
  params:
    c : Counter
  return : Int
  locals:
    a : Int
    b : Int

=== class fields ===
  Counter:
    n : Int

[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### c_refinement__sample1_satisfiable

```
# samples/feature_c_refinement/sample1_satisfiable.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_c_refinement/sample1_satisfiable.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Sat.needs_nonneg ===
  params:
    k : {k: Int | k >= 0}
  return : Int

=== Sat.needs_ge_two ===
  params:
    n_terms : {n_terms: Int | n_terms >= 2}
  return : Int

=== Sat.needs_unit_sign ===
  params:
    sign : {sign: Int | sign == 1 or sign == -1}
  return : Int

=== Sat.needs_between ===
  params:
    m : {m: Int | m > 0 and m < 100}
  return : Int

=== Sat.needs_complex ===
  params:
    x : {x: Int | x >= 0 and x <= 100 and x != 50}
  return : Int

=== class fields ===

[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### c_refinement__sample2_unsatisfiable

```
# samples/feature_c_refinement/sample2_unsatisfiable.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_c_refinement/sample2_unsatisfiable.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Unsat.bad_range ===
  params:
    k : {k: Int | k >= 5 and k <= 3}
  return : {_: Int | k >= 5 and k <= 3}

=== Unsat.bad_sign ===
  params:
    x : {x: Int | x > 0 and x < 0}
  return : {_: Int | x > 0 and x < 0}

=== Unsat.bad_century ===
  params:
    n : {n: Int | n >= 100 and n <= 10}
  return : {_: Int | n >= 100 and n <= 10}

=== Unsat.bad_dual ===
  params:
    k : {k: Int | k == 1 and k == 2}
  return : {_: Int | k == 1 and k == 2}
  refinement issues:
    refinement is vacuously false: {_: Int | k >= 5 and k <= 3}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | x > 0 and x < 0}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | n >= 100 and n <= 10}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | k == 1 and k == 2}  (predicate is unsatisfiable)

=== class fields ===

[infer] 4 method(s), 0 unify issue(s), 4 refinement issue(s)
```

### c_refinement__sample3_mixed

```
# samples/feature_c_refinement/sample3_mixed.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_c_refinement/sample3_mixed.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Mixed.range_pred ===
  params:
    a : {a: Int | 0 <= a and a <= 100}
  return : Int

=== Mixed.nonzero ===
  params:
    b : {b: Int | not (b == 0)}
  return : Int

=== Mixed.holed ===
  params:
    c : {c: Int | (c == 0) or (c > 5 and c < 10)}
  return : Int

=== Mixed.solves_for_three ===
  params:
    d : {d: Int | 2 * d + 1 == 7}
  return : Int

=== Mixed.shadow_unsat ===
  params:
    x : {x: Int | (x > 10) and not (x > 5)}
  return : {_: Int | (x > 10) and not (x > 5)}

=== Mixed.arith_unsat ===
  params:
    y : {y: Int | y + 1 == y}
  return : {_: Int | y + 1 == y}
  refinement issues:
    refinement is vacuously false: {_: Int | (x > 10) and not (x > 5)}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | y + 1 == y}  (predicate is unsatisfiable)

=== class fields ===

[infer] 6 method(s), 0 unify issue(s), 2 refinement issue(s)
```

### d_actorfields__sample1_simple

```
# samples/feature_d_actorfields/sample1_simple.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_d_actorfields/sample1_simple.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Counter.init ===
  params:
    initial : Int
  return : δ

=== Counter.get ===
  return : Int

=== Counter.bump ===
  params:
    delta : Int
  return : Int

=== Counter.reset ===
  return : Int

=== class fields ===
  Counter:
    n : Int

[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### d_actorfields__sample2_inferred_from_writes

```
# samples/feature_d_actorfields/sample2_inferred_from_writes.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_d_actorfields/sample2_inferred_from_writes.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Source.value ===
  return : Int

=== Sink.put ===
  params:
    x : Int
  return : Int

=== Sink.peek ===
  return : Int

=== Bridge.feed ===
  params:
    s : Source
    k : Sink
  return : Int
  locals:
    v : Int
    r : Int

=== class fields ===
  Sink:
    stored : Int

[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### d_actorfields__sample3_conflict

```
# samples/feature_d_actorfields/sample3_conflict.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_d_actorfields/sample3_conflict.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] method Mixed.asInt: `s = ...` mismatch  (expected int, got Int)
[type] method Mixed.writeBool: `s = ...` mismatch  (expected int, got Bool)
[type] 2 issue(s).

=== --infer (HM + refinement + structural) ===
=== Mixed.asInt ===
  params:
    x : Int
  return : δ

=== Mixed.asBool ===
  return : Bool

=== Mixed.writeBool ===
  params:
    b : Bool
  return : η
  issues:
    [unify] cannot unify Int with Bool  at assign to s

=== class fields ===
  Mixed:
    s : Int

[infer] 3 method(s), 1 unify issue(s), 0 refinement issue(s)
```

### e_records__sample1_basic

```
# samples/feature_e_records/sample1_basic.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_e_records/sample1_basic.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Geometry.makePoint ===
  params:
    x : Int
    y : Int
  return : {a: Int, b: Int}

=== Geometry.dx ===
  params:
    p : {a: Int, b: Int}
    q : {a: Int, b: Int}
  return : Int

=== Geometry.magnitudeSquared ===
  params:
    p : {a: Int, b: Int}
  return : Int
  locals:
    x : Int
    y : Int

=== class fields ===

[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### e_records__sample2_inferred_from_use

```
# samples/feature_e_records/sample2_inferred_from_use.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_e_records/sample2_inferred_from_use.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Reader.first ===
  params:
    r : {head: Int, tail: Int}
  return : Int

=== Reader.second ===
  params:
    r : {head: Int, tail: Int}
  return : Int

=== Reader.both ===
  params:
    r : {head: Int, tail: Int}
  return : Int
  locals:
    a : Int
    b : Int

=== class fields ===

[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### e_records__sample3_conflict

```
# samples/feature_e_records/sample3_conflict.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_e_records/sample3_conflict.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Engine.process ===
  params:
    r : {key: Int, val: Int}
  return : Int
  issues:
    [unify] record fields differ: ['key', 'label'] vs ['key', 'val']  at Engine.process arg

=== class fields ===

[infer] 1 method(s), 1 unify issue(s), 0 refinement issue(s)
```

### f_realrat__sample1_real_sat

```
# samples/feature_f_realrat/sample1_real_sat.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_f_realrat/sample1_real_sat.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Reals.unit_open ===
  params:
    x : {x: Real | x > 0.0 and x < 1.0}
  return : {_: Real | x > 0.0 and x < 1.0}

=== Reals.nonneg ===
  params:
    y : {y: Real | y >= 0.0}
  return : {_: Real | y >= 0.0}

=== Reals.positive_below ===
  params:
    z : {z: Real | 0.0 < z and z < 100.0}
  return : {_: Real | 0.0 < z and z < 100.0}

=== Reals.offset_window ===
  params:
    w : {w: Real | w > a and w < a + 1.0}
  return : {_: Real | w > a and w < a + 1.0}

=== Reals.monotone ===
  params:
    p : {p: Real | p == 2.0 * q + 1.0}
  return : {_: Real | p == 2.0 * q + 1.0}

=== class fields ===

[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### f_realrat__sample2_real_unsat

```
# samples/feature_f_realrat/sample2_real_unsat.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_f_realrat/sample2_real_unsat.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== BadReals.gt1_lt05 ===
  params:
    x : {x: Real | x > 1.0 and x < 0.5}
  return : {_: Real | x > 1.0 and x < 0.5}

=== BadReals.strict_open_zero ===
  params:
    y : {y: Real | y > 0.0 and y < 0.0}
  return : {_: Real | y > 0.0 and y < 0.0}

=== BadReals.bigger_than_self ===
  params:
    z : {z: Real | z > z + 1.0}
  return : {_: Real | z > z + 1.0}

=== BadReals.bool_eq_int ===
  params:
    w : {w: Real | w == 1.0 and w == 2.0}
  return : {_: Real | w == 1.0 and w == 2.0}
  refinement issues:
    refinement is vacuously false: {_: Real | x > 1.0 and x < 0.5}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Real | y > 0.0 and y < 0.0}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Real | z > z + 1.0}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Real | w == 1.0 and w == 2.0}  (predicate is unsatisfiable)

=== class fields ===

[infer] 4 method(s), 0 unify issue(s), 4 refinement issue(s)
```

### f_realrat__sample3_rat_mixed

```
# samples/feature_f_realrat/sample3_rat_mixed.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_f_realrat/sample3_rat_mixed.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Mixed.rat_window ===
  params:
    r : {r: Rat | r > 0 and r < 1}
  return : {_: Rat | r > 0 and r < 1}

=== Mixed.rat_holed ===
  params:
    s : {s: Rat | (s > 0.0 and s < 0.4) or (s > 0.6 and s < 1.0)}
  return : {_: Rat | (s > 0.0 and s < 0.4) or (s > 0.6 and s < 1.0)}

=== Mixed.real_avoid_zero ===
  params:
    x : {x: Real | not (x == 0.0)}
  return : {_: Real | not (x == 0.0)}

=== Mixed.real_one_solution ===
  params:
    x : {x: Real | 2.0 * x + 1.0 == 4.0}
  return : {_: Real | 2.0 * x + 1.0 == 4.0}

=== Mixed.contradictory ===
  params:
    z : {z: Real | (z > 5.0) and not (z > 1.0)}
  return : {_: Real | (z > 5.0) and not (z > 1.0)}
  refinement issues:
    refinement is vacuously false: {_: Real | (z > 5.0) and not (z > 1.0)}  (predicate is unsatisfiable)

=== class fields ===

[infer] 5 method(s), 0 unify issue(s), 1 refinement issue(s)
```

### g_integration__sample1_typeck_catches

```
# samples/feature_g_integration/sample1_typeck_catches.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_g_integration/sample1_typeck_catches.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] function f: return type mismatch  (expected int, got string)
[type] method T.demo: `var n` initializer mismatch  (expected int, got string)
[type] method T.demo: call to function `write_file` arg `path` mismatch  (expected string, got int)
[type] 3 issue(s).

=== --infer (HM + refinement + structural) ===
=== (top).f ===
  params:
    a : int

=== T.demo ===
  return : γ
  locals:
    n : int
    rc : Int
    z : γ
  issues:
    [unify] cannot unify Str with int  at var n
    [unify] cannot unify Int with Str  at write_file arg 1
    [unbound] unknown function: f  at 

=== class fields ===

[infer] 2 method(s), 3 unify issue(s), 0 refinement issue(s)
```

### g_integration__sample2_inference_catches

```
# samples/feature_g_integration/sample2_inference_catches.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_g_integration/sample2_inference_catches.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Counter.init ===
  params:
    initial : Int
  return : δ

=== Counter.bump ===
  params:
    delta : Int
  return : Int

=== Counter.narrow ===
  params:
    k : {k: Int | k >= 5 and k <= 3}
  return : Int
  refinement issues:
    refinement is vacuously false: {_: Int | k >= 5 and k <= 3}  (predicate is unsatisfiable)

=== class fields ===
  Counter:
    n : Int

[infer] 3 method(s), 0 unify issue(s), 1 refinement issue(s)
```

### g_integration__sample3_clean

```
# samples/feature_g_integration/sample3_clean.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_g_integration/sample3_clean.aipl --check

=== --type-check (nominal + signature + effects) ===
[type] no issues.

=== --infer (HM + refinement + structural) ===
=== Writer.dump ===
  params:
    content : Str
  return : Int
  locals:
    rc : Int

=== Logger.log ===
  params:
    message : Str
    level : {level: Int | level >= 0 and level <= 9}
  return : Int
  locals:
    loud : Str
    rec : {sev: Int, what: Str, who: Str}

=== class fields ===
  Writer:
    path : Str
  Logger:
    w : Writer
    label : Str

[infer] 2 method(s), 0 unify issue(s), 0 refinement issue(s)
```
