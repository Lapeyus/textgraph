#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""textgraph desde la terminal.

Ejemplos:
  python3 cli.py texto.txt
  python3 cli.py texto.txt -f graphml -f llm -o salida/
  cat texto.txt | python3 cli.py - --motor local
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textgraph import exporters, store            # noqa: E402
from textgraph.model import slug                  # noqa: E402
from textgraph.pipeline import construir          # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Convierte un texto en grafo de conocimiento")
    ap.add_argument("entrada", nargs="?", help="archivo de texto o - para leer de la entrada estándar")
    ap.add_argument("-o", "--salida", default=".", help="carpeta de salida")
    ap.add_argument("-f", "--formato", action="append",
                    help="formato de exportación (repetible). Por defecto: json html llm")
    ap.add_argument("-t", "--titulo", default="")
    ap.add_argument("-m", "--motor", default="auto",
                    choices=["auto", "claude-cli", "api", "local"])
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--fragmento", type=int, default=3500)
    ap.add_argument("--paralelo", type=int, default=2,
                    help="fragmentos procesados a la vez (por defecto 2)")
    ap.add_argument("--sin-exhaustividad", action="store_true",
                    help="no usar el modelo para conectar entidades sueltas")
    ap.add_argument("--fusion-llm", action="store_true")
    ap.add_argument("--no-guardar", action="store_true",
                    help="no registrar el grafo en la carpeta data/")
    ap.add_argument("--listar-formatos", action="store_true")
    args = ap.parse_args()

    if args.listar_formatos:
        for f in exporters.FORMATOS:
            print("  %-11s %-18s %-12s %s" % (f[0], f[1], f[3], f[4]))
        return 0

    if not args.entrada:
        ap.error("falta el archivo de entrada")
    texto = sys.stdin.read() if args.entrada == "-" else \
        open(args.entrada, encoding="utf-8").read()
    if not texto.strip():
        print("entrada vacía", file=sys.stderr)
        return 1

    titulo = args.titulo or (os.path.basename(args.entrada) if args.entrada != "-" else "")

    def progreso(**kw):
        sys.stderr.write("  [%s] %s\n" % (kw.get("fase", ""), kw.get("mensaje", "")))

    grafo = construir(texto, titulo=titulo, engine=args.motor, modelo=args.modelo,
                      max_chars=args.fragmento, paralelo=args.paralelo,
                      exhaustividad=not args.sin_exhaustividad,
                      fusion_llm=args.fusion_llm, progreso=progreso)

    if not args.no_guardar:
        gid = store.guardar(grafo)
        sys.stderr.write("  guardado como proyecto: %s\n" % gid)

    if not os.path.isdir(args.salida):
        os.makedirs(args.salida)
    base = slug(grafo.title or "grafo", 50)
    for fmt in (args.formato or ["json", "html", "llm"]):
        datos, _, ext = exporters.exportar(grafo, fmt,
                                           os.path.join(os.path.dirname(
                                               os.path.abspath(__file__)), "web"))
        destino = os.path.join(args.salida, base + ext)
        with open(destino, "wb") as f:
            f.write(datos)
        sys.stderr.write("  escrito %s\n" % destino)

    st = grafo.to_dict()["stats"]
    sys.stderr.write("  %d nodos · %d relaciones · %d componente(s) · %d sin conectar\n"
                     % (st["nodos"], st["aristas"], st["componentes"], st["huerfanos"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
