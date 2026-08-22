# -*- coding: utf-8 -*-
"""Índice de menciones: dónde aparece cada entidad en el texto original."""

import re
import unicodedata

from .chunker import sentences


def _sin_acentos(t):
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def _aplanar(texto):
    """Versión sin acentos que conserva EXACTAMENTE la longitud original.

    Es imprescindible: los desplazamientos calculados sobre esta cadena se
    aplican al texto original, y una normalización que cambie la longitud
    (ligaduras, fracciones, símbolos compuestos) desplazaría las menciones.
    """
    salida = []
    for ch in texto:
        plano = _sin_acentos(ch)
        salida.append(plano if len(plano) == 1 else ch)
    return "".join(salida)


def _patron(forma):
    """Patrón tolerante a acentos, mayúsculas y espacios múltiples."""
    partes = []
    for ch in _sin_acentos(forma):
        if ch.isspace():
            partes.append(r"\s+")
        elif ch.isalnum():
            partes.append(re.escape(ch) + "́?")
        else:
            partes.append(re.escape(ch))
    cuerpo = "".join(partes)
    ini = r"(?<![\w])" if forma[:1].isalnum() else ""
    fin = r"(?![\w])" if forma[-1:].isalnum() else ""
    return ini + cuerpo + fin


def indexar(grafo, texto):
    """Rellena `nodo.mentions` con todas las apariciones literales en el texto."""
    sents = sentences(texto)
    limites = [(s[0], s[1], i) for i, s in enumerate(sents)]
    plano = _aplanar(texto)

    formas = []   # (forma, node_id)
    for nid, n in grafo.nodes.items():
        for f in [n.label] + list(n.aliases):
            f = (f or "").strip()
            if len(f) >= 2:
                formas.append((f, nid))
    formas.sort(key=lambda x: -len(x[0]))

    ocupado = [False] * (len(texto) + 1)
    for nodo in grafo.nodes.values():
        nodo.mentions = []

    for forma, nid in formas:
        try:
            rx = re.compile(_patron(forma), re.IGNORECASE)
        except re.error:
            continue
        for m in rx.finditer(plano):
            a, b = m.start(), m.end()
            if b - a < 2 or any(ocupado[a:b]):
                continue
            for i in range(a, b):
                ocupado[i] = True
            idx = _sentencia(limites, a)
            grafo.nodes[nid].mentions.append({
                "start": a, "end": b, "quote": texto[a:b],
                "sentencia": idx,
                "contexto": sents[idx][2] if idx is not None else "",
            })

    for nodo in grafo.nodes.values():
        nodo.mentions.sort(key=lambda x: x["start"])
    return sents


def _sentencia(limites, pos):
    for ini, fin, i in limites:
        if ini <= pos < fin:
            return i
    return None


def por_sentencia(grafo):
    """{indice_sentencia: set(node_id)}"""
    mapa = {}
    for nid, n in grafo.nodes.items():
        for m in n.mentions:
            i = m.get("sentencia")
            if i is None:
                continue
            mapa.setdefault(i, set()).add(nid)
    return mapa
