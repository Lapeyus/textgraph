# -*- coding: utf-8 -*-
"""Motores LLM y parseo tolerante de JSON.

Se usa HTTP crudo (urllib) en lugar del SDK `anthropic` a propósito: la
aplicación está diseñada para funcionar sobre el Python del sistema sin
instalar ninguna dependencia. Los motores por defecto ni siquiera necesitan
clave de API: reutilizan la CLI ya instalada y autenticada (`claude`, `codex`
de OpenAI, `gemini` de Google o `agy` de Antigravity).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
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

# Ídem para los modelos que ofrece la CLI `codex`. Fuente: tarifas OpenAI API;
# en toda la familia la entrada cacheada se cobra al 10 % de la de entrada.
PRECIOS_CODEX = {
    "gpt-5.6-sol": (4.0, 20.0),
    "gpt-5.6-terra": (2.0, 12.0),
    "gpt-5.6-luna": (0.2, 1.2),
}
MODELO_POR_DEFECTO_CODEX = "gpt-5.6-sol"

# Ídem para la CLI `gemini`. Fuente: tarifas Gemini API (tramo <=200k tokens);
# la entrada cacheada también se cobra al 10 % de la de entrada.
PRECIOS_GEMINI = {
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-3-pro-preview": (2.0, 12.0),
    "gemini-3-flash-preview": (0.5, 3.0),
    "gemini-2.5-pro": (1.25, 10.0),
}
MODELO_POR_DEFECTO_GEMINI = "gemini-3-pro-preview"

# Catálogo de la CLI `agy` de Antigravity (el sufijo es el esfuerzo de
# razonamiento). El consumo sale de la cuota del plan de Google; el coste
# equivalente usa la tarifa pública del modelo subyacente cuando existe
# (GPT-OSS no tiene, así que se contabiliza a cero).
MODELOS_ANTIGRAVITY = [
    "gemini-3.7-flash-high", "gemini-3.7-flash-medium", "gemini-3.7-flash-low",
    "gemini-3.6-flash-high", "gemini-3.6-flash-medium", "gemini-3.6-flash-low",
    "gemini-3.5-flash-high", "gemini-3.5-flash-medium", "gemini-3.5-flash-low",
    "gemini-3.1-pro-high", "gemini-3.1-pro-low",
    "claude-sonnet-4-6", "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
]
PRECIOS_ANTIGRAVITY = {
    "gemini-3.7-flash-high": (0.75, 3.75),
    "gemini-3.7-flash-medium": (0.75, 3.75),
    "gemini-3.7-flash-low": (0.75, 3.75),
    "gemini-3.6-flash-high": (0.75, 3.75),
    "gemini-3.6-flash-medium": (0.75, 3.75),
    "gemini-3.6-flash-low": (0.75, 3.75),
    "gemini-3.5-flash-high": (1.5, 9.0),
    "gemini-3.5-flash-medium": (1.5, 9.0),
    "gemini-3.5-flash-low": (1.5, 9.0),
    "gemini-3.1-pro-high": (2.0, 12.0),
    "gemini-3.1-pro-low": (2.0, 12.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6-thinking": (5.0, 25.0),
}
MODELO_POR_DEFECTO_ANTIGRAVITY = "gemini-3.7-flash-high"

# Servidor Ollama local: sin coste y sin red externa. OLLAMA_HOST suele venir
# como direccion de escucha ("0.0.0.0:11434"), asi que se normaliza a una URL
# conectable.
MODELO_POR_DEFECTO_OLLAMA = "gemma4:12b-mlx"


def _host_ollama(host=None):
    h = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").strip().rstrip("/")
    if not h.startswith(("http://", "https://")):
        h = "http://" + h
    return h.replace("://0.0.0.0", "://localhost")


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


class MotorCodexCLI(Motor):
    """Usa la CLI `codex` (OpenAI) ya autenticada. No requiere clave de API."""

    nombre = "codex-cli"

    def __init__(self, modelo=None, timeout=300, **kw):
        Motor.__init__(self, modelo or MODELO_POR_DEFECTO_CODEX)
        self.timeout = timeout
        self.bin = shutil.which("codex")

    @staticmethod
    def disponible():
        return shutil.which("codex") is not None

    @staticmethod
    def _leer_eventos(jsonl):
        """Extrae (texto, uso, error) del JSONL de `codex exec --json`."""
        texto, uso, error = "", {}, None
        for linea in (jsonl or "").splitlines():
            try:
                evt = json.loads(linea)
            except ValueError:
                continue
            if not isinstance(evt, dict):
                continue
            tipo = evt.get("type") or ""
            item = evt.get("item") or {}
            if tipo == "item.completed" and item.get("type") == "agent_message":
                texto = item.get("text") or texto
            elif tipo == "turn.completed":
                uso = evt.get("usage") or {}
            elif tipo in ("turn.failed", "error"):
                e = evt.get("error")
                error = ((e or {}).get("message") if isinstance(e, dict)
                         else None) or str(e or evt)
        return texto, uso, error

    def completar(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000):
        if not self.bin:
            raise ErrorMotor("no se encontró la CLI `codex` en el PATH")
        # Misma precaución que con `claude`: sandbox de solo lectura, sin la
        # configuración del usuario (MCP incluidos), sin AGENTS.md del proyecto
        # y sin dejar sesiones guardadas. La respuesta final se escribe en un
        # archivo temporal (--output-last-message), que es más estable entre
        # versiones que el propio JSONL.
        tmp = tempfile.NamedTemporaryFile(prefix="textgraph-codex-",
                                          suffix=".txt", delete=False)
        tmp.close()
        cmd = [self.bin, "exec", "--json", "--color", "never",
               "--sandbox", "read-only", "--skip-git-repo-check",
               "--ignore-user-config", "--ephemeral",
               "-c", "project_doc_max_bytes=0",
               "--output-last-message", tmp.name,
               "--model", self.modelo, "-"]
        # `codex exec` no admite un prompt de sistema aparte: se antepone.
        entrada = (sistema + "\n\n" + prompt) if sistema else prompt
        try:
            try:
                proc = subprocess.run(cmd, input=entrada.encode("utf-8"),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      timeout=self.timeout)
            except subprocess.TimeoutExpired:
                raise ErrorMotor("la CLI `codex` superó el tiempo límite (%ss)"
                                 % self.timeout)
            try:
                with open(tmp.name, encoding="utf-8") as f:
                    ultimo = f.read().strip()
            except OSError:
                ultimo = ""
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        texto, uso, error = self._leer_eventos(proc.stdout.decode("utf-8", "replace"))
        if proc.returncode != 0:
            raise ErrorMotor("la CLI `codex` falló: %s"
                             % (error or proc.stderr.decode("utf-8", "replace")[:400]))
        if error and not (ultimo or texto):
            raise ErrorMotor("la CLI `codex` devolvió error: %s" % str(error)[:300])
        ent = int(uso.get("input_tokens") or 0)
        cache = min(ent, int(uso.get("cached_input_tokens") or 0))
        sal = int(uso.get("output_tokens") or 0)
        pin, pout = PRECIOS_CODEX.get(self.modelo, (0.0, 0.0))
        self.llamadas += 1
        self.tokens_in += ent
        self.tokens_out += sal
        # coste equivalente a tarifa de API; la entrada cacheada vale el 10 %
        self.coste += ((ent - cache) * pin + cache * pin * 0.1 + sal * pout) / 1e6
        return ultimo or texto


class MotorGeminiCLI(Motor):
    """Usa la CLI `gemini` (Google) ya autenticada. No requiere clave de API."""

    nombre = "gemini-cli"

    def __init__(self, modelo=None, timeout=300, **kw):
        Motor.__init__(self, modelo or MODELO_POR_DEFECTO_GEMINI)
        self.timeout = timeout
        self.bin = shutil.which("gemini")

    @staticmethod
    def disponible():
        return shutil.which("gemini") is not None

    @staticmethod
    def _leer_respuesta(salida):
        """Extrae (texto, stats, error) del JSON de `gemini -o json`."""
        t = (salida or "").strip()
        ini = t.find("{")
        if ini < 0:
            return "", {}, None
        try:
            env = json.loads(t[ini:])
        except ValueError:
            return "", {}, None
        if not isinstance(env, dict):
            return "", {}, None
        err = env.get("error")
        msg = err.get("message") if isinstance(err, dict) else \
            (str(err) if err else None)
        return env.get("response") or "", env.get("stats") or {}, msg

    def completar(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000):
        if not self.bin:
            raise ErrorMotor("no se encontró la CLI `gemini` en el PATH")
        # Misma precaución que con las otras CLI: modo plan (solo lectura) y
        # sin extensiones. GEMINI_SYSTEM_MD apunta a un archivo temporal con
        # nuestro prompt de sistema, que SUSTITUYE al del agente: además de
        # fijar las instrucciones, ahorra los miles de tokens de ese prompt.
        tmp = tempfile.NamedTemporaryFile(prefix="textgraph-gemini-",
                                          suffix=".md", delete=False)
        try:
            tmp.write((sistema or "").encode("utf-8"))
            tmp.close()
            entorno = dict(os.environ)
            if sistema:
                entorno["GEMINI_SYSTEM_MD"] = tmp.name
            cmd = [self.bin, "-o", "json", "--approval-mode", "plan",
                   "--skip-trust", "-e", "none",
                   "-m", self.modelo, "-p", prompt]
            try:
                proc = subprocess.run(cmd, input=b"", stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      timeout=self.timeout, env=entorno)
            except subprocess.TimeoutExpired:
                raise ErrorMotor("la CLI `gemini` superó el tiempo límite (%ss)"
                                 % self.timeout)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        texto, stats, error = self._leer_respuesta(
            proc.stdout.decode("utf-8", "replace"))
        if proc.returncode != 0:
            raise ErrorMotor("la CLI `gemini` falló: %s"
                             % (error or proc.stderr.decode("utf-8", "replace")[:400]))
        if error and not texto:
            raise ErrorMotor("la CLI `gemini` devolvió error: %s" % str(error)[:300])
        self.llamadas += 1
        for nombre, datos in (stats.get("models") or {}).items():
            t = (datos or {}).get("tokens") or {}
            ent = int(t.get("prompt") or 0)
            cache = min(ent, int(t.get("cached") or 0))
            sal = int(t.get("candidates") or 0) + int(t.get("thoughts") or 0)
            pin, pout = PRECIOS_GEMINI.get(
                nombre, PRECIOS_GEMINI.get(self.modelo, (0.0, 0.0)))
            self.tokens_in += ent
            self.tokens_out += sal
            # coste equivalente a tarifa de API; la entrada cacheada al 10 %
            self.coste += ((ent - cache) * pin + cache * pin * 0.1
                           + sal * pout) / 1e6
        return texto


class MotorAntigravityCLI(Motor):
    """Usa la CLI `agy` de Antigravity (Google) ya autenticada."""

    nombre = "antigravity-cli"

    def __init__(self, modelo=None, timeout=300, **kw):
        Motor.__init__(self, modelo or MODELO_POR_DEFECTO_ANTIGRAVITY)
        self.timeout = timeout
        self.bin = shutil.which("agy")

    @staticmethod
    def disponible():
        return shutil.which("agy") is not None

    @staticmethod
    def _leer_respuesta(salida):
        """Extrae (texto, uso, error) del JSON de `agy --output-format json`."""
        t = (salida or "").strip()
        ini = t.find("{")
        if ini < 0:
            return "", {}, None
        try:
            env = json.loads(t[ini:])
        except ValueError:
            return "", {}, None
        if not isinstance(env, dict):
            return "", {}, None
        error = env.get("error") or (
            None if env.get("status") in (None, "SUCCESS")
            else str(env.get("status")))
        return env.get("response") or "", env.get("usage") or {}, error

    def completar(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000):
        if not self.bin:
            raise ErrorMotor("no se encontró la CLI `agy` en el PATH")
        # Sin expansión de skills ni comandos, la llamada queda en una pura
        # completación (y ahorra los tokens de esas expansiones). En modo
        # impresión la CLI deniega por sí sola los permisos de herramientas.
        # No admite prompt de sistema aparte, así que se antepone al mensaje.
        entrada = (sistema + "\n\n" + prompt) if sistema else prompt
        cmd = [self.bin, "-p", entrada, "--output-format", "json",
               "--disable-slash-commands",
               "--print-timeout", "%ds" % int(self.timeout),
               "--model", self.modelo]
        try:
            proc = subprocess.run(cmd, input=b"", stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  timeout=self.timeout + 30)
        except subprocess.TimeoutExpired:
            raise ErrorMotor("la CLI `agy` superó el tiempo límite (%ss)"
                             % self.timeout)
        texto, uso, error = self._leer_respuesta(
            proc.stdout.decode("utf-8", "replace"))
        if proc.returncode != 0:
            raise ErrorMotor("la CLI `agy` falló: %s"
                             % (error or proc.stderr.decode("utf-8", "replace")[:400]))
        if error and not texto:
            raise ErrorMotor("la CLI `agy` devolvió error: %s" % str(error)[:300])
        ent = int(uso.get("input_tokens") or 0)
        cache = min(ent, int(uso.get("cache_read_tokens") or 0))
        sal = int(uso.get("output_tokens") or 0)  # ya incluye el razonamiento
        pin, pout = PRECIOS_ANTIGRAVITY.get(self.modelo, (0.0, 0.0))
        self.llamadas += 1
        self.tokens_in += ent
        self.tokens_out += sal
        # coste equivalente a tarifa de API; la entrada cacheada al 10 %
        self.coste += ((ent - cache) * pin + cache * pin * 0.1
                       + sal * pout) / 1e6
        return texto


class MotorOllama(Motor):
    """Servidor Ollama local por HTTP crudo. Sin dependencias y sin coste."""

    nombre = "ollama"

    def __init__(self, modelo=None, host=None, timeout=600, **kw):
        Motor.__init__(self, modelo or MODELO_POR_DEFECTO_OLLAMA)
        self.host = _host_ollama(host)
        self.timeout = timeout

    @staticmethod
    def disponible():
        try:
            with urllib.request.urlopen(_host_ollama() + "/api/version", timeout=2):
                return True
        except Exception:
            return False

    def completar(self, prompt, sistema=prompts.SISTEMA, max_tokens=16000):
        # "think": False evita que los modelos razonadores gasten la salida en
        # pensamiento; si el modelo no lo soporta, se reintenta sin el campo.
        resp = self._generar(prompt, sistema, max_tokens, think=False)
        if resp is None:
            resp = self._generar(prompt, sistema, max_tokens, think=None)
        self.llamadas += 1
        self.tokens_in += int(resp.get("prompt_eval_count") or 0)
        self.tokens_out += int(resp.get("eval_count") or 0)
        # modelo local: el coste equivalente queda en cero
        return resp.get("response") or ""

    def _generar(self, prompt, sistema, max_tokens, think):
        cuerpo = {
            "model": self.modelo,
            "system": sistema or "",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": max_tokens},
        }
        if think is not None:
            cuerpo["think"] = think
        req = urllib.request.Request(
            self.host + "/api/generate", data=json.dumps(cuerpo).encode("utf-8"),
            method="POST", headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:300]
            if think is not None and "think" in detalle.lower():
                return None
            raise ErrorMotor("HTTP %s de Ollama: %s" % (e.code, detalle))
        except (urllib.error.URLError, OSError, ValueError) as e:
            # cubre tambien conexiones cortadas a mitad (RemoteDisconnected)
            raise ErrorMotor("fallo de conexion con Ollama: %s" % e)


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
        elif MotorCodexCLI.disponible():
            nombre = "codex-cli"
        elif MotorGeminiCLI.disponible():
            nombre = "gemini-cli"
        elif MotorAntigravityCLI.disponible():
            nombre = "antigravity-cli"
        elif MotorOllama.disponible():
            nombre = "ollama"
        else:
            nombre = "local"
    if nombre == "claude-cli":
        return MotorClaudeCLI(modelo, **kw)
    if nombre == "codex-cli":
        return MotorCodexCLI(modelo, **kw)
    if nombre == "gemini-cli":
        return MotorGeminiCLI(modelo, **kw)
    if nombre == "antigravity-cli":
        return MotorAntigravityCLI(modelo, **kw)
    if nombre == "ollama":
        return MotorOllama(modelo, **kw)
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
        "codex-cli": MotorCodexCLI.disponible(),
        "gemini-cli": MotorGeminiCLI.disponible(),
        "antigravity-cli": MotorAntigravityCLI.disponible(),
        "ollama": MotorOllama.disponible(),
        "local": True,
    }
