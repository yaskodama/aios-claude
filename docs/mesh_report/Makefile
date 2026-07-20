all: mesh_report.pdf

mesh_report.pdf: main.tex dist3.tex
	xelatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
	xelatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
	mv main.pdf mesh_report.pdf

clean:
	rm -f main.aux main.log main.out main.toc main.pdf mesh_report.pdf
