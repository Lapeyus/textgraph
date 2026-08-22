# -*- coding: utf-8 -*-
"""Persistencia de proyectos en disco (un JSON por grafo)."""

import json
import os
import time

from .model import Graph, slug

RAIZ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _dir():
    if not os.path.isdir(RAIZ):
        os.makedirs(RAIZ)
    return RAIZ


def nuevo_id(titulo):
    base = slug(titulo or "grafo", 40) or "grafo"
    return "%s-%s" % (base, time.strftime("%Y%m%d-%H%M%S"))


def ruta(gid):
    return os.path.join(_dir(), "%s.json" % slug(gid, 80))


def guardar(grafo, gid=None):
    gid = gid or grafo.meta.get("id") or nuevo_id(grafo.title)
    grafo.meta["id"] = gid
    grafo.meta.setdefault("creado", time.time())
    grafo.meta["modificado"] = time.time()
    with open(ruta(gid), "w", encoding="utf-8") as f:
        json.dump(grafo.to_dict(), f, ensure_ascii=False)
    return gid


def cargar(gid):
    p = ruta(gid)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return Graph.from_dict(json.load(f))


def borrar(gid):
    p = ruta(gid)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


def listar():
    out = []
    for nombre in os.listdir(_dir()):
        if not nombre.endswith(".json"):
            continue
        try:
            with open(os.path.join(_dir(), nombre), encoding="utf-8") as f:
                d = json.load(f)
        except (ValueError, OSError):
            continue
        st = d.get("stats", {})
        meta = d.get("meta", {})
        out.append({
            "id": meta.get("id") or nombre[:-5],
            "titulo": d.get("title", ""),
            "nodos": st.get("nodos", 0), "aristas": st.get("aristas", 0),
            "modificado": meta.get("modificado") or os.path.getmtime(
                os.path.join(_dir(), nombre)),
            "motor": meta.get("motor", ""), "modelo": meta.get("modelo", ""),
        })
    out.sort(key=lambda x: -x["modificado"])
    return out
