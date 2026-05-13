# Sample fluency evaluation

| checkpoint | n total | n ja | n en | fluency_ja | fluency_en | fluency_overall |
|---|---:|---:|---:|---:|---:|---:|
| `stage13_jp_heavy_125` | 375 | 165 | 210 | 0.544 | 0.997 | 0.798 |
| `stage12_multi_bpe4k` | 60 | 24 | 36 | 0.419 | 0.998 | 0.766 |
| `stage11_1b_tokens_bpe` | 60 | 3 | 57 | 0.063 | 0.998 | 0.951 |

## per-(language, temperature) means

| checkpoint | metric | value |
|---|---|---:|
| `stage13_jp_heavy_125` | en_temp0.6  (n=70) | 0.998 |
| `stage13_jp_heavy_125` | en_temp0.85  (n=70) | 0.997 |
| `stage13_jp_heavy_125` | en_temp1.05  (n=70) | 0.995 |
| `stage13_jp_heavy_125` | ja_temp0.6  (n=55) | 0.671 |
| `stage13_jp_heavy_125` | ja_temp0.85  (n=55) | 0.576 |
| `stage13_jp_heavy_125` | ja_temp1.05  (n=55) | 0.384 |
| `stage12_multi_bpe4k` | en_temp0.6  (n=12) | 0.997 |
| `stage12_multi_bpe4k` | en_temp0.85  (n=12) | 0.999 |
| `stage12_multi_bpe4k` | en_temp1.05  (n=12) | 0.997 |
| `stage12_multi_bpe4k` | ja_temp0.6  (n=8) | 0.556 |
| `stage12_multi_bpe4k` | ja_temp0.85  (n=8) | 0.441 |
| `stage12_multi_bpe4k` | ja_temp1.05  (n=8) | 0.261 |
| `stage11_1b_tokens_bpe` | en_temp0.6  (n=19) | 0.999 |
| `stage11_1b_tokens_bpe` | en_temp0.85  (n=19) | 0.998 |
| `stage11_1b_tokens_bpe` | en_temp1.05  (n=19) | 0.998 |
| `stage11_1b_tokens_bpe` | ja_temp0.6  (n=1) | 0.069 |
| `stage11_1b_tokens_bpe` | ja_temp0.85  (n=1) | 0.064 |
| `stage11_1b_tokens_bpe` | ja_temp1.05  (n=1) | 0.057 |
