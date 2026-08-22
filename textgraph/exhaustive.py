# -*- coding: utf-8 -*-
"""Garantía de exhaustividad: ningún nodo queda suelto y el grafo es conexo.

Estrategia en cascada, de más a menos respaldo textual:
  1. co-ocurrencia en la misma oración,
  2. reconciliación asistida por el modelo,
  3. co-ocurrencia en el mismo fragmento,
  4. enlace estructural al nodo más central (último recurso, marcado como tal).
"""

from .model import Edge
from . import mentions as mod_mentions
from .normalize import predicado


def _mas_central(grafo, ids):
    def clave(nid):
        n = grafo.nodes[nid]
        return (n.metrics.get("pagerank", 0.0), grafo.degree(nid), len(n.mentions))
    return max(ids, key=clave) if ids else None


def paso_coocurrencia(grafo, sents, ambito="sentencia", log=None):
    """Conecta huérfanos con entidades que comparten oración (o fragmento)."""
    log = log if log is not None else []
    huerfanos = set(grafo.orphans())
    if not huerfanos:
        return 0
    mapa = mod_mentions.por_sentencia(grafo)
    nuevas = 0
    for nid in list(huerfanos):
        if grafo.degree(nid):
            continue
        nodo = grafo.nodes[nid]
        candidatas = []
        for m in nodo.mentions:
            i = m.get("sentencia")
            if i is None:
                continue
            rango = [i] if ambito == "sentencia" else range(max(0, i - 2), i + 3)
            for j in rango:
                for otro in mapa.get(j, ()):
                    if otro != nid:
                        candidatas.append((otro, j))
        if not candidatas:
            continue
        vistos = set()
        for otro, j in candidatas[:3]:
            if otro in vistos:
                continue
            vistos.add(otro)
            texto = sents[j][2] if j < len(sents) else ""
            e = Edge(nid, otro, u"aparece junto a", "coocurrencia", texto, 0.35,
                     directed=False)
            if grafo.add_edge(e):
                nuevas += 1
                log.append(u"co-ocurrencia (%s): «%s» ↔ «%s»"
                           % (ambito, nodo.label, grafo.nodes[otro].label))
    return nuevas


def paso_modelo(grafo, motor, log=None, max_huerfanos=40):
    """Pide al modelo relaciones para los nodos que siguen aislados."""
    log = log if log is not None else []
    huerfanos = grafo.orphans()
    if not huerfanos or motor is None or not getattr(motor, "usa_llm", True):
        return 0
    bloques = []
    for nid in huerfanos[:max_huerfanos]:
        n = grafo.nodes[nid]
        ctx = [m.get("contexto", "") for m in n.mentions[:3] if m.get("contexto")]
        bloques.append(u"- «%s» (%s)%s\n  contexto: %s"
                       % (n.label, n.type,
                          (u" — " + n.description) if n.description else "",
                          " / ".join(ctx) or u"(sin contexto localizado)"))
    conectados = [nid for nid in grafo.nodes if grafo.degree(nid)]
    conectados.sort(key=lambda x: -grafo.nodes[x].metrics.get("pagerank", 0)
                    if grafo.nodes[x].metrics else -grafo.degree(x))
    catalogo = "\n".join(u"- «%s» (%s)" % (grafo.nodes[i].label, grafo.nodes[i].type)
                         for i in conectados[:120]) or u"(el grafo aún no tiene aristas)"
    try:
        rel = motor.reconciliar("\n".join(bloques), catalogo).get("relaciones", [])
    except Exception as e:
        log.append(u"aviso: reconciliación con modelo fallida (%s)" % e)
        return 0

    nuevas = 0
    for r in rel:
        a = grafo.node_by_label(r.get("origen"))
        b = grafo.node_by_label(r.get("destino"))
        if not a or not b or a.id == b.id:
            continue
        e = Edge(a.id, b.id, predicado(r.get("etiqueta")),
                 r.get("tipo") if r.get("tipo") in ("explicita", "implicita") else "implicita",
                 r.get("evidencia") or "", float(r.get("confianza") or 0.6))
        if grafo.add_edge(e):
            nuevas += 1
            log.append(u"reconciliación: «%s» —%s→ «%s»" % (a.label, e.label, b.label))
    return nuevas


def paso_estructural(grafo, log=None):
    """Último recurso: engancha cada huérfano al nodo más central de su fragmento."""
    log = log if log is not None else []
    nuevas = 0
    for nid in grafo.orphans():
        nodo = grafo.nodes[nid]
        vecinos_frag = [o for o, n in grafo.nodes.items()
                        if o != nid and (n.chunks & nodo.chunks) and grafo.degree(o)]
        destino = _mas_central(grafo, vecinos_frag) or _mas_central(
            grafo, [o for o in grafo.nodes if o != nid])
        if not destino:
            continue
        ctx = nodo.mentions[0].get("contexto", "") if nodo.mentions else ""
        e = Edge(nid, destino, u"contexto compartido", "estructural", ctx, 0.15,
                 directed=False)
        if grafo.add_edge(e):
            nuevas += 1
            log.append(u"enlace estructural: «%s» ↔ «%s»"
                       % (nodo.label, grafo.nodes[destino].label))
    return nuevas


def paso_componentes(grafo, motor=None, texto="", log=None):
    """Une los componentes desconectados hasta dejar un único grafo conexo."""
    log = log if log is not None else []
    comps = grafo.components()
    if len(comps) <= 1:
        return 0
    nuevas = 0

    if motor is not None and getattr(motor, "usa_llm", True) and len(comps) <= 12:
        bloques = []
        for i, comp in enumerate(comps[:12]):
            top = sorted(comp, key=lambda x: -grafo.degree(x))[:8]
            bloques.append(u"Grupo %d: %s" % (
                i + 1, ", ".join(u"«%s» (%s)" % (grafo.nodes[t].label,
                                                 grafo.nodes[t].type) for t in top)))
        try:
            rel = motor.puentes("\n".join(bloques), texto[:6000],
                                n=len(comps)).get("relaciones", [])
        except Exception as e:
            rel = []
            log.append(u"aviso: puentes con modelo fallidos (%s)" % e)
        for r in rel:
            a = grafo.node_by_label(r.get("origen"))
            b = grafo.node_by_label(r.get("destino"))
            if not a or not b or a.id == b.id:
                continue
            e = Edge(a.id, b.id, predicado(r.get("etiqueta")), "implicita",
                     r.get("evidencia") or "", float(r.get("confianza") or 0.5))
            if grafo.add_edge(e):
                nuevas += 1
                log.append(u"puente: «%s» —%s→ «%s»" % (a.label, e.label, b.label))

    # cierre garantizado
    comps = grafo.components()
    if len(comps) > 1:
        principal = _mas_central(grafo, comps[0])
        for comp in comps[1:]:
            rep = _mas_central(grafo, comp)
            if not rep or not principal:
                continue
            e = Edge(rep, principal, u"mismo documento", "estructural",
                     "", 0.1, directed=False)
            if grafo.add_edge(e):
                nuevas += 1
                log.append(u"puente estructural: «%s» ↔ «%s»"
                           % (grafo.nodes[rep].label, grafo.nodes[principal].label))
    return nuevas


def asegurar(grafo, sents, motor=None, texto="", usar_modelo=True, log=None):
    """Ejecuta la cascada completa y devuelve un informe."""
    log = log if log is not None else grafo.log
    informe = {"huerfanos_iniciales": len(grafo.orphans()),
               "componentes_iniciales": len(grafo.components())}

    informe["por_coocurrencia"] = paso_coocurrencia(grafo, sents, "sentencia", log)
    if usar_modelo:
        informe["por_modelo"] = paso_modelo(grafo, motor, log)
    else:
        informe["por_modelo"] = 0
    informe["por_fragmento"] = paso_coocurrencia(grafo, sents, "fragmento", log)
    informe["por_estructura"] = paso_estructural(grafo, log)
    informe["puentes"] = paso_componentes(grafo, motor if usar_modelo else None,
                                          texto, log)

    informe["huerfanos_finales"] = len(grafo.orphans())
    informe["componentes_finales"] = len(grafo.components())
    return informe
