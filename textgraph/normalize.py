# -*- coding: utf-8 -*-
"""Resolución de entidades: fusiona variantes de la misma cosa."""

import re
import unicodedata

from .model import slug

ARTICULOS = {"el", "la", "los", "las", "un", "una", "unos", "unas", "lo",
             "the", "a", "an", "l'", "il", "le"}
CONECTORES = {"de", "del", "la", "las", "los", "y", "e", "of", "the", "for",
              "en", "in", "da", "di", "von", "van", "der", "al"}


def clave(label):
    """Clave de comparación: sin acentos, sin artículos, sin puntuación."""
    t = unicodedata.normalize("NFKD", (label or "").strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t)
    ws = [w for w in t.split() if w]
    while ws and ws[0] in ARTICULOS:
        ws = ws[1:]
    return " ".join(ws)


def predicado(txt):
    """Normaliza la etiqueta de una relación a un predicado corto en minúsculas.

    Los modelos alternan estilos («fue juzgado por», «JUZGADO_POR»); aquí se
    unifican para que el grafo se lea de forma homogénea.
    """
    t = " ".join(str(txt or "").split()).strip(" .,;:")
    if re.fullmatch(r"[A-ZÁÉÍÓÚÑÜ0-9_\-]+", t or ""):
        t = t.replace("_", " ").replace("-", " ")
    t = t.lower()
    t = re.sub(r"^(que|el cual|la cual|se trata de)\s+", "", t)
    if len(t.split()) > 6:
        t = " ".join(t.split()[:6])
    return t or u"se relaciona con"


def tokens_significativos(label):
    # El umbral es 2 y no 3 a propósito: en vocabulario técnico hay tokens
    # cortos que distinguen productos («BigQuery ML» frente a «BigQuery»).
    return [w for w in clave(label).split() if w not in CONECTORES and len(w) >= 2]


def es_sigla_de(sigla, largo):
    s = re.sub(r"[^A-Za-z]", "", sigla)
    if not (2 <= len(s) <= 8) or not sigla.isupper():
        return False
    iniciales = "".join(w[0] for w in clave(largo).split() if w not in CONECTORES)
    return s.lower() == iniciales.lower()


def parejas_candidatas(nodos):
    """Devuelve [(a, b, motivo, confianza)] de posibles duplicados.

    En vez de comparar todos contra todos (cuadrático y lento en textos
    largos), se indexan las entidades por raíz de token y solo se comparan
    las que comparten alguna. Las siglas sí se comparan con todas, porque no
    comparten tokens con su forma desarrollada.
    """
    lst = list(nodos)
    indice = {}
    for i, n in enumerate(lst):
        claves = {t.rstrip("s") for t in tokens_significativos(n.label)}
        claves.add(clave(n.label))
        for al in n.aliases:
            claves.add(clave(al))
            claves.update(t.rstrip("s") for t in tokens_significativos(al))
        for c in claves:
            if c:
                indice.setdefault(c, set()).add(i)

    pares = set()
    for c, ids in indice.items():
        if len(ids) > 60:      # token demasiado común: mala pista
            continue
        ids = sorted(ids)
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                pares.add((ids[x], ids[y]))

    siglas = [i for i, n in enumerate(lst)
              if n.label.isupper() and 2 <= len(n.label) <= 8]
    for i in siglas:
        for j in range(len(lst)):
            if i != j:
                pares.add((min(i, j), max(i, j)))

    out = []
    for i, j in pares:
        m = _motivo(lst[i], lst[j])
        if m:
            out.append((lst[i], lst[j]) + m)
    out.sort(key=lambda p: -p[3])
    return out


def _motivo(a, b):
    ka, kb = clave(a.label), clave(b.label)
    if not ka or not kb:
        return None
    alias_a = {clave(x) for x in a.aliases} | {ka}
    alias_b = {clave(x) for x in b.aliases} | {kb}
    if alias_a & alias_b:
        return ("misma forma normalizada", 1.0)
    if es_sigla_de(a.label, b.label) or es_sigla_de(b.label, a.label):
        return ("sigla", 0.95)
    ta, tb = set(tokens_significativos(a.label)), set(tokens_significativos(b.label))
    if not ta or not tb:
        return None
    if a.type != b.type and "OTRO" not in (a.type, b.type):
        return None
    if ta == tb:
        return ("mismos tokens", 0.95)
    if ta < tb or tb < ta:
        chico, grande = (ta, tb) if ta < tb else (tb, ta)
        # "Curie" ⊂ "Marie Curie": alta confianza solo para personas
        if a.type == b.type == "PERSONA" and len(chico) == 1:
            return ("apellido", 0.85)
        if len(chico) >= 2 and len(grande) - len(chico) <= 2:
            # Deliberadamente por debajo del umbral de fusión automática:
            # «Cloud Run» y «Cloud Run functions» son productos distintos.
            return ("forma abreviada", 0.6)
        return ("subconjunto de tokens", 0.5)
    # plural / singular
    if {w.rstrip("s") for w in ta} == {w.rstrip("s") for w in tb}:
        return ("singular/plural", 0.8)
    # Casi iguales: comparten el grueso de los tokens y solo difieren en uno a
    # cada lado («Section 1: Data Preparation» vs «Sección 1. Data Preparation»).
    # Queda por debajo del umbral de fusión automática: solo se resuelve si se
    # activa la fusión asistida por el modelo.
    comunes = ta & tb
    if len(comunes) >= 2 and len(ta - tb) <= 1 and len(tb - ta) <= 1:
        return ("tokens casi iguales", 0.6)
    return None


def canonico(a, b):
    """Elige qué nodo sobrevive: el de etiqueta más informativa."""
    pa = (len(tokens_significativos(a.label)), len(a.label), len(a.mentions))
    pb = (len(tokens_significativos(b.label)), len(b.label), len(b.mentions))
    return (a, b) if pa >= pb else (b, a)


def fusionar(grafo, id_canon, id_absorbido):
    """Absorbe un nodo en otro, reescribiendo sus aristas."""
    if id_canon == id_absorbido:
        return
    canon = grafo.nodes.get(id_canon)
    otro = grafo.nodes.get(id_absorbido)
    if not canon or not otro:
        return
    canon.add_alias(otro.label)
    for al in otro.aliases:
        canon.add_alias(al)
    if len(otro.description) > len(canon.description):
        canon.description = otro.description
    if canon.type == "OTRO" and otro.type != "OTRO":
        canon.type = otro.type
    canon.mentions.extend(otro.mentions)
    canon.chunks |= otro.chunks

    del grafo.nodes[id_absorbido]
    aristas = list(grafo.edges.values())
    grafo.edges.clear()
    for e in aristas:
        if e.source == id_absorbido:
            e.source = id_canon
        if e.target == id_absorbido:
            e.target = id_canon
        if e.source == e.target:
            continue
        e.id = "e_%s__%s__%s" % (e.source, slug(e.label, 32), e.target)
        grafo.add_edge(e)


def resolver(grafo, umbral=0.7, motor=None, usar_llm=False, log=None):
    """Fusiona duplicados. Con `usar_llm` consulta al modelo los casos dudosos."""
    log = log if log is not None else []
    cambios = 0
    dudosas = []
    for a, b, motivo, conf in parejas_candidatas(list(grafo.nodes.values())):
        if a.id not in grafo.nodes or b.id not in grafo.nodes:
            continue
        if conf >= umbral:
            canon, absorbido = canonico(a, b)
            fusionar(grafo, canon.id, absorbido.id)
            log.append(u"fusión: «%s» ← «%s» (%s, %.2f)"
                       % (canon.label, absorbido.label, motivo, conf))
            cambios += 1
        else:
            dudosas.append((a, b, motivo, conf))

    if usar_llm and motor is not None and dudosas:
        listado = "\n".join(
            u"%d. «%s» (%s) vs «%s» (%s) — indicio: %s"
            % (i + 1, a.label, a.type, b.label, b.type, motivo)
            for i, (a, b, motivo, _) in enumerate(dudosas[:40]))
        try:
            for f in motor.fusiones(listado).get("fusiones", []):
                if not f.get("misma"):
                    continue
                na, nb = grafo.node_by_label(f.get("a")), grafo.node_by_label(f.get("b"))
                if not na or not nb or na.id == nb.id:
                    continue
                pref = grafo.node_by_label(f.get("canonico") or na.label) or na
                otro = nb if pref.id == na.id else na
                fusionar(grafo, pref.id, otro.id)
                log.append(u"fusión (modelo): «%s» ← «%s»" % (pref.label, otro.label))
                cambios += 1
        except Exception as e:
            log.append(u"aviso: fusión asistida por modelo no disponible (%s)" % e)
    return cambios
