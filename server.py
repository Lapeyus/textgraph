#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor local de textgraph: interfaz web + API.

Uso:  python3 server.py [--puerto 8765] [--sin-navegador]
"""

import argparse
import json
import mimetypes
import os
import posixpath
import re
import sys
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textgraph import exporters, store          # noqa: E402
from textgraph.llm import (MODELO_POR_DEFECTO, MODELO_POR_DEFECTO_ANTIGRAVITY,  # noqa: E402
                           MODELO_POR_DEFECTO_CODEX, MODELO_POR_DEFECTO_GEMINI,
                           MODELOS_ANTIGRAVITY, PRECIOS, PRECIOS_ANTIGRAVITY,
                           PRECIOS_CODEX, PRECIOS_GEMINI, motores_disponibles)
from textgraph.model import Edge, Graph, Node    # noqa: E402
from textgraph.pipeline import construir         # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
TRABAJOS = {}
LOCK = threading.Lock()


# ------------------------------------------------------------------ trabajos
def lanzar_trabajo(params):
    jid = uuid.uuid4().hex[:12]
    with LOCK:
        TRABAJOS[jid] = {"id": jid, "estado": "en_curso", "fase": "inicio",
                         "mensaje": u"Preparando…", "hecho": 0, "total": 1,
                         "grafo_id": None, "error": None, "log": []}

    def progreso(**kw):
        with LOCK:
            t = TRABAJOS[jid]
            t.update({k: v for k, v in kw.items() if k in
                      ("fase", "mensaje", "hecho", "total")})
            t["log"].append(kw.get("mensaje", ""))

    def correr():
        try:
            grafo = construir(
                params["texto"], titulo=params.get("titulo", ""),
                engine=params.get("engine", "auto"),
                modelo=params.get("modelo") or None,
                max_chars=int(params.get("max_chars", 3500)),
                paralelo=int(params.get("paralelo", 2)),
                exhaustividad=bool(params.get("exhaustividad", True)),
                fusion_llm=bool(params.get("fusion_llm", False)),
                progreso=progreso)
            gid = store.guardar(grafo)
            with LOCK:
                TRABAJOS[jid].update({"estado": "listo", "grafo_id": gid,
                                      "hecho": TRABAJOS[jid]["total"],
                                      "mensaje": u"Grafo listo"})
        except Exception as e:
            traceback.print_exc()
            with LOCK:
                TRABAJOS[jid].update({"estado": "error", "error": str(e),
                                      "mensaje": u"Error: %s" % e})

    threading.Thread(target=correr, daemon=True).start()
    return jid


# ------------------------------------------------------------------ handler
class Handler(BaseHTTPRequestHandler):
    server_version = "textgraph/1.0"

    def log_message(self, formato, *args):
        if os.environ.get("TEXTGRAPH_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), formato % args))

    # -- utilidades
    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, codigo, mensaje):
        self._json({"error": mensaje}, codigo)

    def _leer_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _estatico(self, ruta_rel):
        ruta_rel = posixpath.normpath(unquote(ruta_rel)).lstrip("/")
        if ruta_rel in ("", "."):
            ruta_rel = "index.html"
        destino = os.path.normpath(os.path.join(WEB, ruta_rel))
        if not destino.startswith(WEB) or not os.path.isfile(destino):
            return self._error(404, "no encontrado")
        tipo = mimetypes.guess_type(destino)[0] or "application/octet-stream"
        with open(destino, "rb") as f:
            datos = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "%s; charset=utf-8" % tipo
                         if tipo.startswith("text/") or "javascript" in tipo else tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(datos)

    # -- rutas
    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/estado":
                modelos_claude = sorted(PRECIOS.keys())
                precios = dict(PRECIOS)
                precios.update(PRECIOS_CODEX)
                precios.update(PRECIOS_GEMINI)
                precios.update(PRECIOS_ANTIGRAVITY)
                return self._json({
                    "motores": motores_disponibles(),
                    "modelos": {"claude-cli": modelos_claude, "api": modelos_claude,
                                "codex-cli": sorted(PRECIOS_CODEX.keys()),
                                "gemini-cli": sorted(PRECIOS_GEMINI.keys()),
                                "antigravity-cli": list(MODELOS_ANTIGRAVITY)},
                    "modelo_por_defecto": {"claude-cli": MODELO_POR_DEFECTO,
                                           "api": MODELO_POR_DEFECTO,
                                           "codex-cli": MODELO_POR_DEFECTO_CODEX,
                                           "gemini-cli": MODELO_POR_DEFECTO_GEMINI,
                                           "antigravity-cli": MODELO_POR_DEFECTO_ANTIGRAVITY},
                    "precios": precios,
                    "formatos": [{"id": f[0], "nombre": f[1], "ext": f[3], "uso": f[4]}
                                 for f in exporters.FORMATOS],
                })
            if p == "/api/proyectos":
                return self._json({"proyectos": store.listar()})
            m = re.match(r"^/api/trabajo/([\w-]+)$", p)
            if m:
                with LOCK:
                    t = TRABAJOS.get(m.group(1))
                return self._json(t) if t else self._error(404, "trabajo desconocido")
            m = re.match(r"^/api/grafo/([\w.-]+)$", p)
            if m:
                g = store.cargar(m.group(1))
                return self._json(g.to_dict()) if g else self._error(404, "no existe")
            m = re.match(r"^/api/exportar/([\w.-]+)/([\w-]+)$", p)
            if m:
                return self._exportar(m.group(1), m.group(2))
            return self._estatico(p)
        except Exception as e:
            traceback.print_exc()
            return self._error(500, str(e))

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/extraer":
                d = self._leer_json()
                texto = (d.get("texto") or "").strip()
                if not texto:
                    return self._error(400, "falta el texto")
                if len(texto) > 400000:
                    return self._error(400, "texto demasiado largo (máx. 400 000 caracteres)")
                return self._json({"trabajo": lanzar_trabajo(d)})
            m = re.match(r"^/api/grafo/([\w.-]+)$", p)
            if m:
                d = self._leer_json()
                g = Graph.from_dict(d)
                gid = store.guardar(g, m.group(1))
                return self._json({"ok": True, "id": gid})
            return self._error(404, "ruta desconocida")
        except Exception as e:
            traceback.print_exc()
            return self._error(500, str(e))

    def do_DELETE(self):
        m = re.match(r"^/api/grafo/([\w.-]+)$", urlparse(self.path).path)
        if not m:
            return self._error(404, "ruta desconocida")
        return self._json({"ok": store.borrar(m.group(1))})

    def _exportar(self, gid, formato):
        g = store.cargar(gid)
        if not g:
            return self._error(404, "no existe")
        try:
            datos, tipo, ext = exporters.exportar(g, formato, WEB)
        except ValueError as e:
            return self._error(400, str(e))
        from textgraph.model import slug
        nombre = "%s%s" % (slug(g.title or gid, 50), ext)
        self.send_response(200)
        self.send_header("Content-Type", "%s; charset=utf-8" % tipo)
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % nombre)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)


def main():
    ap = argparse.ArgumentParser(description="Servidor local de textgraph")
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--sin-navegador", action="store_true")
    args = ap.parse_args()

    servidor = ThreadingHTTPServer((args.host, args.puerto), Handler)
    url = "http://%s:%d/" % (args.host, args.puerto)
    print(u"textgraph escuchando en %s  (Ctrl-C para salir)" % url)
    motores = motores_disponibles()
    print(u"  motores disponibles: %s"
          % ", ".join(k for k, v in motores.items() if v))
    if not args.sin_navegador:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print(u"\nadiós")
        servidor.shutdown()


if __name__ == "__main__":
    main()
