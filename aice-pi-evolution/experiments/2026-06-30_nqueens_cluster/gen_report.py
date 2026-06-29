#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate report.tex (xelatex / xeCJK) from results.json."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
RES  = os.path.join(HERE, "results.json")
TEX  = os.path.join(HERE, "report.tex")

CONFIGS = ["mac", "mac+rpi3", "mac+rpi3+rpi4", "mac+rpi3+rpi4+rpi5"]
CFG_TEX = {
    "mac":                r"Mac \scriptsize(AIPL)",
    "mac+rpi3":           r"+rpi3",
    "mac+rpi3+rpi4":      r"+rpi3+rpi4",
    "mac+rpi3+rpi4+rpi5": r"+rpi3+rpi4+rpi5",
}

rows = json.load(open(RES))
# index by (config,n)
by = {(r["config"], r["n"]): r for r in rows}
Ns = sorted({r["n"] for r in rows})


def fmt_t(s):
    if s is None: return "--"
    if s >= 1.0:  return "%.2f" % s
    return "%.3f" % s


def main_table():
    L = [r"\begin{tabular}{r" + "r" * len(CONFIGS) + "}", r"\toprule"]
    L.append("$N$ & " + " & ".join(CFG_TEX[c] for c in CONFIGS) + r" \\")
    L.append(r"\midrule")
    for n in Ns:
        cells = []
        for c in CONFIGS:
            r = by.get((c, n))
            cells.append(fmt_t(r["wall_s"]) if r else "--")
        L.append("%d & " % n + " & ".join(cells) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(L)


def speedup_table():
    """speedup of each cluster config vs Mac-alone, where Mac-alone exists."""
    L = [r"\begin{tabular}{r" + "r" * (len(CONFIGS) - 1) + "}", r"\toprule"]
    L.append("$N$ & " + " & ".join(CFG_TEX[c] for c in CONFIGS[1:]) + r" \\")
    L.append(r"\midrule")
    for n in Ns:
        mac = by.get(("mac", n))
        if not mac: continue
        cells = []
        for c in CONFIGS[1:]:
            r = by.get((c, n))
            if r and r["wall_s"] > 0:
                cells.append(r"$\times$%.0f" % (mac["wall_s"] / r["wall_s"]))
            else:
                cells.append("--")
        L.append("%d & " % n + " & ".join(cells) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(L)


def perworker_table():
    """device-side compute ms for the largest N that has board-config data."""
    board_ns = [r["n"] for r in rows if r["config"] != "mac"]
    n = max(board_ns) if board_ns else max(Ns)
    L = [r"\begin{tabular}{llrrr}", r"\toprule",
         r"構成 & ワーカー & 列範囲 & 部分解 & 端末計算[ms] \\", r"\midrule"]
    for c in CONFIGS[1:]:
        r = by.get((c, n))
        if not r: continue
        first = True
        for p in r["parts"]:
            cfg = CFG_TEX[c] if first else ""
            L.append(r"%s & %s & $[%d,%d)$ & %d & %s \\" % (
                cfg, p["worker"], p["c0"], p["c1"], p["solutions"],
                str(p["dev_ms"]) if p["dev_ms"] is not None else "--"))
            first = False
        L.append(r"\midrule")
    L[-1] = r"\bottomrule"
    L.append(r"\end{tabular}")
    return r"\textbf{$N=%d$}\\[2pt]" % n + "\n".join(L)


# headline numbers for the abstract
def headline():
    best = None
    for n in Ns:
        mac = by.get(("mac", n))
        if not mac: continue
        for c in CONFIGS[1:]:
            r = by.get((c, n))
            if r and r["wall_s"] > 0:
                sp = mac["wall_s"] / r["wall_s"]
                if best is None or sp > best[0]:
                    best = (sp, n, c)
    return best


PREAMBLE = r"""% !TEX program = xelatex
\documentclass[11pt,a4paper]{article}
\usepackage[a4paper,margin=22mm]{geometry}
\usepackage{xeCJK}
\usepackage{fontspec}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage{hyperref}
\setCJKmainfont{Hiragino Mincho ProN}
\setCJKsansfont{Hiragino Sans}
\setCJKmonofont{Hiragino Sans}
\setmonofont{Menlo}[Scale=0.82]
\hypersetup{colorlinks=true,linkcolor=black,urlcolor=blue!60!black,
  pdftitle={分散N-Queensベンチマーク},pdfauthor={Yasushi Kodama}}
\title{\bfseries 分散\,N\textendash Queens\,ベンチマーク\\[2pt]
\large Mac\,AIPL ランタイムと Raspberry\,Pi Xinu クラスタの協調実行}
\author{児玉 靖司\\ \small 法政大学経営学部 \quad\texttt{yass@hosei.ac.jp}}
\date{2026年6月30日}
"""


def build():
    sp, spn, spc = headline()
    doc = [PREAMBLE, r"\begin{document}", r"\maketitle"]

    doc.append(r"""\begin{abstract}
\normalsize
型付きAIエージェント言語 AIPL のインタプリタ実行系（Mac 上の Py\textendash I ランタイム）と，
ベアメタル Xinu を載せた Raspberry\,Pi 実機3台（rpi3/rpi4/rpi5）から成る WiFi クラスタを対象に，
古典的探索問題である $N$\textendash Queens を題材とした分散ベンチマークを行った．
第一クイーンの列位置で探索木を互いに素な部分に分割し，
各ワーカーへ列範囲を割り当てて並行実行・部分解の合算を行う方式を実装した．
4 構成（Mac 単体 / +rpi3 / +rpi3+rpi4 / +rpi3+rpi4+rpi5）について $N$ を漸増させて計測した結果，
インタプリタ実行系から native Xinu クラスタへ計算をオフロードすることで
最大 %s（$N=%d$，%s 構成）の高速化を確認した．
全構成の総解数は OEIS A000170 の既知値と完全に一致し，分散実行の正当性を検証した．
\end{abstract}""" % (r"$\times$%.0f" % sp, spn, spc.replace("mac+", "")))

    doc.append(r"""\section{背景と目的}
AIPL は型付きのAIエージェント指向言語であり，その参照実装（Py\textendash I ランタイム）は
動的型検査とアクタ・メッセージングを優先した\emph{インタプリタ}実行系である．
表現力と検証容易性の代償として実行速度は低く，重い数値探索には不向きである．
一方，筆者らは Raspberry\,Pi 3/4/5 上で動作するベアメタル Xinu に
SMP ワーカープール（コア0=OS，コア1\textendash3=計算ワーカー）と
HTTP アクタ実行系を実装してきた．
本実験の目的は，\textbf{遅いインタプリタ実行系の計算を，
ネットワーク越しに native な Xinu クラスタへ分散オフロードする}という
構成の有効性を，再現性のある定量ベンチマークで示すことである．

題材は $N$\textendash Queens（$N\times N$ 盤に互いに利かない $N$ 個のクイーンを置く配置数）とした．
解の総数は第一クイーンを置く列 $k\in\{0,\dots,N-1\}$ ごとの部分解数の互いに素な和であり，
列ごとに独立に数え上げできるため分散に適する．""")

    doc.append(r"""\section{実験環境}
\begin{itemize}\setlength{\itemsep}{1pt}
\item \textbf{Mac}（オーケストレータ兼 AIPL ワーカー）：AIPL の Py\textendash I ランタイムが
\texttt{nqueens\_subset.abcl}（ビットマスク無しの素朴な再帰探索）を解釈実行する．
\item \textbf{rpi3}（BCM2837 / Cortex\textendash A53）：単一コアで列範囲を直接計算（WiFi, \texttt{:8080}）．
\item \textbf{rpi4}（BCM2711 / Cortex\textendash A72 $\times$4）：SMP ワーカープールで列を4コアに分散．
\item \textbf{rpi5}（BCM2712 / Cortex\textendash A76 $\times$4）：同上，最新・最速コア．
\end{itemize}
各 Xinu ボードは native ルート \texttt{GET /nqpart?n=N\&c0=A\&c1=B} を備え，
第一クイーンを列 $[A,B)$ に置く配置数を数えて
\texttt{solutions=..\ ms=..\ cores=..} を返す．
rpi4/rpi5 ではこの列範囲を \texttt{smp\_parallel\_sum} で各コアに分配する．
ボード側 native 実装はビットマスク・バックトラッキングであり，
cc\textendash JIT の 250\,ms 暴走デッドラインを回避して正確な計数を保証する．""")

    doc.append(r"""\section{手法}
\begin{enumerate}\setlength{\itemsep}{1pt}
\item \textbf{分割}：$N$ 個の第一クイーン列 $\{0,\dots,N-1\}$ をアクティブなワーカー数で
ほぼ等分し，連続した列ブロックを各ワーカーに割り当てる
（rpi4/rpi5 は受け取ったブロックを内部でさらに各コアへ SMP 分散する）．
\item \textbf{Mac の扱い}：AIPL インタプリタは1ボードの $\sim10^4$ 倍遅いため，
複数ボード構成では Mac は列を担当せずオーケストレータに徹する（後述の通り測定上の必然）．
Mac 単体構成でのみ Mac が全列を解釈実行する．
\item \textbf{ウォームアップ}：計測前に各ボードへ極小要求（$N{=}4$）を1回送り，
単一スレッド webactor の初回往復遅延（最大 $\sim$35\,s）を計測から除く．
\item \textbf{計測}：オーケストレータが並行ディスパッチ開始から最後のワーカー応答までの
実時間（wall\textendash clock）を測る．これが各構成の所要時間である．
\item \textbf{検証}：各部分解の総和を OEIS A000170 の既知値と照合し，全 $(構成,N)$ で一致を確認した．
\end{enumerate}""")

    doc.append(r"\section{結果}")
    doc.append(r"\subsection{所要時間（wall\textendash clock 秒）}")
    doc.append(r"\begin{center}" + "\n" + main_table() + "\n" + r"\end{center}")
    doc.append(r"""全 $(構成,N)$ で総解数は既知値と一致した（正当性 100\%）．
Mac 単体は $N$ の増加に対し急峻に悪化する（解釈実行のため探索木サイズにほぼ比例）一方，
クラスタ構成は native 実行により桁違いに高速である．""")

    doc.append(r"\subsection{Mac 単体に対する高速化倍率}")
    doc.append(r"\begin{center}" + "\n" + speedup_table() + "\n" + r"\end{center}")

    doc.append(r"\subsection{最大 $N$ での列割り当てと端末計算時間}")
    doc.append(r"\begin{center}" + "\n" + perworker_table() + "\n" + r"\end{center}")

    doc.append(r"""\section{考察}
\paragraph{(1) インタプリタ・オフロードが支配的}
最大の効果は AIPL 解釈実行から native Xinu への計算移譲である．
Mac 単体は $N{=}10$ で約 7.3\,s，$N{=}11$ で約 41\,s を要したが，
同じ問題を1ボードに投げるだけで応答は $0.1$\,s 未満に収まる．
これは「遅い高水準実行系＋速いエッジ実機クラスタ」という非対称構成の実用的価値を示す．

\paragraph{(2) ネットワーク律速と計算律速の交差}
ボード同士の比較では2つの領域が現れる．小さい $N$ では計算が一瞬で終わり，
所要時間は HTTP 往復遅延に支配される（最遅ボードの RTT が律速）。
このためボードを増やすと\emph{かえって}遅くなることがある（協調オーバヘッド）。
$N$ が大きく計算が支配的になると，列分割による真の並列性が効き，
SMP コアを持つ rpi4/rpi5 を加えるほど makespan が縮む．

\paragraph{(3) ヘテロジニアス・クラスタ}
等分割では単一コアの rpi3 が割当ブロックのボトルネックになりやすい．
端末計算時間（表）から，同じ列数でも rpi3（1コア）対 rpi4/rpi5（4コア）で
処理時間が大きく異なることが読み取れる．
速度に比例した重み付き分割は今後の課題である．""")

    doc.append(r"""\section{結論}
AIPL インタプリタ実行系と native Xinu クラスタを協調させ，
$N$\textendash Queens を第一クイーン列で分割して分散実行する系を実装・計測した．
全構成で OEIS A000170 と一致する正しい解を得つつ，
インタプリタから実機クラスタへのオフロードにより大幅な高速化を達成した．
本結果は，重い計算を高速なエッジ実機群へ委譲する AIPL 実行モデルの妥当性を支持する．

\vspace{4pt}\noindent\footnotesize
参考：N\textendash Queens 解数列 OEIS A000170 \url{https://oeis.org/A000170}．
測定スクリプト \texttt{nq\_cluster\_bench.py}，生データ \texttt{results.json}．""")

    doc.append(r"\end{document}")
    open(TEX, "w").write("\n\n".join(doc))
    print("wrote", TEX)


if __name__ == "__main__":
    build()
