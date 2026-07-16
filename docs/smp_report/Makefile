# Raspberry Pi Xinu マルチコア化レポート
#
#   make        -> smp_report.pdf を生成
#   make clean  -> 中間ファイルを削除
#
# ★ 目次と相互参照(\ref)のために xelatex を 2 回まわす必要がある。

DOC := main
OUT := smp_report

all: $(OUT).pdf

$(OUT).pdf: $(DOC).tex boards/rpi3.tex boards/rpi4.tex boards/rpi5.tex
	xelatex -interaction=nonstopmode -halt-on-error $(DOC).tex
	xelatex -interaction=nonstopmode -halt-on-error $(DOC).tex
	mv $(DOC).pdf $(OUT).pdf

clean:
	rm -f $(DOC).aux $(DOC).log $(DOC).out $(DOC).toc $(DOC).pdf

.PHONY: all clean
