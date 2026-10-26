# Pruebas de textgraph

## 1. Estrategia

textgraph se apoya en modelos de lenguaje externos, pero casi toda su lógica
es determinista: segmentación, normalización, fusión, índice de menciones,
exhaustividad, métricas, exportación, persistencia y la API HTTP. Las pruebas
cubren esa lógica **sin gastar llamadas a modelos y sin red externa**:

- Los motores LLM se sustituyen por el motor heurístico `MotorLocal` o por un
  **motor simulado** que devuelve JSON fijo (subclase de `MotorLocal` con
  `usa_llm = True`), inyectado en `pipeline.construir(motor=...)`.
- El parseo de las salidas de las CLIs (`codex`, `gemini`, `agy`) se prueba con
  salidas grabadas en el propio código de prueba, llamando a los métodos
  estáticos de lectura; nunca se ejecutan las CLIs.
- El almacenamiento se redirige a una carpeta temporal (parche de
  `store.RAIZ`), así que las pruebas no tocan `data/`.
- El servidor se levanta en `127.0.0.1` con un puerto efímero y la detección
  de motores (`motores_disponibles`, que buscaría CLIs y sondearía Ollama) se
  sustituye por un diccionario fijo.

No hay pruebas automáticas de la interfaz web (`web/app.js`) ni de los motores
reales contra los proveedores.

## 2. Cómo correr las pruebas

Desde la raíz del repositorio, con cualquier Python ≥ 3.8 (no hay entorno
virtual ni dependencias):

```bash
python3 pruebas.py                          # comprobaciones integrales
python3 -m unittest discover -s tests -v    # pruebas unitarias
```

Una prueba concreta:

```bash
python3 -m unittest tests.test_logica.TestServidor -v
python3 -m unittest tests.test_logica.TestTuberia.test_construir_con_motor_simulado
```

## 3. Inventario de suites

### 3.1 `pruebas.py` (script, 46 comprobaciones)

Script autocontenido que imprime `[ok  ]` o `[FALLA]` por comprobación y sale
con código 1 si alguna falla.

| Sección | Qué verifica |
|---|---|
| segmentación | no corta en abreviaturas; desplazamientos exactos; fragmentación con solapamiento; `find_quote` con espacios irregulares |
| parseo de JSON del modelo | vallas Markdown, comas finales, texto sobrante con llaves dentro de cadenas |
| parseo de eventos de la CLI codex | mensaje del agente, uso de tokens, líneas no JSON, error de turno |
| parseo de la respuesta de la CLI gemini | respuesta con ruido previo, tokens por modelo, error en el sobre JSON |
| parseo de la respuesta de la CLI antigravity | respuesta, uso de tokens, estado `SUCCESS` / `ERROR` |
| resolución de entidades | fusión por apellido, acentos/artículos y siglas (6 → 3 nodos) |
| índice de menciones | etiqueta y alias; citas iguales al texto; la forma larga gana |
| exhaustividad | sin modelo: cero sueltos y un componente |
| métricas | más de una comunidad; intermediación alta en puentes |
| tubería completa con el motor local | produce nodos y relaciones; grafo conexo y sin sueltos |
| exportadores | los 12 formatos producen contenido; GraphML/GEXF son XML válido; JSON/JSON-LD son JSON válido |
| ida y vuelta de serialización | `to_dict` → `from_dict` conserva nodos y aristas |

### 3.2 `tests/test_logica.py` (unittest, 40 pruebas)

| Clase | Pruebas | Qué cubre |
|---|---|---|
| `TestModelo` | 7 | `slug`; tipos inválidos → `OTRO` / `explicita`; rechazo de bucles y nodos inexistentes; fusión de aristas duplicadas e inversas (tipo, confianza, evidencia, fragmentos); fusión suave de nodos; estadísticas y densidad; borrado en cascada |
| `TestChunker` | 4 | iniciales («J. R.»); párrafos sin punto; offsets de fragmentos y texto vacío; recorte de citas largas en `find_quote` |
| `TestNormalize` | 5 | `clave`; `predicado` (MAYÚSCULAS_CON_GUIONES, «que …», vacío, máx. 6 palabras); `es_sigla_de`; formas abreviadas y tipos distintos no se fusionan |
| `TestLLMSinRed` | 7 | JSON truncado; errores de `parse_json`; normalización de `OLLAMA_HOST`; `crear_motor` (local, desconocido, `auto` sin nada disponible → local); reintento con aviso en `Motor.json`; `MotorAPI` sin clave falla sin abrir conexión |
| `TestTuberia` | 5 | `construir` con motor simulado (artículo inicial, tipo en inglés, entidad recuperada de relación, confianza recortada, evidencia relocalizada, grafo conexo, `meta`); propagación de etiquetas entre oleadas; error de fragmento en el registro; reconciliación con modelo simulado; título por defecto |
| `TestExportadores` | 3 | formato desconocido → `ValueError`; 12 formatos con MIME y extensión esperados; CSV con cabecera |
| `TestStore` | 2 | guardar / cargar / listar / borrar; JSON corruptos ignorados |
| `TestPublicar` | 2 | genera visor, índice y `.nojekyll` en carpeta temporal; sin grafos → código 1 |
| `TestServidor` | 5 | `GET /api/estado`; validación de `POST /api/extraer` (vacío, > 400 000); ciclo guardar → leer → exportar → listar → borrar; 404 de rutas y protección contra `..`; trabajo completo con motor `local` hasta `listo` |

## 4. Datos y servicios necesarios

| Necesidad | Cómo se resuelve |
|---|---|
| Texto de entrada | Cadenas fijas en el código de prueba (párrafo sobre Marie Curie). |
| Modelos de lenguaje | `MotorLocal` o `MotorSimulado`; ninguna llamada real. |
| CLIs `claude`, `codex`, `gemini`, `agy` | No se ejecutan; solo se prueban los analizadores de su salida. |
| Ollama | No se contacta; `motores_disponibles` se sustituye en las pruebas del servidor. |
| Red | Solo bucle local (`127.0.0.1`) en `TestServidor`. |
| Disco | Carpetas temporales (`tempfile.mkdtemp`) que se eliminan al terminar. `pruebas.py` no escribe en disco. |
| `web/` | Lo leen los exportadores HTML y el servidor estático. |

## 5. Resultado de la última ejecución

Ejecutado el 25 de octubre de 2026 en macOS:

| Suite | Python 3.12.13 | Python 3.9.6 (sistema) |
|---|---|---|
| `python3 pruebas.py` | 46/46 ok, «todas las pruebas pasan» (≈ 0,1 s) | todas pasan |
| `python3 -m unittest discover -s tests -v` | 40 pruebas, OK (≈ 2,6 s) | 40 pruebas, OK |

## 6. Brechas conocidas

- **CLI (`cli.py`)**: sin prueba automática; se ejercita a mano
  (`python3 cli.py examples/revolucion-francesa.txt -m local --no-guardar -o /tmp/salida`).
  Ojo: sin `--no-guardar`, la CLI escribe en `data/`.
- **Motores reales**: la construcción de los comandos de cada CLI y las
  peticiones HTTP a la Messages API y a Ollama no se prueban (requieren
  credenciales, red o servicios locales).
- **Interfaz web**: sin pruebas de `web/app.js` (no hay entorno de JavaScript
  en el repositorio).
- **Fusión asistida por modelo** (`normalize.resolver(usar_llm=True)`) y
  **puentes entre componentes con modelo** (`exhaustive.paso_componentes`): sin
  prueba con motor simulado.
- **Exportadores**: se valida que produzcan XML/JSON bien formado, no la
  semántica de Cypher, DOT, Mermaid o Turtle con sus herramientas.
- **Rendimiento**: no hay pruebas con textos largos ni medición de tiempos.
