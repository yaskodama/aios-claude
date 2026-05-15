// pi_10k.pl — PiLang reference program.
//
// This file is the embedded sample inside Pi_PiLang_Final.aice
// (pi_lang_syntax.sample_program). Extracted here for direct
// human review.  PiLang itself was *not* hand-written — it was
// selected by the MAP-Elites pipeline described in:
//
//   Pi_Phase0_LowLevelBaseline.aice   (5 low-level seeds)
//   Pi_Phase1_OpenSearch.aice         (60 cells × 40 generations)
//   Pi_Phase2_BignumRefinement.aice   (refine free axes + 3 new axes)
//   Pi_PiLang_Final.aice              (freeze the elite as the language)

pi : Real with digits = 10_000  with guard = +log2 N
   = chudnovsky |> binary_splitting |> emit
