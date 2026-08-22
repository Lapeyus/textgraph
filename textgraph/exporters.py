# -*- coding: utf-8 -*-
"""Exportadores a formatos abiertos de grafos."""

import io
import json
import os
import re
import csv as _csv

from .model import slug

FORMATOS = [
    ("json", "JSON nativo", "application/json", ".json",
     u"Grafo completo con evidencias y métricas"),
    ("graphml", "GraphML", "application/xml", ".graphml",
     u"Gephi, yEd, Cytoscape, NetworkX"),
    ("gexf", "GEXF", "application/xml", ".gexf", u"Gephi"),
    ("csv-nodes", "CSV de nodos", "text/csv", ".nodes.csv", u"Hojas de cálculo, Gephi"),
    ("csv-edges", "CSV de aristas", "text/csv", ".edges.csv", u"Hojas de cálculo, Gephi"),
    ("cypher", "Cypher", "text/plain", ".cypher", u"Importar en Neo4j"),
    ("dot", "DOT", "text/vnd.graphviz", ".dot", u"Graphviz"),
    ("mermaid", "Mermaid", "text/plain", ".mmd", u"Markdown, Obsidian, docs"),
    ("turtle", "RDF Turtle", "text/turtle", ".ttl", u"Web semántica, SPARQL"),
    ("jsonld", "JSON-LD", "application/ld+json", ".jsonld", u"Datos enlazados"),
    ("llm", "Paquete para LLM", "text/markdown", ".llm.md",
     u"Markdown compacto para analizar con otro modelo"),
    ("html", "HTML autónomo", "text/html", ".html",
     u"Visor interactivo en un solo archivo"),
]


def exportar(grafo, formato, web_dir=None):
    """Devuelve (bytes, mimetype, extension)."""
    tabla = {f[0]: f for f in FORMATOS}
    if formato not in tabla:
        raise ValueError("formato desconocido: %s" % formato)
    fn = globals()["_" + formato.replace("-", "_")]
    contenido = fn(grafo, web_dir) if formato == "html" else fn(grafo)
    if isinstance(contenido, str):
        contenido = contenido.encode("utf-8")
    return contenido, tabla[formato][2], tabla[formato][3]


# ------------------------------------------------------------------ helpers
def _esc_xml(t):
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def _n(grafo, nid):
    n = grafo.nodes.get(nid)
    return n.label if n else nid


# ------------------------------------------------------------------ formatos
def _json(grafo):
    return json.dumps(grafo.to_dict(), ensure_ascii=False, indent=2)


def _graphml(grafo):
    o = io.StringIO()
    o.write('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"\n'
            '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
            '  xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns '
            'http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">\n')
    claves_n = [("label", "string"), ("tipo", "string"), ("descripcion", "string"),
                ("aliases", "string"), ("menciones", "int"), ("grado", "int"),
                ("pagerank", "double"), ("comunidad", "int")]
    claves_e = [("label", "string"), ("tipo", "string"), ("evidencia", "string"),
                ("confianza", "double")]
    for k, t in claves_n:
        o.write('  <key id="n_%s" for="node" attr.name="%s" attr.type="%s"/>\n' % (k, k, t))
    for k, t in claves_e:
        o.write('  <key id="e_%s" for="edge" attr.name="%s" attr.type="%s"/>\n' % (k, k, t))
    o.write('  <graph id="G" edgedefault="directed">\n')
    for n in grafo.nodes.values():
        m = n.metrics or {}
        o.write('    <node id="%s">\n' % _esc_xml(n.id))
        for k, v in (("label", n.label), ("tipo", n.type), ("descripcion", n.description),
                     ("aliases", "; ".join(n.aliases)), ("menciones", len(n.mentions)),
                     ("grado", m.get("grado", 0)), ("pagerank", m.get("pagerank", 0)),
                     ("comunidad", m.get("comunidad", 0))):
            o.write('      <data key="n_%s">%s</data>\n' % (k, _esc_xml(v)))
        o.write('    </node>\n')
    for i, e in enumerate(grafo.edges.values()):
        o.write('    <edge id="e%d" source="%s" target="%s">\n'
                % (i, _esc_xml(e.source), _esc_xml(e.target)))
        for k, v in (("label", e.label), ("tipo", e.type), ("evidencia", e.evidence),
                     ("confianza", e.confidence)):
            o.write('      <data key="e_%s">%s</data>\n' % (k, _esc_xml(v)))
        o.write('    </edge>\n')
    o.write('  </graph>\n</graphml>\n')
    return o.getvalue()


def _gexf(grafo):
    o = io.StringIO()
    o.write('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gexf xmlns="http://www.gexf.net/1.2draft" version="1.2">\n'
            '  <meta><description>%s</description></meta>\n'
            '  <graph mode="static" defaultedgetype="directed">\n'
            % _esc_xml(grafo.title))
    o.write('    <attributes class="node">\n'
            '      <attribute id="0" title="tipo" type="string"/>\n'
            '      <attribute id="1" title="descripcion" type="string"/>\n'
            '      <attribute id="2" title="comunidad" type="integer"/>\n'
            '      <attribute id="3" title="pagerank" type="float"/>\n'
            '    </attributes>\n')
    o.write('    <attributes class="edge">\n'
            '      <attribute id="0" title="tipo" type="string"/>\n'
            '      <attribute id="1" title="evidencia" type="string"/>\n'
            '    </attributes>\n')
    o.write('    <nodes>\n')
    for n in grafo.nodes.values():
        m = n.metrics or {}
        o.write('      <node id="%s" label="%s">\n        <attvalues>\n'
                '          <attvalue for="0" value="%s"/>\n'
                '          <attvalue for="1" value="%s"/>\n'
                '          <attvalue for="2" value="%s"/>\n'
                '          <attvalue for="3" value="%s"/>\n'
                '        </attvalues>\n      </node>\n'
                % (_esc_xml(n.id), _esc_xml(n.label), _esc_xml(n.type),
                   _esc_xml(n.description), m.get("comunidad", 0), m.get("pagerank", 0)))
    o.write('    </nodes>\n    <edges>\n')
    for i, e in enumerate(grafo.edges.values()):
        o.write('      <edge id="%d" source="%s" target="%s" label="%s">\n'
                '        <attvalues>\n'
                '          <attvalue for="0" value="%s"/>\n'
                '          <attvalue for="1" value="%s"/>\n'
                '        </attvalues>\n      </edge>\n'
                % (i, _esc_xml(e.source), _esc_xml(e.target), _esc_xml(e.label),
                   _esc_xml(e.type), _esc_xml(e.evidence)))
    o.write('    </edges>\n  </graph>\n</gexf>\n')
    return o.getvalue()


def _csv_nodes(grafo):
    o = io.StringIO()
    w = _csv.writer(o)
    w.writerow(["Id", "Label", "Tipo", "Descripcion", "Aliases", "Menciones",
                "Grado", "PageRank", "Intermediacion", "Comunidad"])
    for n in grafo.nodes.values():
        m = n.metrics or {}
        w.writerow([n.id, n.label, n.type, n.description, "; ".join(n.aliases),
                    len(n.mentions), m.get("grado", 0), m.get("pagerank", 0),
                    m.get("intermediacion", 0), m.get("comunidad", 0)])
    return o.getvalue()


def _csv_edges(grafo):
    o = io.StringIO()
    w = _csv.writer(o)
    w.writerow(["Source", "Target", "Label", "Type", "Tipo_relacion",
                "Evidencia", "Confianza", "Source_label", "Target_label"])
    for e in grafo.edges.values():
        w.writerow([e.source, e.target, e.label,
                    "Directed" if e.directed else "Undirected", e.type,
                    e.evidence, e.confidence, _n(grafo, e.source), _n(grafo, e.target)])
    return o.getvalue()


def _cypher(grafo):
    o = io.StringIO()
    o.write("// %s — generado por textgraph\n" % grafo.title)
    o.write("// Ejecutar en Neo4j Browser o cypher-shell\n\n")
    o.write("CREATE CONSTRAINT entidad_id IF NOT EXISTS "
            "FOR (e:Entidad) REQUIRE e.id IS UNIQUE;\n\n")
    for n in grafo.nodes.values():
        m = n.metrics or {}
        o.write("MERGE (n:Entidad:%s {id:%s}) SET n.label=%s, n.descripcion=%s, "
                "n.aliases=%s, n.grado=%d, n.pagerank=%s, n.comunidad=%d;\n"
                % (n.type.capitalize(), _cy(n.id), _cy(n.label), _cy(n.description),
                   json.dumps(n.aliases, ensure_ascii=False), m.get("grado", 0),
                   m.get("pagerank", 0), m.get("comunidad", 0)))
    o.write("\n")
    for e in grafo.edges.values():
        rel = re.sub(r"[^A-Z0-9_]", "", slug(e.label).upper()) or "RELACIONADO_CON"
        o.write("MATCH (a:Entidad {id:%s}), (b:Entidad {id:%s}) "
                "MERGE (a)-[r:%s]->(b) SET r.label=%s, r.tipo=%s, r.evidencia=%s, "
                "r.confianza=%s;\n"
                % (_cy(e.source), _cy(e.target), rel, _cy(e.label), _cy(e.type),
                   _cy(e.evidence), e.confidence))
    return o.getvalue()


def _cy(v):
    return json.dumps(str(v or ""), ensure_ascii=False)


def _dot(grafo):
    colores = {"PERSONA": "#e8743b", "ORGANIZACION": "#19a979", "LUGAR": "#1f77b4",
               "TIEMPO": "#945ecf", "EVENTO": "#e6444c", "OBRA": "#c8a032",
               "CONCEPTO": "#13a4b4", "OBJETO": "#6c8893", "MAGNITUD": "#bf399e",
               "PROCESO": "#f5a623", "DISCIPLINA": "#4e79a7", "OTRO": "#9aa0a6"}
    o = io.StringIO()
    o.write('digraph "%s" {\n  graph [overlap=false, splines=true, bgcolor="white"];\n'
            '  node [shape=box, style="rounded,filled", fontname="Helvetica", '
            'fontsize=10, color="#00000000", fontcolor="white"];\n'
            '  edge [fontname="Helvetica", fontsize=8, color="#888888"];\n'
            % grafo.title.replace('"', "'"))
    for n in grafo.nodes.values():
        o.write('  "%s" [label="%s", fillcolor="%s"];\n'
                % (n.id, n.label.replace('"', "'"), colores.get(n.type, "#9aa0a6")))
    estilos = {"explicita": "solid", "implicita": "dashed",
               "coocurrencia": "dotted", "estructural": "dotted"}
    for e in grafo.edges.values():
        o.write('  "%s" -> "%s" [label="%s", style=%s];\n'
                % (e.source, e.target, e.label.replace('"', "'"),
                   estilos.get(e.type, "solid")))
    o.write("}\n")
    return o.getvalue()


def _mermaid(grafo):
    o = io.StringIO()
    o.write("graph LR\n")
    ids = {}
    for i, n in enumerate(grafo.nodes.values()):
        ids[n.id] = "N%d" % i
        etiqueta = n.label.replace('"', "'")
        o.write('  %s["%s"]\n' % (ids[n.id], etiqueta))
    for e in grafo.edges.values():
        flecha = "-->" if e.type == "explicita" else "-.->"
        o.write('  %s %s|"%s"| %s\n'
                % (ids.get(e.source, "?"), flecha, e.label.replace('"', "'"),
                   ids.get(e.target, "?")))
    tipos = {}
    for n in grafo.nodes.values():
        tipos.setdefault(n.type, []).append(ids[n.id])
    colores = {"PERSONA": "#e8743b", "ORGANIZACION": "#19a979", "LUGAR": "#1f77b4",
               "TIEMPO": "#945ecf", "EVENTO": "#e6444c", "OBRA": "#c8a032",
               "CONCEPTO": "#13a4b4"}
    for t, lst in tipos.items():
        if t in colores:
            o.write("  classDef %s fill:%s,stroke:#333,color:#fff;\n" % (t, colores[t]))
            o.write("  class %s %s;\n" % (",".join(lst), t))
    return o.getvalue()


def _turtle(grafo):
    o = io.StringIO()
    o.write("@prefix tg: <urn:textgraph:> .\n"
            "@prefix ent: <urn:textgraph:entidad/> .\n"
            "@prefix rel: <urn:textgraph:relacion/> .\n"
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n")
    o.write('tg:documento a tg:Documento ; rdfs:label %s .\n\n' % _ttl(grafo.title))
    for n in grafo.nodes.values():
        o.write("ent:%s a tg:%s ;\n  rdfs:label %s ;\n"
                % (n.id, n.type.capitalize(), _ttl(n.label)))
        if n.description:
            o.write("  rdfs:comment %s ;\n" % _ttl(n.description))
        for a in n.aliases:
            o.write("  tg:alias %s ;\n" % _ttl(a))
        o.write("  tg:menciones %d .\n\n" % len(n.mentions))
    for i, e in enumerate(grafo.edges.values()):
        p = slug(e.label) or "relacionado_con"
        o.write("ent:%s rel:%s ent:%s .\n" % (e.source, p, e.target))
        o.write("_:s%d a rdf:Statement ;\n  rdf:subject ent:%s ;\n  rdf:predicate rel:%s ;\n"
                "  rdf:object ent:%s ;\n  rdfs:label %s ;\n  tg:tipo %s ;\n"
                "  tg:confianza %s ;\n  tg:evidencia %s .\n\n"
                % (i, e.source, p, e.target, _ttl(e.label), _ttl(e.type),
                   '"%s"^^xsd:decimal' % e.confidence, _ttl(e.evidence)))
    return o.getvalue()


def _ttl(v):
    return json.dumps(str(v or ""), ensure_ascii=False)


def _jsonld(grafo):
    doc = {
        "@context": {
            "tg": "urn:textgraph:",
            "label": "http://www.w3.org/2000/01/rdf-schema#label",
            "description": "http://www.w3.org/2000/01/rdf-schema#comment",
            "alias": "tg:alias", "relations": "tg:relacion",
            "source": "tg:origen", "target": "tg:destino",
            "evidence": "tg:evidencia", "confidence": "tg:confianza",
        },
        "@id": "urn:textgraph:documento",
        "title": grafo.title,
        "@graph": [],
    }
    for n in grafo.nodes.values():
        doc["@graph"].append({
            "@id": "urn:textgraph:entidad/" + n.id,
            "@type": "tg:" + n.type.capitalize(),
            "label": n.label, "description": n.description, "alias": n.aliases,
            "tg:metricas": n.metrics,
        })
    doc["relations"] = [{
        "@type": "tg:Relacion",
        "source": "urn:textgraph:entidad/" + e.source,
        "target": "urn:textgraph:entidad/" + e.target,
        "label": e.label, "tg:tipo": e.type,
        "evidence": e.evidence, "confidence": e.confidence,
    } for e in grafo.edges.values()]
    return json.dumps(doc, ensure_ascii=False, indent=2)


def _llm(grafo):
    """Markdown compacto pensado para que otro modelo razone sobre el grafo."""
    d = grafo.to_dict()
    st = d["stats"]
    o = io.StringIO()
    o.write(u"# Grafo de conocimiento: %s\n\n" % grafo.title)
    o.write(u"Extraído automáticamente del texto fuente. %d entidades, %d relaciones, "
            u"%d componente(s), %d entidad(es) sin conectar.\n\n"
            % (st["nodos"], st["aristas"], st["componentes"], st["huerfanos"]))

    o.write(u"## Entidades por tipo\n\n")
    por_tipo = {}
    for n in grafo.nodes.values():
        por_tipo.setdefault(n.type, []).append(n)
    for tipo in sorted(por_tipo, key=lambda t: -len(por_tipo[t])):
        o.write(u"### %s (%d)\n" % (tipo, len(por_tipo[tipo])))
        for n in sorted(por_tipo[tipo], key=lambda x: -(x.metrics or {}).get("grado", 0)):
            alias = (u" [también: %s]" % "; ".join(n.aliases)) if n.aliases else ""
            desc = (u" — %s" % n.description) if n.description else ""
            o.write(u"- **%s**%s%s (grado %d, menciones %d)\n"
                    % (n.label, alias, desc, (n.metrics or {}).get("grado", 0),
                       len(n.mentions)))
        o.write(u"\n")

    o.write(u"## Relaciones (tripletas)\n\n")
    o.write(u"Formato: `origen --[predicado]--> destino` · tipo · evidencia textual\n\n")
    for e in sorted(grafo.edges.values(), key=lambda x: -x.confidence):
        ev = (u' · "%s"' % " ".join(e.evidence.split())[:160]) if e.evidence else ""
        o.write(u"- `%s --[%s]--> %s` · %s%s\n"
                % (_n(grafo, e.source), e.label, _n(grafo, e.target), e.type, ev))

    o.write(u"\n## Vecindario de las entidades centrales\n\n")
    centrales = sorted(grafo.nodes.values(),
                       key=lambda n: -(n.metrics or {}).get("grado", 0))[:10]
    for n in centrales:
        vecinos = []
        for e in grafo.edges.values():
            if e.source == n.id:
                vecinos.append(u"%s %s" % (e.label, _n(grafo, e.target)))
            elif e.target == n.id:
                vecinos.append(u"←%s %s" % (e.label, _n(grafo, e.source)))
        o.write(u"- **%s**: %s\n" % (n.label, "; ".join(vecinos[:20])))

    o.write(u"\n## Cómo leer los tipos de relación\n\n"
            u"- `explicita`: afirmada literalmente en el texto.\n"
            u"- `implicita`: deducida del texto (correferencia o contexto).\n"
            u"- `coocurrencia`: las entidades comparten oración, sin predicado explícito.\n"
            u"- `estructural`: enlace de último recurso para garantizar que ninguna "
            u"entidad quede aislada; el vínculo semántico es débil.\n")
    return o.getvalue()


def _html(grafo, web_dir=None):
    """Visor interactivo autónomo (un solo archivo, sin conexión)."""
    web_dir = web_dir or os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web")
    def leer(nombre):
        with open(os.path.join(web_dir, nombre), encoding="utf-8") as f:
            return f.read()
    html = leer("index.html")
    css = leer("style.css")
    js = leer("app.js")
    vis = leer(os.path.join("vendor", "vis-network.min.js"))
    datos = json.dumps(grafo.to_dict(), ensure_ascii=False)

    html = html.replace('<link rel="stylesheet" href="style.css">',
                        "<style>\n%s\n</style>" % css)
    html = html.replace('<script src="vendor/vis-network.min.js"></script>',
                        "<script>\n%s\n</script>" % vis)
    html = html.replace('<script src="app.js"></script>',
                        "<script>\nwindow.GRAFO_EMBEBIDO = %s;\n</script>\n<script>\n%s\n</script>"
                        % (datos, js))
    return html
