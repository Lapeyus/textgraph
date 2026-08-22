# -*- coding: utf-8 -*-
"""Motor heurístico sin LLM (funciona sin red ni clave).

Calidad muy inferior a la extracción con modelo; sirve como respaldo offline
y para comparar en clase qué aporta un LLM frente a reglas.
"""

import re

from .chunker import sentences

FUNCION = set(u"""el la los las un una unos unas de del al a ante bajo cabe con contra
desde durante en entre hacia hasta mediante para por según sin so sobre tras y e o u ni
que quien cuyo como cuando donde porque pues si no sí más menos muy también tampoco
este esta estos estas ese esa esos esas aquel aquella su sus mi mis tu tus nuestro
junto además ademas asimismo entonces luego después despues durante
lo le les se me te nos os yo tú él ella ellos ellas usted ustedes fue era son eran es
ha han había hubo será sería puede pueden debe deben the of and in to for with on at
by from as is was were are be been this that these those it its his her their""".split())

MESES = u"enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre".split()

PISTAS_ORG = u"universidad instituto academia empresa compañía compania sociedad ministerio banco museo escuela facultad laboratorio fundación fundacion partido consejo comisión comision agencia corporación corporacion s.a. inc ltd asociación asociacion federación federacion".split()
PISTAS_LUGAR = u"ciudad país pais región region provincia estado calle avenida río rio monte mar océano oceano continente isla valle".split()
PISTAS_OBRA = u"libro novela poema película pelicula obra artículo articulo tratado ensayo canción cancion informe ley decreto".split()
PISTAS_EVENTO = u"premio guerra batalla congreso conferencia revolución revolucion tratado cumbre juegos festival elecciones crisis".split()


def _tiene_pista(minusculas, pistas):
    palabras = set(re.findall(u"[\\w.]+", minusculas))
    return any(p in palabras for p in pistas)

MAYUS = u"A-ZÁÉÍÓÚÑÜ"
MINUS = u"a-záéíóúñüïö"
_PROPIO = re.compile(
    u"[%s][%s%s]+(?:\\s+(?:de|del|la|las|los|y|von|van|der|di|da)\\s+[%s][%s%s]+"
    u"|\\s+[%s][%s%s]+)*" % (MAYUS, MINUS, MAYUS, MAYUS, MINUS, MAYUS, MAYUS, MINUS, MAYUS))
_SIGLA = re.compile(u"\\b[%s]{2,6}\\b" % MAYUS)
_ANIO = re.compile(u"\\b(?:1[0-9]{3}|20[0-9]{2})\\b")
_FECHA = re.compile(u"\\b(?:\\d{1,2}\\s+de\\s+)?(?:%s)(?:\\s+de\\s+\\d{3,4})?\\b"
                    % "|".join(MESES), re.I)
_CANTIDAD = re.compile(u"\\b\\d+(?:[.,]\\d+)?\\s?(?:%|km|kg|m|cm|mm|g|l|ml|€|\\$|años|"
                       u"habitantes|millones|miles|grados|°C|K|W|V|Hz)\\b", re.I)
_COMILLAS = re.compile(u"[«\"“]([^»\"”]{3,60})[»\"”]")
_VERBO = re.compile(u"\\b\\w+(?:ó|ía|aron|ieron|aba|ía|ar|er|ir|an|en|a|e)\\b", re.U)
_VERBOS_COMUNES = set(u"""es son fue fueron era eran está están estaba tiene tienen tuvo
hay ha han había fundó creó descubrió escribió publicó nació murió dirigió lideró
ganó recibió estudió trabajó vivió trasladó desarrolló propuso demostró incluye
contiene forma parte pertenece produce genera causa provoca permite requiere""".split())


def _tipo(txt):
    b = txt.lower()
    if _ANIO.fullmatch(txt) or _FECHA.match(txt):
        return "TIEMPO"
    if _CANTIDAD.match(txt):
        return "MAGNITUD"
    if _tiene_pista(b, PISTAS_EVENTO):
        return "EVENTO"
    if _tiene_pista(b, PISTAS_ORG):
        return "ORGANIZACION"
    if _tiene_pista(b, PISTAS_LUGAR):
        return "LUGAR"
    if _tiene_pista(b, PISTAS_OBRA):
        return "OBRA"
    if txt.isupper() and 2 <= len(txt) <= 6:
        return "ORGANIZACION"
    if len(txt.split()) >= 2 and all(w[:1].isupper() for w in txt.split()
                                     if w.lower() not in FUNCION):
        return "PERSONA"
    return "OTRO"


def _limpia(txt):
    ws = txt.split()
    while ws and ws[0].lower() in FUNCION:
        ws = ws[1:]
    while ws and ws[-1].lower() in FUNCION:
        ws = ws[:-1]
    return " ".join(ws).strip(" ,;:.")


def _candidatos(frase, es_inicio_ok=False):
    """Devuelve [(inicio_rel, fin_rel, texto)] de entidades candidatas."""
    vistos = []
    def add(m):
        t = _limpia(m.group(0))
        if len(t) < 2 or t.lower() in FUNCION:
            return
        ini = frase.find(t, m.start())
        if ini < 0:
            ini = m.start()
        vistos.append((ini, ini + len(t), t))

    for m in _COMILLAS.finditer(frase):
        vistos.append((m.start(1), m.end(1), m.group(1)))
    for rx in (_FECHA, _CANTIDAD, _ANIO):
        for m in rx.finditer(frase):
            vistos.append((m.start(), m.end(), m.group(0)))
    for m in _PROPIO.finditer(frase):
        # descarta mayúscula inicial de oración si es palabra función o verbo común
        t = _limpia(m.group(0))
        if not t:
            continue
        if m.start() == 0 and len(t.split()) == 1 and (
                t.lower() in FUNCION or t.lower() in _VERBOS_COMUNES):
            continue
        add(m)
    for m in _SIGLA.finditer(frase):
        add(m)

    vistos.sort()
    fusion = []
    for ini, fin, t in vistos:
        if fusion and ini < fusion[-1][1]:
            if fin - ini > fusion[-1][1] - fusion[-1][0]:
                fusion[-1] = (ini, fin, t)
            continue
        fusion.append((ini, fin, t))
    return fusion


def _predicado(medio):
    ws = [w for w in re.split(r"[\s,;]+", medio.strip()) if w]
    verbos = [w for w in ws if w.lower() in _VERBOS_COMUNES or _VERBO.fullmatch(w.lower())]
    if verbos:
        i = ws.index(verbos[0])
        frag = ws[i:i + 3]
        return " ".join(frag).strip(" ,;:.").lower() or "se relaciona con"
    if ws and ws[0].lower() in FUNCION and len(ws) <= 3:
        return " ".join(ws).lower()
    return "se menciona junto a"


class MotorLocal(object):
    """Interfaz compatible con los motores LLM, pero basada en reglas."""

    nombre = "local"
    usa_llm = False
    modelo = "reglas"

    def __init__(self, *a, **kw):
        self.coste = 0.0
        self.llamadas = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def resumen(self):
        return {"motor": self.nombre, "modelo": self.modelo,
                "llamadas": self.llamadas, "coste_usd": 0.0,
                "tokens_entrada": 0, "tokens_salida": 0}

    def extraer_fragmento(self, texto, labels_previos=None):
        self.llamadas += 1
        ents, rels, vistos = [], [], {}
        for _, _, frase in sentences(texto):
            cands = _candidatos(frase)
            for ini, fin, t in cands:
                if t.lower() not in vistos:
                    vistos[t.lower()] = t
                    ents.append({"label": t, "tipo": _tipo(t), "aliases": [],
                                 "descripcion": "", "evidencia": frase})
            for a, b in zip(cands, cands[1:]):
                medio = frase[a[1]:b[0]]
                if len(medio) > 90:
                    continue
                rels.append({"origen": a[2], "destino": b[2],
                             "etiqueta": _predicado(medio),
                             "tipo": "implicita", "confianza": 0.35,
                             "evidencia": frase})
            # conecta la primera entidad con las lejanas de la misma frase
            if len(cands) > 2:
                for otro in cands[2:]:
                    rels.append({"origen": cands[0][2], "destino": otro[2],
                                 "etiqueta": u"se menciona junto a",
                                 "tipo": "coocurrencia", "confianza": 0.2,
                                 "evidencia": frase})
        return {"entidades": ents, "relaciones": rels}

    def reconciliar(self, aisladas, catalogo):
        return {"relaciones": []}

    def puentes(self, grupos, texto):
        return {"relaciones": []}

    def fusiones(self, parejas):
        return {"fusiones": []}
