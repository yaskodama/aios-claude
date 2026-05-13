# Sample fluency evaluation

| checkpoint | n total | n ja | n en | n code | fluency_ja | fluency_en | fluency_code | fluency_overall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `stage9_bpe_vocab2048_125` | 375 | 165 | 192 | 18 | 0.076 | 0.998 | 0.415 | 0.564 |
| `stage11_1b_tokens_bpe_125` | 375 | 165 | 192 | 18 | 0.064 | 0.998 | 0.46 | 0.561 |
| `stage12_multi_bpe4k_125` | 375 | 165 | 192 | 18 | 0.459 | 0.997 | 0.481 | 0.736 |
| `stage13_jp_heavy_125` | 375 | 165 | 192 | 18 | 0.544 | 0.997 | 0.483 | 0.773 |

## per-(language, temperature) means

| checkpoint | metric | value |
|---|---|---:|
| `stage9_bpe_vocab2048_125` | code_temp0.6  (n=6) | 0.462 |
| `stage9_bpe_vocab2048_125` | code_temp0.85  (n=6) | 0.404 |
| `stage9_bpe_vocab2048_125` | code_temp1.05  (n=6) | 0.381 |
| `stage9_bpe_vocab2048_125` | en_temp0.6  (n=64) | 0.998 |
| `stage9_bpe_vocab2048_125` | en_temp0.85  (n=64) | 0.998 |
| `stage9_bpe_vocab2048_125` | en_temp1.05  (n=64) | 0.997 |
| `stage9_bpe_vocab2048_125` | ja_temp0.6  (n=55) | 0.074 |
| `stage9_bpe_vocab2048_125` | ja_temp0.85  (n=55) | 0.076 |
| `stage9_bpe_vocab2048_125` | ja_temp1.05  (n=55) | 0.076 |
| `stage11_1b_tokens_bpe_125` | code_temp0.6  (n=6) | 0.554 |
| `stage11_1b_tokens_bpe_125` | code_temp0.85  (n=6) | 0.399 |
| `stage11_1b_tokens_bpe_125` | code_temp1.05  (n=6) | 0.429 |
| `stage11_1b_tokens_bpe_125` | en_temp0.6  (n=64) | 0.999 |
| `stage11_1b_tokens_bpe_125` | en_temp0.85  (n=64) | 0.998 |
| `stage11_1b_tokens_bpe_125` | en_temp1.05  (n=64) | 0.997 |
| `stage11_1b_tokens_bpe_125` | ja_temp0.6  (n=55) | 0.067 |
| `stage11_1b_tokens_bpe_125` | ja_temp0.85  (n=55) | 0.069 |
| `stage11_1b_tokens_bpe_125` | ja_temp1.05  (n=55) | 0.056 |
| `stage12_multi_bpe4k_125` | code_temp0.6  (n=6) | 0.599 |
| `stage12_multi_bpe4k_125` | code_temp0.85  (n=6) | 0.46 |
| `stage12_multi_bpe4k_125` | code_temp1.05  (n=6) | 0.385 |
| `stage12_multi_bpe4k_125` | en_temp0.6  (n=64) | 0.998 |
| `stage12_multi_bpe4k_125` | en_temp0.85  (n=64) | 0.998 |
| `stage12_multi_bpe4k_125` | en_temp1.05  (n=64) | 0.996 |
| `stage12_multi_bpe4k_125` | ja_temp0.6  (n=55) | 0.659 |
| `stage12_multi_bpe4k_125` | ja_temp0.85  (n=55) | 0.44 |
| `stage12_multi_bpe4k_125` | ja_temp1.05  (n=55) | 0.278 |
| `stage13_jp_heavy_125` | code_temp0.6  (n=6) | 0.551 |
| `stage13_jp_heavy_125` | code_temp0.85  (n=6) | 0.466 |
| `stage13_jp_heavy_125` | code_temp1.05  (n=6) | 0.431 |
| `stage13_jp_heavy_125` | en_temp0.6  (n=64) | 0.998 |
| `stage13_jp_heavy_125` | en_temp0.85  (n=64) | 0.997 |
| `stage13_jp_heavy_125` | en_temp1.05  (n=64) | 0.995 |
| `stage13_jp_heavy_125` | ja_temp0.6  (n=55) | 0.671 |
| `stage13_jp_heavy_125` | ja_temp0.85  (n=55) | 0.576 |
| `stage13_jp_heavy_125` | ja_temp1.05  (n=55) | 0.384 |
