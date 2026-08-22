# -*- coding: utf-8 -*-
"""Métricas de red para interpretar el grafo (grado, PageRank, comunidades)."""

import collections


def calcular(grafo):
    adj = grafo.adjacency()
    n = len(adj)
    if n == 0:
        return
    pr = pagerank(adj)
    btw = intermediacion(adj)
    com = comunidades(adj)
    maxpr = max(pr.values()) or 1.0
    maxbtw = max(btw.values()) or 1.0
    for nid, nodo in grafo.nodes.items():
        nodo.metrics = {
            "grado": len(adj[nid]),
            "pagerank": round(pr[nid], 5),
            "pagerank_rel": round(pr[nid] / maxpr, 4),
            "intermediacion": round(btw[nid], 4),
            "intermediacion_rel": round(btw[nid] / maxbtw, 4),
            "comunidad": com[nid],
            "menciones": len(nodo.mentions),
        }
    grafo.meta["comunidades"] = len(set(com.values()))


def pagerank(adj, d=0.85, iteraciones=60, tol=1e-8):
    n = len(adj)
    pr = {k: 1.0 / n for k in adj}
    colgantes = [k for k, v in adj.items() if not v]
    for _ in range(iteraciones):
        nuevo = {}
        fuga = sum(pr[k] for k in colgantes) / n
        for k in adj:
            s = sum(pr[v] / len(adj[v]) for v in adj[k] if adj[v])
            nuevo[k] = (1 - d) / n + d * (s + fuga)
        dif = sum(abs(nuevo[k] - pr[k]) for k in adj)
        pr = nuevo
        if dif < tol:
            break
    return pr


def intermediacion(adj):
    """Betweenness de Brandes, no ponderada y normalizada."""
    cb = {k: 0.0 for k in adj}
    for s in adj:
        pila, pred = [], {k: [] for k in adj}
        sigma = {k: 0.0 for k in adj}
        dist = {k: -1 for k in adj}
        sigma[s], dist[s] = 1.0, 0
        cola = collections.deque([s])
        while cola:
            v = cola.popleft()
            pila.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    cola.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = {k: 0.0 for k in adj}
        while pila:
            w = pila.pop()
            for v in pred[w]:
                if sigma[w]:
                    delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != s:
                cb[w] += delta[w]
    n = len(adj)
    if n > 2:
        escala = 1.0 / ((n - 1) * (n - 2))
        for k in cb:
            cb[k] *= escala
    return cb


def comunidades(adj, iteraciones=30):
    """Comunidades por modularidad (movimiento local tipo Louvain, nivel 1).

    Determinista: recorre los nodos en orden estable, así el mismo grafo
    produce siempre los mismos colores.
    """
    m2 = sum(len(v) for v in adj.values())  # = 2m
    if m2 == 0:
        return {k: i for i, k in enumerate(sorted(adj))}
    com = {k: k for k in adj}
    tot = {k: float(len(adj[k])) for k in adj}   # grados totales por comunidad
    orden = sorted(adj, key=lambda k: (-len(adj[k]), k))

    for _ in range(iteraciones):
        movidos = 0
        for v in orden:
            ki = float(len(adj[v]))
            if not ki:
                continue
            actual = com[v]
            tot[actual] -= ki
            pesos = collections.Counter()
            for w in adj[v]:
                pesos[com[w]] += 1
            pesos.setdefault(actual, 0)
            mejor, mejor_gain = actual, None
            for c, kin in sorted(pesos.items(), key=lambda kv: (-kv[1], str(kv[0]))):
                gain = kin - tot.get(c, 0.0) * ki / m2
                if mejor_gain is None or gain > mejor_gain + 1e-12:
                    mejor, mejor_gain = c, gain
            com[v] = mejor
            tot[mejor] = tot.get(mejor, 0.0) + ki
            if mejor != actual:
                movidos += 1
        if not movidos:
            break

    # nodos aislados: comunidad propia
    tam = collections.Counter(com.values())
    mapa = {e: i for i, (e, _) in enumerate(
        sorted(tam.items(), key=lambda kv: (-kv[1], str(kv[0]))))}
    return {k: mapa[v] for k, v in com.items()}
