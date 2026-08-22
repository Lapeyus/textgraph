# -*- coding: utf-8 -*-
"""Orquestación: texto -> grafo de conocimiento exhaustivo."""

import concurrent.futures
import re
import time

from . import analysis, exhaustive, mentions, normalize
from .chunker import chunk, find_quote
from .llm import crear_motor
from .model import Edge, Graph, Node, TIPOS_ENTIDAD, slug

ARTICULO_INICIAL = re.compile(r"^(el|la|los|las|un|una|unos|unas|lo|the|a|an)\s+", re.I)


def _limpia_label(txt):
    t = " ".join(str(txt or "").split()).strip(" .,;:")
    t = t.strip(u"«»\"'“”")
    # quita artículo inicial solo si va en minúscula ("la Sorbona" -> "Sorbona")
    m = ARTICULO_INICIAL.match(t)
    if m and m.group(1).islower() and len(t.split()) > 1:
        t = t[m.end():]
    return t.strip()


def _tipo(txt):
    t = str(txt or "").strip().upper()
    t = {"ORGANIZACIÓN": "ORGANIZACION", "FECHA": "TIEMPO", "LOCATION": "LUGAR",
         "PERSON": "PERSONA", "ORG": "ORGANIZACION", "DATE": "TIEMPO",
         "EVENT": "EVENTO", "WORK": "OBRA", "CONCEPT": "CONCEPTO",
         "OBJECT": "OBJETO", "QUANTITY": "MAGNITUD", "PROCESS": "PROCESO",
         "DISCIPLINE": "DISCIPLINA", "MAGNITUDE": "MAGNITUD"}.get(t, t)
    return t if t in TIPOS_ENTIDAD else "OTRO"


def _nid(label):
    return slug(normalize.clave(label)) or slug(label)


def construir(texto, titulo="", engine="auto", modelo=None, max_chars=3500,
              overlap=2, exhaustividad=True, fusion_llm=False, progreso=None,
              motor=None, paralelo=2):
    """Devuelve un `Graph` construido a partir del texto."""
    t0 = time.time()
    aviso = progreso or (lambda **kw: None)
    motor = motor or crear_motor(engine, modelo)
    grafo = Graph(titulo or _titulo(texto), texto)
    grafo.meta.update({"motor": getattr(motor, "nombre", "?"),
                       "modelo": getattr(motor, "modelo", "?"),
                       "caracteres": len(texto), "paralelo": paralelo})

    fragmentos = chunk(texto, max_chars, overlap)
    total = len(fragmentos) or 1
    aviso(fase="fragmentar", mensaje=u"Texto dividido en %d fragmento(s)" % total,
          hecho=0, total=total + 4)

    # Los fragmentos se procesan en oleadas: dentro de cada oleada las llamadas
    # van en paralelo, y entre oleadas se pasa al modelo la lista de entidades
    # ya conocidas para que reutilice las mismas etiquetas.
    paralelo = max(1, int(paralelo or 1))
    labels_previos = []
    hechos = 0
    for inicio in range(0, len(fragmentos), paralelo):
        oleada = fragmentos[inicio:inicio + paralelo]
        aviso(fase="extraer", mensaje=u"Extrayendo entidades y relaciones (%d-%d/%d)"
              % (oleada[0]["i"] + 1, oleada[-1]["i"] + 1, total),
              hecho=hechos, total=total + 4)
        resultados = [None] * len(oleada)
        if len(oleada) == 1:
            try:
                resultados[0] = motor.extraer_fragmento(oleada[0]["text"], labels_previos)
            except Exception as e:
                grafo.log.append(u"error en el fragmento %d: %s" % (oleada[0]["i"] + 1, e))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(oleada)) as pool:
                futuros = {pool.submit(motor.extraer_fragmento, f["text"],
                                       labels_previos): k
                           for k, f in enumerate(oleada)}
                for fut in concurrent.futures.as_completed(futuros):
                    k = futuros[fut]
                    try:
                        resultados[k] = fut.result()
                    except Exception as e:
                        grafo.log.append(u"error en el fragmento %d: %s"
                                         % (oleada[k]["i"] + 1, e))
        for k, f in enumerate(oleada):
            if resultados[k]:
                _ingerir(grafo, resultados[k], f, texto)
        hechos += len(oleada)
        labels_previos = [n.label for n in grafo.nodes.values()][:200]

    aviso(fase="fusionar", mensaje=u"Resolviendo variantes de la misma entidad",
          hecho=total, total=total + 4)
    normalize.resolver(grafo, motor=motor, usar_llm=fusion_llm, log=grafo.log)

    aviso(fase="indexar", mensaje=u"Localizando menciones en el texto",
          hecho=total + 1, total=total + 4)
    sents = mentions.indexar(grafo, texto)
    analysis.calcular(grafo)

    aviso(fase="exhaustividad", mensaje=u"Conectando entidades sueltas",
          hecho=total + 2, total=total + 4)
    informe = exhaustive.asegurar(grafo, sents, motor, texto,
                                  usar_modelo=exhaustividad, log=grafo.log)
    grafo.meta["exhaustividad"] = informe

    aviso(fase="metricas", mensaje=u"Calculando métricas de red",
          hecho=total + 3, total=total + 4)
    analysis.calcular(grafo)

    grafo.meta["segundos"] = round(time.time() - t0, 1)
    grafo.meta["uso"] = motor.resumen()
    aviso(fase="listo", mensaje=u"Grafo listo: %d nodos, %d relaciones"
          % (len(grafo.nodes), len(grafo.edges)), hecho=total + 4, total=total + 4)
    return grafo


def _titulo(texto):
    for linea in texto.strip().splitlines():
        linea = linea.strip(" #*").strip()
        if linea:
            return linea[:70]
    return u"Documento sin título"


def _ingerir(grafo, datos, fragmento, texto_completo):
    """Vuelca el JSON de un fragmento en el grafo."""
    i = fragmento["i"]
    locales = {}

    for ent in datos.get("entidades", []):
        if not isinstance(ent, dict):
            continue
        label = _limpia_label(ent.get("label"))
        if not label or len(label) > 120:
            continue
        nid = _nid(label)
        if not nid:
            continue
        nodo = Node(nid, label, _tipo(ent.get("tipo")),
                    [_limpia_label(a) for a in (ent.get("aliases") or [])
                     if isinstance(a, str)],
                    str(ent.get("descripcion") or "")[:300], chunks={i})
        ev = ent.get("evidencia")
        pos = find_quote(texto_completo, ev) if ev else None
        if pos:
            nodo.mentions.append({"start": pos[0], "end": pos[1],
                                  "quote": texto_completo[pos[0]:pos[1]],
                                  "sentencia": None, "contexto": ""})
        nodo = grafo.add_node(nodo)
        locales[label.lower()] = nodo.id
        for a in nodo.aliases:
            locales.setdefault(a.lower(), nodo.id)

    def resolver_ref(ref):
        ref = _limpia_label(ref)
        if not ref:
            return None
        if ref.lower() in locales:
            return locales[ref.lower()]
        n = grafo.node_by_label(ref)
        if n:
            return n.id
        nid = _nid(ref)
        if nid in grafo.nodes:
            return nid
        # el modelo citó una entidad que no listó: la creamos (nada se pierde)
        if len(ref) > 120:
            return None
        nuevo = grafo.add_node(Node(nid, ref, "OTRO", chunks={i}))
        grafo.log.append(u"entidad recuperada de una relación: «%s»" % ref)
        return nuevo.id

    for rel in datos.get("relaciones", []):
        if not isinstance(rel, dict):
            continue
        a = resolver_ref(rel.get("origen"))
        b = resolver_ref(rel.get("destino"))
        if not a or not b or a == b:
            continue
        tipo = str(rel.get("tipo") or "explicita").lower()
        if tipo not in ("explicita", "implicita", "coocurrencia", "estructural"):
            tipo = "explicita"
        try:
            conf = float(rel.get("confianza"))
        except (TypeError, ValueError):
            conf = 0.8
        ev = str(rel.get("evidencia") or "")
        pos = find_quote(texto_completo, ev)
        grafo.add_edge(Edge(a, b, normalize.predicado(rel.get("etiqueta")), tipo,
                            texto_completo[pos[0]:pos[1]] if pos else ev,
                            max(0.0, min(1.0, conf)), chunks={i}))
