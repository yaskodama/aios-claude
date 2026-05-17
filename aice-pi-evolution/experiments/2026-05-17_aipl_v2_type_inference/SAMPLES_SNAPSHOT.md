# AIPL Phase E-β 段階 — サンプル実行スナップショット

**実行日:** 2026-05-17
**インタプリタ:** `/opt/homebrew/bin/python3 src/python-aipl/aipl_main.py <FILE> --infer`

12 サンプル / 4 feature × 3 = 既存全件を最新エンジン (Phase E-β 段階) で再実行した結果のスナップショット。詳細ログは `sample_outputs/<feature>__<sample>.log` (gitignored)。

## サマリ

| Feature | Sample | 結果 |
|---|---|---|
| a_hm | a_hm__sample1_arithmetic | `[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| a_hm | a_hm__sample2_predicates | `[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| a_hm | a_hm__sample3_rat_real | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| b_crossclass | b_crossclass__sample1_simple | `[infer] 2 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| b_crossclass | b_crossclass__sample2_chained | `[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| b_crossclass | b_crossclass__sample3_init_args | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| c_refinement | c_refinement__sample1_satisfiable | `[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| c_refinement | c_refinement__sample2_unsatisfiable | `[infer] 4 method(s), 0 unify issue(s), 4 refinement issue(s)` |
| c_refinement | c_refinement__sample3_mixed | `[infer] 6 method(s), 0 unify issue(s), 2 refinement issue(s)` |
| d_actorfields | d_actorfields__sample1_simple | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| d_actorfields | d_actorfields__sample2_inferred_from_writes | `[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)` |
| d_actorfields | d_actorfields__sample3_conflict | `[infer] 3 method(s), 1 unify issue(s), 0 refinement issue(s)` |

## 各サンプルの推論結果

### a_hm__sample1_arithmetic

```
# samples/feature_a_hm/sample1_arithmetic.aipl
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_a_hm/sample1_arithmetic.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_a_hm/sample2_predicates.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_a_hm/sample3_rat_real.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_b_crossclass/sample1_simple.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_b_crossclass/sample2_chained.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_b_crossclass/sample3_init_args.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_c_refinement/sample1_satisfiable.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_c_refinement/sample2_unsatisfiable.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_c_refinement/sample3_mixed.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_d_actorfields/sample1_simple.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_d_actorfields/sample2_inferred_from_writes.aipl --infer

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
# command: /opt/homebrew/bin/python3 ../../../src/python-aipl/aipl_main.py samples/feature_d_actorfields/sample3_conflict.aipl --infer

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
