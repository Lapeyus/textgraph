#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera el sitio de GitHub Pages con los grafos elegidos.

    python3 publicar.py                  # publica todos los grafos de data/
    python3 publicar.py revolucion       # solo los que casen con ese texto
    python3 publicar.py --salida docs

Cada grafo se exporta como HTML autónomo (visor interactivo completo, sin
servidor ni conexión) y se genera un índice que los enumera.
"""

import argparse
import html
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textgraph import exporters, store          # noqa: E402
from textgraph.model import slug                # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")

PLANTILLA = u"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>textgraph · grafos de conocimiento</title>
<style>
:root{{
  --fondo:#f6f7f9; --panel:#fff; --borde:#e2e5ea; --texto:#1c2430; --tenue:#697586;
  --acento:#2f6df6; --acento-suave:#e8f0ff;
  --sombra:0 1px 3px rgba(20,30,50,.08),0 8px 24px rgba(20,30,50,.06);
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--fondo);color:var(--texto);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}}
.envoltura{{max-width:920px;margin:0 auto;padding:48px 20px 72px}}
header{{display:flex;align-items:center;gap:14px;margin-bottom:8px}}
.logo{{font-size:38px;color:var(--acento);line-height:1}}
h1{{margin:0;font-size:26px;letter-spacing:-.02em}}
.lema{{margin:2px 0 0;color:var(--tenue);font-size:14px}}
.intro{{margin:24px 0 36px;max-width:65ch}}
.intro code{{background:var(--panel);border:1px solid var(--borde);border-radius:5px;
  padding:1px 5px;font-size:13px}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--tenue);
  margin:0 0 14px}}
.rejilla{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}}
.tarjeta{{background:var(--panel);border:1px solid var(--borde);border-radius:14px;
  padding:18px;text-decoration:none;color:inherit;display:flex;flex-direction:column;
  gap:10px;transition:border-color .15s,transform .15s,box-shadow .15s}}
.tarjeta:hover{{border-color:var(--acento);transform:translateY(-2px);box-shadow:var(--sombra)}}
.tarjeta h3{{margin:0;font-size:16px;line-height:1.35}}
.cifras{{display:flex;gap:6px;flex-wrap:wrap}}
.cifra{{background:var(--fondo);border:1px solid var(--borde);border-radius:999px;
  padding:2px 9px;font-size:11.5px;color:var(--tenue)}}
.cifra b{{color:var(--texto);font-variant-numeric:tabular-nums}}
.pie-tarjeta{{color:var(--tenue);font-size:12px;margin-top:auto}}
.abrir{{color:var(--acento);font-weight:600;font-size:13px}}
footer{{margin-top:48px;padding-top:20px;border-top:1px solid var(--borde);
  color:var(--tenue);font-size:13px}}
footer a{{color:var(--acento)}}
@media (prefers-color-scheme:dark){{
  /* En oscuro el azul de enlace debe aclararse o no se lee sobre el fondo. */
  :root{{--fondo:#12161c;--panel:#1a2029;--borde:#2b3441;--texto:#e8ecf1;--tenue:#93a0b1;
    --acento:#7ba6ff;--acento-suave:#1c2c4a}}
}}
</style>
</head>
<body>
<div class="envoltura">
  <header>
    <span class="logo">⁂</span>
    <div>
      <h1>textgraph</h1>
      <p class="lema">del texto al grafo de conocimiento</p>
    </div>
  </header>

  <p class="intro">Cada tarjeta abre un <b>visor interactivo autónomo</b>: el grafo
  completo, el texto original con las menciones resaltadas y la evidencia textual
  de cada relación, todo en un único archivo HTML. Los grafos se construyen con
  <a href="{repo}">textgraph</a>, que extrae entidades y relaciones de un texto y
  garantiza que ningún nodo quede aislado.</p>

  <h2>Grafos publicados</h2>
  <div class="rejilla">
{tarjetas}
  </div>

  <footer>
    Generado con <a href="{repo}">textgraph</a> · {fecha}
  </footer>
</div>
</body>
</html>
"""

TARJETA = u"""    <a class="tarjeta" href="grafos/{archivo}">
      <h3>{titulo}</h3>
      <div class="cifras">
        <span class="cifra"><b>{nodos}</b> nodos</span>
        <span class="cifra"><b>{aristas}</b> relaciones</span>
        <span class="cifra"><b>{comunidades}</b> comunidades</span>
      </div>
      <div class="pie-tarjeta">{descripcion}</div>
      <span class="abrir">Explorar el grafo →</span>
    </a>"""


def main():
    ap = argparse.ArgumentParser(description="Genera el sitio de GitHub Pages")
    ap.add_argument("filtro", nargs="*", help="publica solo los grafos cuyo id o título contenga estos textos")
    ap.add_argument("--salida", default="docs")
    ap.add_argument("--repo", default="https://github.com/Lapeyus/textgraph")
    args = ap.parse_args()

    destino = os.path.join(BASE, args.salida)
    grafos_dir = os.path.join(destino, "grafos")
    if not os.path.isdir(grafos_dir):
        os.makedirs(grafos_dir)

    proyectos = store.listar()
    if args.filtro:
        proyectos = [p for p in proyectos
                     if any(f.lower() in (p["id"] + " " + p["titulo"]).lower()
                            for f in args.filtro)]
    if not proyectos:
        print("no hay grafos que publicar", file=sys.stderr)
        return 1

    tarjetas = []
    for p in proyectos:
        g = store.cargar(p["id"])
        if not g:
            continue
        datos, _, _ = exporters.exportar(g, "html", WEB)
        archivo = slug(g.title or p["id"], 60) + ".html"
        with open(os.path.join(grafos_dir, archivo), "wb") as f:
            f.write(datos)
        d = g.to_dict()
        meta = d["meta"]
        descripcion = u"%s · %s · %s" % (
            time.strftime("%d/%m/%Y", time.localtime(meta.get("modificado", 0))),
            meta.get("modelo", "?"),
            u"%d componente, sin nodos aislados" % d["stats"]["componentes"]
            if d["stats"]["huerfanos"] == 0 else
            u"%d nodos sin conectar" % d["stats"]["huerfanos"])
        tarjetas.append(TARJETA.format(
            archivo=html.escape(archivo), titulo=html.escape(g.title or p["id"]),
            nodos=d["stats"]["nodos"], aristas=d["stats"]["aristas"],
            comunidades=meta.get("comunidades", "—"),
            descripcion=html.escape(descripcion)))
        print(u"  publicado  grafos/%s  (%d nodos, %d relaciones, %.0f KB)"
              % (archivo, d["stats"]["nodos"], d["stats"]["aristas"], len(datos) / 1024.0))

    indice = PLANTILLA.format(tarjetas="\n".join(tarjetas), repo=args.repo,
                              fecha=time.strftime("%d/%m/%Y"))
    with open(os.path.join(destino, "index.html"), "w", encoding="utf-8") as f:
        f.write(indice)
    # Evita que GitHub Pages procese el sitio con Jekyll.
    open(os.path.join(destino, ".nojekyll"), "w").close()
    print(u"  índice     %s/index.html  (%d grafo/s)" % (args.salida, len(tarjetas)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
