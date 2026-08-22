# -*- coding: utf-8 -*-
"""Motores LLM y parseo tolerante de JSON.

Se usa HTTP crudo (urllib) en lugar del SDK `anthropic` a propósito: la
aplicación está diseñada para funcionar sobre el Python del sistema sin
instalar ninguna dependencia. El motor por defecto ni siquiera necesita clave
de API: reutiliza la CLI `claude` ya instalada.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request

from . import prompts

# $ por millón de tokens (entrada, salida). Fuente: tarifas Claude API.
PRECIOS = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}
MODELO_POR_DEFECTO = "claude-opus-5"


class ErrorMotor(RuntimeError):
    pass


# ---------------------------------------------------------------- JSON laxo
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(texto):
    """Extrae el primer objeto JSON de una respuesta del modelo."""
    if not texto:
        raise ErrorMotor("respuesta vacía del modelo")
    t = texto.strip()
    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    ini = t.find("{")
    if ini < 0:
        raise ErrorMotor("la respuesta no contiene JSON: %s" % t[:200])
    # equilibra llaves respetando cadenas
    prof, en_cad, esc = 0, False, False
    for i in range(ini, len(t)):
        c = t[i]
        if en_cad:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                en_cad = False
            continue
        if c == '"':
            en_cad = True
        elif c == "{":
            prof += 1
        elif c == "}":
            prof -= 1
            if prof == 0:
                bloque = t[ini:i + 1]
                try:
                    return json.loads(bloque)
                except ValueError:
                    try:
                        return json.loads(re.sub(r",(\s*[}\]])", r"\1", bloque))
                    except ValueError as e:
                        raise ErrorMotor("JSON inválido: %s" % e)
    # JSON truncado: recorta hasta el último elemento completo
    recorte = t[ini:]
    for cierre in ("}]}", "}]}"):
        pos = recorte.rfind("}")
        if pos > 0:
            intento = recorte[:pos + 1]
            for sufijo in ("", "]}", "}]}" , "]}}"):
                try:
                    return json.loads(intento + sufijo)
                except ValueError:
                    continue
        break
    raise ErrorMotor("no se pudo parsear el JSON de la respuesta")


# ---------------------------------------------------------------- motores
class Motor(object):
    nombre = "base"
    usa_llm = True

    def __init__(self, modelo=None, **kw):
        self.modelo = modelo or MODELO_POR_DEFECTO
        self.coste = 0.0
        self.llamadas = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def completar(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000):
        raise NotImplementedError

    def json(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000, reintentos=2):
        ultimo = None
        for intento in range(reintentos + 1):
            try:
                bruto = self.completar(prompt, sistema, max_tokens)
                return parse_json(bruto)
            except ErrorMotor as e:
                ultimo = e
                if intento < reintentos:
                    prompt = (prompt + "\n\nIMPORTANTE: la respuesta anterior no fue "
                              "JSON válido. Devuelve ÚNICAMENTE el objeto JSON.")
        raise ultimo

    # -- tareas de extracción -----------------------------------------
    def extraer_fragmento(self, texto, labels_previos=None):
        ctx = ""
        if labels_previos:
            lista = "\n".join("- %s" % l for l in labels_previos[:150])
            ctx = prompts.CONTEXTO_ENTIDADES.format(lista=lista)
        p = prompts.EXTRACCION.format(tipos=prompts.TIPOS, contexto=ctx, texto=texto)
        d = self.json(p)
        return {"entidades": d.get("entidades") or [],
                "relaciones": d.get("relaciones") or []}

    def reconciliar(self, aisladas, catalogo):
        p = prompts.RECONCILIACION.format(aisladas=aisladas, catalogo=catalogo)
        return {"relaciones": (self.json(p, max_tokens=8000).get("relaciones") or [])}

    def puentes(self, grupos, texto, n=2):
        p = prompts.PUENTES.format(n=n, grupos=grupos, texto=texto)
        return {"relaciones": (self.json(p, max_tokens=6000).get("relaciones") or [])}

    def fusiones(self, parejas):
        p = prompts.FUSION.format(parejas=parejas)
        return {"fusiones": (self.json(p, max_tokens=6000).get("fusiones") or [])}

    def resumen(self):
        return {"motor": self.nombre, "modelo": self.modelo, "llamadas": self.llamadas,
                "coste_usd": round(self.coste, 4),
                "tokens_entrada": self.tokens_in, "tokens_salida": self.tokens_out}


class MotorClaudeCLI(Motor):
    """Usa la CLI `claude` ya autenticada. No requiere clave de API."""

    nombre = "claude-cli"

    def __init__(self, modelo=None, timeout=300, **kw):
        Motor.__init__(self, modelo)
        self.timeout = timeout
        self.bin = shutil.which("claude")

    @staticmethod
    def disponible():
        return shutil.which("claude") is not None

    def completar(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000):
        if not self.bin:
            raise ErrorMotor("no se encontró la CLI `claude` en el PATH")
        # Se desactivan herramientas, ajustes de usuario y servidores MCP: sin
        # ellos la llamada no arrastra decenas de miles de tokens de contexto
        # (en pruebas, el coste por llamada baja unas 50 veces).
        cmd = [self.bin, "-p", "--output-format", "json", "--max-turns", "1",
               "--tools", "", "--setting-sources", "",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--system-prompt", sistema]
        if self.modelo:
            cmd += ["--model", self.modelo]
        try:
            proc = subprocess.run(cmd, input=prompt.encode("utf-8"),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise ErrorMotor("la CLI `claude` superó el tiempo límite (%ss)" % self.timeout)
        if proc.returncode != 0:
            raise ErrorMotor("la CLI `claude` falló: %s"
                             % proc.stderr.decode("utf-8", "replace")[:400])
        try:
            env = json.loads(proc.stdout.decode("utf-8", "replace"))
        except ValueError:
            raise ErrorMotor("salida inesperada de la CLI `claude`")
        if env.get("is_error"):
            raise ErrorMotor("la CLI `claude` devolvió error: %s"
                             % str(env.get("result"))[:300])
        self.llamadas += 1
        self.coste += float(env.get("total_cost_usd") or 0.0)
        uso = env.get("usage") or {}
        self.tokens_in += int(uso.get("input_tokens") or 0)
        self.tokens_out += int(uso.get("output_tokens") or 0)
        return env.get("result") or ""


class MotorAPI(Motor):
    """Messages API por HTTP crudo (sin dependencias)."""

    nombre = "api"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, modelo=None, api_key=None, timeout=300, **kw):
        Motor.__init__(self, modelo)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.timeout = timeout

    @staticmethod
    def disponible():
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def completar(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000):
        if not self.api_key:
            raise ErrorMotor("falta ANTHROPIC_API_KEY")
        cuerpo = {
            "model": self.modelo,
            "max_tokens": max_tokens,
            "system": sistema,
            "messages": [{"role": "user", "content": prompt}],
        }
        datos = json.dumps(cuerpo).encode("utf-8")
        req = urllib.request.Request(self.URL, data=datos, method="POST", headers={
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:400]
            raise ErrorMotor("HTTP %s de la API: %s" % (e.code, detalle))
        except urllib.error.URLError as e:
            raise ErrorMotor("no se pudo conectar con la API: %s" % e.reason)

        if resp.get("stop_reason") == "refusal":
            raise ErrorMotor("el modelo rechazó la solicitud (%s)"
                             % (resp.get("stop_details") or {}).get("category"))
        partes = [b.get("text", "") for b in resp.get("content", [])
                  if b.get("type") == "text"]
        uso = resp.get("usage") or {}
        ent, sal = int(uso.get("input_tokens") or 0), int(uso.get("output_tokens") or 0)
        pin, pout = PRECIOS.get(self.modelo, (0.0, 0.0))
        self.llamadas += 1
        self.tokens_in += ent
        self.tokens_out += sal
        self.coste += ent / 1e6 * pin + sal / 1e6 * pout
        return "\n".join(partes)


def crear_motor(nombre="auto", modelo=None, **kw):
    if nombre in ("auto", None, ""):
        if MotorClaudeCLI.disponible():
            nombre = "claude-cli"
        elif MotorAPI.disponible():
            nombre = "api"
        else:
            nombre = "local"
    if nombre == "claude-cli":
        return MotorClaudeCLI(modelo, **kw)
    if nombre == "api":
        return MotorAPI(modelo, **kw)
    if nombre == "local":
        from .local import MotorLocal
        return MotorLocal()
    raise ErrorMotor("motor desconocido: %s" % nombre)


def motores_disponibles():
    return {
        "claude-cli": MotorClaudeCLI.disponible(),
        "api": MotorAPI.disponible(),
        "local": True,
    }
