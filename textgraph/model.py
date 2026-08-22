"""Modelo de datos del grafo de conocimiento."""

import re
import unicodedata


TIPOS_ENTIDAD = [
    "PERSONA", "ORGANIZACION", "LUGAR", "TIEMPO", "EVENTO", "OBRA",
    "CONCEPTO", "OBJETO", "MAGNITUD", "PROCESO", "DISCIPLINA", "OTRO",
]

# Tipos de arista, de mayor a menor respaldo textual.
TIPOS_RELACION = ["explicita", "implicita", "coocurrencia", "estructural"]


def slug(texto, maxlen=64):
    """Identificador estable a partir de una etiqueta."""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return (t or "n")[:maxlen]


class Node:
    __slots__ = ("id", "label", "type", "aliases", "description",
                 "mentions", "chunks", "metrics")

    def __init__(self, id, label, type="OTRO", aliases=None, description="",
                 mentions=None, chunks=None, metrics=None):
        self.id = id
        self.label = label
        self.type = type if type in TIPOS_ENTIDAD else "OTRO"
        self.aliases = list(aliases or [])
        self.description = description or ""
        # mentions: [{"quote": str, "chunk": int, "start": int, "end": int}]
        self.mentions = list(mentions or [])
        self.chunks = set(chunks or [])
        self.metrics = dict(metrics or {})

    def add_alias(self, alias):
        if not alias:
            return
        alias = alias.strip()
        low = {a.lower() for a in self.aliases} | {self.label.lower()}
        if alias and alias.lower() not in low:
            self.aliases.append(alias)

    def to_dict(self):
        return {
            "id": self.id, "label": self.label, "type": self.type,
            "aliases": self.aliases, "description": self.description,
            "mentions": self.mentions, "chunks": sorted(self.chunks),
            "metrics": self.metrics,
        }

    @staticmethod
    def from_dict(d):
        return Node(d["id"], d["label"], d.get("type", "OTRO"),
                    d.get("aliases"), d.get("description"), d.get("mentions"),
                    d.get("chunks"), d.get("metrics"))


class Edge:
    __slots__ = ("id", "source", "target", "label", "type", "evidence",
                 "confidence", "directed", "chunks")

    def __init__(self, source, target, label, type="explicita", evidence="",
                 confidence=0.8, directed=True, chunks=None, id=None):
        self.source = source
        self.target = target
        self.label = (label or "relacionado con").strip()
        self.type = type if type in TIPOS_RELACION else "explicita"
        self.evidence = evidence or ""
        self.confidence = float(confidence)
        self.directed = bool(directed)
        self.chunks = set(chunks or [])
        self.id = id or "e_%s__%s__%s" % (source, slug(self.label, 32), target)

    def key(self):
        return (self.source, self.target, self.label.lower())

    def to_dict(self):
        return {
            "id": self.id, "source": self.source, "target": self.target,
            "label": self.label, "type": self.type, "evidence": self.evidence,
            "confidence": round(self.confidence, 3), "directed": self.directed,
            "chunks": sorted(self.chunks),
        }

    @staticmethod
    def from_dict(d):
        return Edge(d["source"], d["target"], d["label"], d.get("type", "explicita"),
                    d.get("evidence", ""), d.get("confidence", 0.8),
                    d.get("directed", True), d.get("chunks"), d.get("id"))


class Graph:
    def __init__(self, title="", text="", meta=None):
        self.title = title
        self.text = text
        self.nodes = {}          # id -> Node
        self.edges = {}          # key -> Edge
        self.meta = dict(meta or {})
        self.log = []

    # -- nodos ---------------------------------------------------------
    def add_node(self, node):
        prev = self.nodes.get(node.id)
        if prev is None:
            self.nodes[node.id] = node
            return node
        # fusión suave
        if len(node.label) > len(prev.label) and prev.type == node.type:
            prev.add_alias(node.label)
        else:
            prev.add_alias(node.label)
        for a in node.aliases:
            prev.add_alias(a)
        if node.description and len(node.description) > len(prev.description):
            prev.description = node.description
        if prev.type == "OTRO" and node.type != "OTRO":
            prev.type = node.type
        prev.mentions.extend(node.mentions)
        prev.chunks |= node.chunks
        return prev

    def node_by_label(self, label):
        s = slug(label)
        if s in self.nodes:
            return self.nodes[s]
        low = (label or "").strip().lower()
        for n in self.nodes.values():
            if n.label.lower() == low or low in [a.lower() for a in n.aliases]:
                return n
        return None

    # -- aristas -------------------------------------------------------
    def add_edge(self, edge):
        if edge.source == edge.target:
            return None
        if edge.source not in self.nodes or edge.target not in self.nodes:
            return None
        k = edge.key()
        prev = self.edges.get(k)
        if prev is None:
            # ¿existe la inversa con la misma etiqueta? evita duplicar
            inv = (edge.target, edge.source, edge.label.lower())
            if inv in self.edges:
                self.edges[inv].chunks |= edge.chunks
                return self.edges[inv]
            self.edges[k] = edge
            return edge
        prev.chunks |= edge.chunks
        prev.confidence = max(prev.confidence, edge.confidence)
        if len(edge.evidence) > len(prev.evidence):
            prev.evidence = edge.evidence
        if TIPOS_RELACION.index(edge.type) < TIPOS_RELACION.index(prev.type):
            prev.type = edge.type
        return prev

    def remove_node(self, nid):
        self.nodes.pop(nid, None)
        for k in [k for k, e in self.edges.items()
                  if e.source == nid or e.target == nid]:
            del self.edges[k]

    # -- topología -----------------------------------------------------
    def neighbors(self, nid):
        out = set()
        for e in self.edges.values():
            if e.source == nid:
                out.add(e.target)
            elif e.target == nid:
                out.add(e.source)
        return out

    def adjacency(self):
        adj = {nid: set() for nid in self.nodes}
        for e in self.edges.values():
            if e.source in adj and e.target in adj:
                adj[e.source].add(e.target)
                adj[e.target].add(e.source)
        return adj

    def degree(self, nid):
        return len(self.neighbors(nid))

    def orphans(self):
        adj = self.adjacency()
        return [nid for nid, ns in adj.items() if not ns]

    def components(self):
        adj = self.adjacency()
        visto, comps = set(), []
        for nid in self.nodes:
            if nid in visto:
                continue
            pila, comp = [nid], []
            visto.add(nid)
            while pila:
                cur = pila.pop()
                comp.append(cur)
                for v in adj[cur]:
                    if v not in visto:
                        visto.add(v)
                        pila.append(v)
            comps.append(comp)
        comps.sort(key=len, reverse=True)
        return comps

    # -- serialización -------------------------------------------------
    def to_dict(self):
        comps = self.components()
        return {
            "title": self.title,
            "text": self.text,
            "meta": self.meta,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()],
            "stats": {
                "nodos": len(self.nodes),
                "aristas": len(self.edges),
                "componentes": len(comps),
                "huerfanos": len(self.orphans()),
                "densidad": round(
                    (2.0 * len(self.edges)) / (len(self.nodes) * (len(self.nodes) - 1)), 4
                ) if len(self.nodes) > 1 else 0.0,
                "por_tipo_entidad": _cuenta([n.type for n in self.nodes.values()]),
                "por_tipo_relacion": _cuenta([e.type for e in self.edges.values()]),
            },
            "log": self.log,
        }

    @staticmethod
    def from_dict(d):
        g = Graph(d.get("title", ""), d.get("text", ""), d.get("meta"))
        for nd in d.get("nodes", []):
            g.nodes[nd["id"]] = Node.from_dict(nd)
        for ed in d.get("edges", []):
            e = Edge.from_dict(ed)
            g.edges[e.key()] = e
        g.log = d.get("log", [])
        return g


def _cuenta(items):
    out = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
