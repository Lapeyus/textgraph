#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas de la maquinaria que no necesita modelo.

    python3 pruebas.py
"""

import json
import os
import sys
import xml.dom.minidom

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textgraph import analysis, exhaustive, exporters, mentions, normalize  # noqa: E402
from textgraph.chunker import chunk, find_quote, sentences                  # noqa: E402
from textgraph.llm import (MotorAntigravityCLI, MotorCodexCLI,              # noqa: E402
                           MotorGeminiCLI, parse_json)
from textgraph.local import MotorLocal                                      # noqa: E402
from textgraph.model import Edge, Graph, Node                               # noqa: E402
from textgraph.pipeline import construir                                    # noqa: E402

FALLOS = []


def check(nombre, condicion, detalle=""):
    estado = "ok  " if condicion else "FALLA"
    print("  [%s] %s%s" % (estado, nombre, ("  → %s" % detalle) if detalle and not condicion else ""))
    if not condicion:
        FALLOS.append(nombre)


TEXTO = (u"Marie Curie nació en Varsovia en 1867. Junto al Dr. Pierre Curie "
         u"descubrió el polonio (p.ej. en 1898). En 1891 Curie se trasladó a "
         u"París, donde estudió en la Sorbona.\n\nRecibió el Premio Nobel de "
         u"Física en 1903.")


def main():
    print("segmentación")
    s = sentences(TEXTO)
    check("no parte en abreviaturas", all("Dr." not in x[2] or "Pierre" in x[2] for x in s))
    check("los desplazamientos apuntan al texto real",
          all(TEXTO[a:b] == t for a, b, t in s))
    check("fragmenta con solapamiento", len(chunk(TEXTO, 90, 1)) > 1)
    check("localiza citas con espacios raros",
          find_quote(TEXTO, u"nació   en Varsovia") is not None)

    print("parseo de JSON del modelo")
    check("acepta vallado markdown", parse_json('```json\n{"a":1}\n```') == {"a": 1})
    check("tolera comas finales", parse_json('{"a":[1,2],}') == {"a": [1, 2]})
    check("ignora texto sobrante", parse_json('claro: {"b":"}"} listo') == {"b": "}"})

    print("parseo de eventos de la CLI codex")
    jl = ('{"type":"thread.started","thread_id":"x"}\n'
          'Reading prompt from stdin...\n'
          '{"type":"item.completed","item":{"id":"i0","type":"agent_message",'
          '"text":"{\\"ok\\":true}"}}\n'
          '{"type":"turn.completed","usage":{"input_tokens":12835,'
          '"cached_input_tokens":9984,"output_tokens":9}}')
    t, u, err = MotorCodexCLI._leer_eventos(jl)
    check("extrae el mensaje del agente", t == '{"ok":true}', t)
    check("extrae el uso de tokens",
          u.get("input_tokens") == 12835 and u.get("output_tokens") == 9, u)
    check("tolera líneas que no son JSON", err is None, err)
    t2, _, err2 = MotorCodexCLI._leer_eventos(
        '{"type":"turn.failed","error":{"message":"sin cupo"}}')
    check("recoge el error del turno", err2 == "sin cupo" and t2 == "", err2)

    print("parseo de la respuesta de la CLI gemini")
    env = ('{"session_id":"x","response":"{\\"ok\\":true}","stats":{"models":'
           '{"gemini-3-pro-preview":{"tokens":{"prompt":1200,"candidates":300,'
           '"thoughts":150,"cached":400,"total":1650,"tool":0}}}}}')
    t3, st3, err3 = MotorGeminiCLI._leer_respuesta("aviso previo\n" + env)
    tk = st3["models"]["gemini-3-pro-preview"]["tokens"]
    check("extrae la respuesta pese al ruido previo", t3 == '{"ok":true}', t3)
    check("extrae los tokens del modelo",
          tk["prompt"] == 1200 and tk["candidates"] == 300, st3)
    check("sin error en la respuesta buena", err3 is None, err3)
    t4, _, err4 = MotorGeminiCLI._leer_respuesta(
        '{"error":{"type":"AuthError","message":"sin sesión","code":41}}')
    check("recoge el error del sobre JSON", err4 == "sin sesión" and t4 == "", err4)

    print("parseo de la respuesta de la CLI antigravity")
    env2 = ('{"conversation_id":"c1","status":"SUCCESS","response":"{\\"ok\\":3}\\n",'
            '"num_turns":1,"usage":{"input_tokens":13735,"output_tokens":63,'
            '"thinking_tokens":58,"cache_read_tokens":0,"total_tokens":13798}}')
    t5, u5, err5 = MotorAntigravityCLI._leer_respuesta(env2)
    check("extrae la respuesta", t5.strip() == '{"ok":3}', t5)
    check("extrae el uso de tokens",
          u5.get("input_tokens") == 13735 and u5.get("output_tokens") == 63, u5)
    check("sin error si el estado es SUCCESS", err5 is None, err5)
    t6, _, err6 = MotorAntigravityCLI._leer_respuesta(
        '{"conversation_id":"","status":"ERROR","response":"",'
        '"error":"modelo desconocido"}')
    check("recoge el error del estado", err6 == "modelo desconocido" and t6 == "", err6)

    print("resolución de entidades")
    g = Graph()
    for i, (l, t) in enumerate([("Marie Curie", "PERSONA"), ("Curie", "PERSONA"),
                                ("la Universidad de París", "ORGANIZACION"),
                                ("Universidad de Paris", "ORGANIZACION"),
                                ("Organización de las Naciones Unidas", "ORGANIZACION"),
                                ("ONU", "ORGANIZACION")]):
        g.add_node(Node(str(i), l, t))
    for i in range(5):
        g.add_edge(Edge(str(i), str(i + 1), "r"))
    normalize.resolver(g, log=[])
    check("fusiona apellido, acentos y siglas", len(g.nodes) == 3,
          [n.label for n in g.nodes.values()])

    print("índice de menciones")
    g2 = Graph(text=TEXTO)
    g2.add_node(Node("mc", "Marie Curie", "PERSONA", aliases=["Curie"]))
    g2.add_node(Node("pc", "Pierre Curie", "PERSONA"))
    mentions.indexar(g2, TEXTO)
    mc = g2.nodes["mc"].mentions
    check("encuentra etiqueta y alias", len(mc) == 2, len(mc))
    check("las citas coinciden con el texto",
          all(TEXTO[m["start"]:m["end"]] == m["quote"] for m in mc))
    check("la forma larga gana a la corta",
          all(m["quote"] != "Curie" or m["start"] > 100 for m in g2.nodes["pc"].mentions))

    print("exhaustividad")
    g3 = Graph(text=TEXTO)
    g3.add_node(Node("a", "Marie Curie", "PERSONA"))
    g3.add_node(Node("b", "Varsovia", "LUGAR"))
    g3.add_node(Node("c", "Sorbona", "ORGANIZACION"))   # quedará suelto
    g3.add_edge(Edge("a", "b", "nació en"))
    sents = mentions.indexar(g3, TEXTO)
    analysis.calcular(g3)
    informe = exhaustive.asegurar(g3, sents, None, TEXTO, usar_modelo=False, log=[])
    check("no deja nodos sueltos", informe["huerfanos_finales"] == 0, informe)
    check("deja un solo componente", informe["componentes_finales"] == 1, informe)

    print("métricas")
    g4 = Graph()
    for l in "abcdefgh":
        g4.add_node(Node(l, l.upper()))
    for x, y in [("a", "b"), ("b", "c"), ("a", "c"), ("c", "d"), ("d", "e"),
                 ("e", "f"), ("d", "f"), ("f", "g"), ("g", "h"), ("h", "f")]:
        g4.add_edge(Edge(x, y, "r"))
    analysis.calcular(g4)
    check("detecta más de una comunidad", g4.meta["comunidades"] > 1)
    check("los puentes tienen intermediación alta",
          g4.nodes["c"].metrics["intermediacion"] > g4.nodes["a"].metrics["intermediacion"])

    print("tubería completa con el motor local")
    g5 = construir(TEXTO, titulo="Prueba", motor=MotorLocal(), exhaustividad=False)
    st = g5.to_dict()["stats"]
    check("produce nodos y relaciones", st["nodos"] > 5 and st["aristas"] > 4, st)
    check("el grafo queda conexo y sin sueltos",
          st["componentes"] == 1 and st["huerfanos"] == 0, st)

    print("exportadores")
    web = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    for fmt, _, _, _, _ in exporters.FORMATOS:
        datos, tipo, ext = exporters.exportar(g5, fmt, web)
        check("exporta %s" % fmt, len(datos) > 40)
        if fmt in ("graphml", "gexf"):
            try:
                xml.dom.minidom.parseString(datos)
                check("%s es XML válido" % fmt, True)
            except Exception as e:
                check("%s es XML válido" % fmt, False, e)
        if fmt in ("json", "jsonld"):
            try:
                json.loads(datos.decode("utf-8"))
                check("%s es JSON válido" % fmt, True)
            except Exception as e:
                check("%s es JSON válido" % fmt, False, e)

    print("ida y vuelta de serialización")
    d = g5.to_dict()
    g6 = Graph.from_dict(d)
    check("conserva nodos y aristas",
          len(g6.nodes) == len(g5.nodes) and len(g6.edges) == len(g5.edges))

    print()
    if FALLOS:
        print("%d prueba(s) fallidas: %s" % (len(FALLOS), ", ".join(FALLOS)))
        return 1
    print("todas las pruebas pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
