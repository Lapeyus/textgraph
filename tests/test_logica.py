# -*- coding: utf-8 -*-
"""Pruebas unitarias de lógica pura (unittest, biblioteca estándar).

Complementan a `pruebas.py`. No usan red, ni CLIs de modelos, ni claves:
los motores LLM se sustituyen por un motor simulado que devuelve JSON fijo,
y el almacenamiento se redirige a una carpeta temporal.

    python3 -m unittest discover -s tests -v
"""

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from http.server import ThreadingHTTPServer
from unittest import mock

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_REPO)

from textgraph import exhaustive, exporters, llm, normalize, store   # noqa: E402
from textgraph.chunker import chunk, find_quote, sentences          # noqa: E402
from textgraph.local import MotorLocal                              # noqa: E402
from textgraph.model import Edge, Graph, Node, slug                 # noqa: E402
from textgraph import pipeline                                      # noqa: E402

TEXTO = (u"Marie Curie nació en Varsovia en 1867. Junto al Dr. Pierre Curie "
         u"descubrió el polonio. Recibió el Premio Nobel de Física en 1903.")


class MotorSimulado(MotorLocal):
    """Motor con interfaz de LLM que responde JSON predefinido (sin red)."""

    nombre = "simulado"
    usa_llm = True
    modelo = "simulado-1"

    def __init__(self, respuesta, reconciliacion=None):
        MotorLocal.__init__(self)
        self.respuesta = respuesta
        self.reconciliacion = reconciliacion or {"relaciones": []}
        self.vistos = []

    def extraer_fragmento(self, texto, labels_previos=None):
        self.llamadas += 1
        self.vistos.append(list(labels_previos or []))
        return json.loads(json.dumps(self.respuesta))

    def reconciliar(self, aisladas, catalogo):
        return self.reconciliacion


# ---------------------------------------------------------------- modelo
class TestModelo(unittest.TestCase):
    def test_slug_quita_acentos_y_simbolos(self):
        self.assertEqual(slug(u"Revolución Francesa (1789)"), "revolucion_francesa_1789")
        self.assertEqual(slug(u"¿?"), "n")
        self.assertEqual(len(slug("a" * 100, 10)), 10)

    def test_tipo_desconocido_cae_en_otro(self):
        self.assertEqual(Node("x", "X", "INVENTADO").type, "OTRO")
        self.assertEqual(Edge("a", "b", "r", "rara").type, "explicita")

    def test_add_edge_rechaza_bucles_y_nodos_inexistentes(self):
        g = Graph()
        g.add_node(Node("a", "A"))
        self.assertIsNone(g.add_edge(Edge("a", "a", "r")))
        self.assertIsNone(g.add_edge(Edge("a", "z", "r")))

    def test_add_edge_fusiona_duplicados_e_inversas(self):
        g = Graph()
        g.add_node(Node("a", "A"))
        g.add_node(Node("b", "B"))
        g.add_edge(Edge("a", "b", "conoce", "coocurrencia", "x", 0.3, chunks={0}))
        g.add_edge(Edge("a", "b", "Conoce", "explicita", "evidencia larga", 0.9, chunks={1}))
        g.add_edge(Edge("b", "a", "conoce", chunks={2}))
        self.assertEqual(len(g.edges), 1)
        e = list(g.edges.values())[0]
        self.assertEqual(e.type, "explicita")          # gana el de más respaldo
        self.assertEqual(e.confidence, 0.9)
        self.assertEqual(e.evidence, "evidencia larga")
        self.assertEqual(e.chunks, {0, 1, 2})

    def test_add_node_fusion_suave(self):
        g = Graph()
        g.add_node(Node("a", "Curie", "OTRO"))
        g.add_node(Node("a", "Marie Curie", "PERSONA", description="física"))
        n = g.nodes["a"]
        self.assertEqual(n.type, "PERSONA")
        self.assertIn("Marie Curie", n.aliases)
        self.assertEqual(n.description, u"física")

    def test_stats_y_componentes(self):
        g = Graph()
        for l in "abcd":
            g.add_node(Node(l, l.upper()))
        g.add_edge(Edge("a", "b", "r"))
        st = g.to_dict()["stats"]
        self.assertEqual(st["componentes"], 3)
        self.assertEqual(st["huerfanos"], 2)
        self.assertEqual(st["densidad"], round(2.0 / 12, 4))

    def test_remove_node_borra_aristas(self):
        g = Graph()
        g.add_node(Node("a", "A"))
        g.add_node(Node("b", "B"))
        g.add_edge(Edge("a", "b", "r"))
        g.remove_node("b")
        self.assertEqual(len(g.edges), 0)


# ---------------------------------------------------------------- texto
class TestChunker(unittest.TestCase):
    def test_no_corta_en_iniciales(self):
        s = sentences(u"J. R. Tolkien escribió. Luego descansó.")
        self.assertEqual(len(s), 2)

    def test_parrafos_separan_oraciones(self):
        s = sentences(u"Sin punto final\n\nOtro párrafo")
        self.assertEqual([x[2] for x in s], [u"Sin punto final", u"Otro párrafo"])

    def test_chunk_vacio_y_offsets(self):
        self.assertEqual(chunk("   "), [])
        frs = chunk(TEXTO, 60, 1)
        for f in frs:
            self.assertEqual(TEXTO[f["start"]:f["end"]], f["text"])
        self.assertEqual([f["i"] for f in frs], list(range(len(frs))))

    def test_find_quote_recorta_citas_largas(self):
        cita = u"Marie Curie nació en Varsovia en 1867 y otras cosas inventadas"
        pos = find_quote(TEXTO, cita)
        self.assertIsNotNone(pos)
        self.assertEqual(pos[0], 0)
        self.assertIsNone(find_quote(TEXTO, u"nada que ver"))
        self.assertIsNone(find_quote(TEXTO, ""))


class TestNormalize(unittest.TestCase):
    def test_clave(self):
        self.assertEqual(normalize.clave(u"La Revolución, Francesa"), "revolucion francesa")

    def test_predicado(self):
        self.assertEqual(normalize.predicado("JUZGADO_POR"), "juzgado por")
        self.assertEqual(normalize.predicado(u"que fundó"), u"fundó")
        self.assertEqual(normalize.predicado(""), "se relaciona con")
        self.assertEqual(len(normalize.predicado("a b c d e f g h").split()), 6)

    def test_es_sigla_de(self):
        self.assertTrue(normalize.es_sigla_de("ONU", u"Organización de las Naciones Unidas"))
        self.assertFalse(normalize.es_sigla_de("onu", u"Organización de las Naciones Unidas"))

    def test_forma_abreviada_no_se_fusiona_sola(self):
        g = Graph()
        g.add_node(Node("a", "Cloud Run", "CONCEPTO"))
        g.add_node(Node("b", "Cloud Run functions", "CONCEPTO"))
        self.assertEqual(normalize.resolver(g, log=[]), 0)
        self.assertEqual(len(g.nodes), 2)

    def test_tipos_distintos_no_se_fusionan(self):
        g = Graph()
        g.add_node(Node("a", u"París", "LUGAR"))
        g.add_node(Node("b", u"París Hilton", "PERSONA"))
        normalize.resolver(g, log=[])
        self.assertEqual(len(g.nodes), 2)


# ---------------------------------------------------------------- llm (sin red)
class TestLLMSinRed(unittest.TestCase):
    def test_parse_json_truncado(self):
        d = llm.parse_json('{"entidades":[{"label":"A"},{"label":"B"},{"lab')
        self.assertEqual([e["label"] for e in d["entidades"]], ["A", "B"])

    def test_parse_json_errores(self):
        with self.assertRaises(llm.ErrorMotor):
            llm.parse_json("")
        with self.assertRaises(llm.ErrorMotor):
            llm.parse_json("sin llaves")

    def test_host_ollama_normaliza(self):
        self.assertEqual(llm._host_ollama("0.0.0.0:11434"), "http://localhost:11434")
        self.assertEqual(llm._host_ollama("https://x:1/"), "https://x:1")

    def test_crear_motor(self):
        self.assertIsInstance(llm.crear_motor("local"), MotorLocal)
        with self.assertRaises(llm.ErrorMotor):
            llm.crear_motor("inexistente")

    def test_auto_cae_en_local_sin_nada_disponible(self):
        clases = [llm.MotorClaudeCLI, llm.MotorAPI, llm.MotorCodexCLI,
                  llm.MotorGeminiCLI, llm.MotorAntigravityCLI, llm.MotorOllama]
        parches = [mock.patch.object(c, "disponible", staticmethod(lambda: False))
                   for c in clases]
        for p in parches:
            p.start()
        try:
            self.assertIsInstance(llm.crear_motor("auto"), MotorLocal)
        finally:
            for p in parches:
                p.stop()

    def test_json_reintenta_y_suma_aviso(self):
        class M(llm.Motor):
            def __init__(self):
                llm.Motor.__init__(self, "x")
                self.prompts = []

            def completar(self, prompt, sistema=None, max_tokens=0):
                self.prompts.append(prompt)
                return "no es json" if len(self.prompts) == 1 else '{"ok": 1}'
        m = M()
        self.assertEqual(m.json("hola"), {"ok": 1})
        self.assertIn("IMPORTANTE", m.prompts[1])

    def test_motor_api_sin_clave_falla_antes_de_la_red(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            m = llm.MotorAPI("claude-sonnet-5")
            with mock.patch.object(urllib.request, "urlopen") as uo:
                with self.assertRaises(llm.ErrorMotor):
                    m.completar("hola")
                uo.assert_not_called()


# ---------------------------------------------------------------- tubería
class TestTuberia(unittest.TestCase):
    RESPUESTA = {
        "entidades": [
            {"label": "la Marie Curie", "tipo": "PERSON", "aliases": ["Curie"],
             "descripcion": u"física", "evidencia": "Marie Curie"},
            {"label": "Varsovia", "tipo": "LOCATION", "evidencia": "Varsovia"},
            {"label": u"Premio Nobel de Física", "tipo": "EVENTO"},
            "basura",
        ],
        "relaciones": [
            {"origen": "Marie Curie", "destino": "Varsovia", "etiqueta": "NACIO_EN",
             "tipo": "explicita", "confianza": 3,
             "evidencia": u"Marie Curie nació en Varsovia"},
            {"origen": "Curie", "destino": "polonio", "etiqueta": u"descubrió",
             "tipo": "rara", "confianza": "x"},
        ],
    }

    def test_construir_con_motor_simulado(self):
        motor = MotorSimulado(self.RESPUESTA)
        g = pipeline.construir(TEXTO, titulo="Prueba", motor=motor)
        labels = {n.label for n in g.nodes.values()}
        self.assertIn("Marie Curie", labels)       # artículo inicial eliminado
        self.assertIn("polonio", labels)           # recuperada de una relación
        mc = g.node_by_label("Marie Curie")
        self.assertEqual(mc.type, "PERSONA")       # tipo en inglés normalizado
        e = g.edges[(mc.id, g.node_by_label("Varsovia").id, "nacio en")]
        self.assertEqual(e.confidence, 1.0)         # confianza recortada a [0,1]
        self.assertTrue(TEXTO.find(e.evidence) >= 0)
        st = g.to_dict()["stats"]
        self.assertEqual(st["huerfanos"], 0)
        self.assertEqual(st["componentes"], 1)
        self.assertEqual(g.meta["motor"], "simulado")
        self.assertIn("exhaustividad", g.meta)
        self.assertTrue(any(u"recuperada" in l for l in g.log))

    def test_oleadas_pasan_etiquetas_previas(self):
        motor = MotorSimulado(self.RESPUESTA)
        texto = u" ".join([u"Oración número %d sobre Varsovia." % i for i in range(12)])
        pipeline.construir(texto, motor=motor, max_chars=80, paralelo=1)
        self.assertGreater(motor.llamadas, 1)
        self.assertEqual(motor.vistos[0], [])
        self.assertIn("Varsovia", motor.vistos[1])

    def test_error_en_fragmento_queda_en_log(self):
        class Roto(MotorSimulado):
            def extraer_fragmento(self, texto, labels_previos=None):
                raise llm.ErrorMotor("fallo simulado")
        g = pipeline.construir(TEXTO, motor=Roto({}), exhaustividad=False)
        self.assertTrue(any("fallo simulado" in l for l in g.log))

    def test_reconciliacion_del_modelo(self):
        g = Graph(text=TEXTO)
        g.add_node(Node("a", "Marie Curie", "PERSONA"))
        g.add_node(Node("b", "Varsovia", "LUGAR"))
        g.add_node(Node("c", "Sorbona", "ORGANIZACION"))   # no aparece en el texto
        g.add_edge(Edge("a", "b", u"nació en"))
        motor = MotorSimulado({}, {"relaciones": [
            {"origen": "Sorbona", "destino": "Marie Curie", "etiqueta": u"acogió a",
             "tipo": "explicita", "confianza": 0.7}]})
        self.assertEqual(exhaustive.paso_modelo(g, motor, log=[]), 1)
        self.assertEqual(g.orphans(), [])

    def test_titulo_por_defecto(self):
        self.assertEqual(pipeline._titulo(u"\n# Mi título\ncuerpo"), u"Mi título")
        self.assertEqual(pipeline._titulo(u"   "), u"Documento sin título")


# ---------------------------------------------------------------- exportadores
class TestExportadores(unittest.TestCase):
    def setUp(self):
        self.g = Graph("T & <x>")
        self.g.add_node(Node("a", u"Ana \"la\" <b>", "PERSONA"))
        self.g.add_node(Node("b", "Bea", "PERSONA"))
        self.g.add_edge(Edge("a", "b", "conoce a", evidence="x"))

    def test_formato_desconocido(self):
        with self.assertRaises(ValueError):
            exporters.exportar(self.g, "xlsx")

    def test_doce_formatos_y_extensiones(self):
        self.assertEqual(len(exporters.FORMATOS), 12)
        web = os.path.join(RAIZ_REPO, "web")
        for fid, _, mime, ext, _ in exporters.FORMATOS:
            datos, tipo, e = exporters.exportar(self.g, fid, web)
            self.assertIsInstance(datos, bytes)
            self.assertEqual((tipo, e), (mime, ext))

    def test_csv_aristas_tiene_cabecera_y_fila(self):
        datos, _, _ = exporters.exportar(self.g, "csv-edges")
        filas = datos.decode("utf-8").strip().splitlines()
        self.assertEqual(len(filas), 2)


# ---------------------------------------------------------------- store
class _ConDataTemporal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="textgraph-test-")
        self._p = mock.patch.object(store, "RAIZ", self.tmp)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestStore(_ConDataTemporal):
    def test_guardar_cargar_listar_borrar(self):
        g = Graph(u"Título con acentos")
        g.add_node(Node("a", "A"))
        gid = store.guardar(g)
        self.assertTrue(gid.startswith("titulo_con_acentos-"))
        self.assertEqual(store.cargar(gid).title, u"Título con acentos")
        lst = store.listar()
        self.assertEqual(lst[0]["id"], gid)
        self.assertEqual(lst[0]["nodos"], 1)
        self.assertTrue(store.borrar(gid))
        self.assertFalse(store.borrar(gid))
        self.assertIsNone(store.cargar(gid))

    def test_listar_ignora_json_corruptos(self):
        with open(os.path.join(self.tmp, "roto.json"), "w") as f:
            f.write("{no")
        self.assertEqual(store.listar(), [])


# ---------------------------------------------------------------- publicar
class TestPublicar(_ConDataTemporal):
    def test_genera_indice_y_visores(self):
        import publicar
        g = Graph(u"Grafo público")
        g.add_node(Node("a", "A"))
        g.add_node(Node("b", "B"))
        g.add_edge(Edge("a", "b", "r"))
        store.guardar(g)
        salida = os.path.join(self.tmp, "sitio")
        with mock.patch.object(sys, "argv", ["publicar.py", "--salida", salida]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(publicar.main(), 0)
        self.assertTrue(os.path.isfile(os.path.join(salida, "grafos", "grafo_publico.html")))
        self.assertTrue(os.path.isfile(os.path.join(salida, ".nojekyll")))
        with open(os.path.join(salida, "index.html"), encoding="utf-8") as f:
            self.assertIn(u"Grafo público", f.read())

    def test_sin_grafos_devuelve_1(self):
        import publicar
        with mock.patch.object(sys, "argv", ["publicar.py", "--salida",
                                             os.path.join(self.tmp, "s")]), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(publicar.main(), 1)


# ---------------------------------------------------------------- servidor
class TestServidor(_ConDataTemporal):
    """Levanta server.Handler en 127.0.0.1 con un puerto efímero."""

    def setUp(self):
        _ConDataTemporal.setUp(self)
        import server
        self.server_mod = server
        disponibles = {"claude-cli": False, "api": False, "codex-cli": False,
                       "gemini-cli": False, "antigravity-cli": False,
                       "ollama": False, "local": True}
        self._p2 = mock.patch.object(server, "motores_disponibles", lambda: disponibles)
        self._p2.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._p2.stop()
        _ConDataTemporal.tearDown(self)

    def _pedir(self, ruta, metodo="GET", cuerpo=None):
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos, method=metodo,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_estado(self):
        c, _, b = self._pedir("/api/estado")
        d = json.loads(b)
        self.assertEqual(c, 200)
        self.assertTrue(d["motores"]["local"])
        self.assertEqual(len(d["formatos"]), 12)
        self.assertIn("claude-cli", d["modelo_por_defecto"])

    def test_extraer_valida_texto(self):
        self.assertEqual(self._pedir("/api/extraer", "POST", {"texto": "  "})[0], 400)
        c, _, b = self._pedir("/api/extraer", "POST", {"texto": "x" * 400001})
        self.assertEqual(c, 400)
        self.assertIn("demasiado largo", json.loads(b)["error"])

    def test_ciclo_guardar_leer_exportar_borrar(self):
        g = Graph("Ciclo")
        g.add_node(Node("a", "A"))
        g.add_node(Node("b", "B"))
        g.add_edge(Edge("a", "b", "r"))
        c, _, b = self._pedir("/api/grafo/mi-grafo", "POST", g.to_dict())
        self.assertEqual((c, json.loads(b)), (200, {"ok": True, "id": "mi-grafo"}))
        c, _, b = self._pedir("/api/grafo/mi-grafo")
        self.assertEqual(json.loads(b)["stats"]["aristas"], 1)
        c, h, b = self._pedir("/api/exportar/mi-grafo/dot")
        self.assertEqual(c, 200)
        self.assertIn('filename="ciclo.dot"', h["Content-Disposition"])
        self.assertEqual(self._pedir("/api/exportar/mi-grafo/xlsx")[0], 400)
        proyectos = json.loads(self._pedir("/api/proyectos")[2])["proyectos"]
        self.assertEqual([p["id"] for p in proyectos], ["mi-grafo"])
        self.assertEqual(json.loads(self._pedir("/api/grafo/mi-grafo", "DELETE")[2]),
                         {"ok": True})
        self.assertEqual(self._pedir("/api/grafo/mi-grafo")[0], 404)

    def test_rutas_desconocidas_y_estaticos(self):
        self.assertEqual(self._pedir("/api/trabajo/nada")[0], 404)
        self.assertEqual(self._pedir("/api/otra", "POST", {})[0], 404)
        self.assertEqual(self._pedir("/api/otra", "DELETE")[0], 404)
        c, h, _ = self._pedir("/")
        self.assertEqual(c, 200)
        self.assertTrue(h["Content-Type"].startswith("text/html"))
        self.assertEqual(self._pedir("/../server.py")[0], 404)

    def test_trabajo_con_motor_local(self):
        import time
        c, _, b = self._pedir("/api/extraer", "POST",
                              {"texto": TEXTO, "engine": "local", "titulo": "Local"})
        jid = json.loads(b)["trabajo"]
        t = {}
        for _ in range(100):
            t = json.loads(self._pedir("/api/trabajo/" + jid)[2])
            if t["estado"] != "en_curso":
                break
            time.sleep(0.05)
        self.assertEqual(t["estado"], "listo", t)
        self.assertEqual(self._pedir("/api/grafo/" + t["grafo_id"])[0], 200)


if __name__ == "__main__":
    unittest.main()
