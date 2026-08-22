# textgraph

Convierte un texto en un **grafo de conocimiento exhaustivo**: las entidades son
los nodos, las relaciones son las aristas, y ninguna entidad se queda suelta.
Incluye una interfaz gráfica para explorar el grafo y exportadores a los
formatos abiertos habituales (Gephi, Neo4j, Graphviz, RDF, Mermaid…), además de
un «paquete para LLM» pensado para que otro modelo siga analizando el resultado.

Pensado para uso educativo: cada relación conserva la **cita literal del texto**
que la justifica, y el visor permite ir del grafo al texto y del texto al grafo.

**▶ Grafos de ejemplo, explorables en el navegador:
[lapeyus.github.io/textgraph](https://lapeyus.github.io/textgraph/)**

```
        texto  ──▶  fragmentos  ──▶  extracción (LLM)  ──▶  fusión de duplicados
                                                                   │
   exportadores  ◀──  métricas de red  ◀──  garantía de exhaustividad
```

## Requisitos

- Python 3.8 o superior (basta el que trae macOS).
- **Ninguna dependencia externa**: todo funciona con la biblioteca estándar.
  La librería de visualización (vis-network) va incluida en `web/vendor/`.
- Para la extracción con modelo, una de estas dos cosas:
  - la CLI `claude` instalada y con sesión iniciada (opción por defecto, no
    necesita clave de API), o
  - la variable de entorno `ANTHROPIC_API_KEY` con una clave de la API.

Sin ninguna de las dos, la aplicación sigue funcionando con el motor
heurístico local (sin red, sin coste y con bastante menos precisión).

## Arranque

```bash
python3 server.py
```

Se abre `http://127.0.0.1:8765/` en el navegador. En macOS también sirve hacer
doble clic en `iniciar.command`.

Opciones: `--puerto 9000`, `--host 0.0.0.0`, `--sin-navegador`.
El servidor escucha solo en `127.0.0.1` salvo que se indique otra cosa.

## Uso de la interfaz

1. Pega el texto (o abre un `.txt` / `.md`) en el panel izquierdo.
2. Ajusta las opciones si quieres: motor, modelo, tamaño de fragmento,
   fragmentos en paralelo, exhaustividad asistida, fusión de duplicados.
   Debajo del botón aparece una estimación orientativa de llamadas y coste.
3. Pulsa **Construir grafo**.
4. Explora:
   - **Detalle**: tipo, alias, métricas, relaciones entrantes y salientes,
     y las apariciones de la entidad en el texto.
   - **Texto**: el texto original con cada mención resaltada; al pulsar una
     mención se selecciona el nodo correspondiente.
   - **Listados**: tablas de entidades y relaciones, ordenables y clicables.
   - **Informe**: cómo se construyó el grafo y qué decisiones se tomaron.
   - **Filtros**: por tipo de entidad, tipo de relación, confianza mínima y
     vecindario de un nodo (con profundidad configurable).
   - **✎ Editar**: añadir, corregir o borrar nodos y relaciones a mano y guardar.
5. **⤓ Exportar** ofrece los doce formatos de salida.

## Exhaustividad: por qué ningún nodo queda aislado

El planteamiento es que si algo aparece en un texto, guarda alguna relación con
lo demás; si el grafo lo deja suelto, es un fallo de la extracción, no del
texto. Tras la extracción se aplica una cascada de reparación, de más a menos
respaldo textual, y cada arista queda marcada con el tipo que le corresponde:

| Tipo de relación | Origen | Cómo se lee |
|---|---|---|
| `explicita` | el texto la afirma literalmente | fiable |
| `implicita` | deducida por el modelo (correferencia, contexto) | razonable |
| `coocurrencia` | las entidades comparten oración, sin predicado explícito | débil |
| `estructural` | último recurso para no dejar nodos sueltos | muy débil |

La cascada es: co-ocurrencia en la misma oración → reconciliación asistida por
el modelo (se le muestran las entidades sueltas con su contexto y el catálogo
del grafo) → co-ocurrencia en el mismo fragmento → enlace estructural al nodo
más central. Después se unen los componentes desconectados con el mismo
criterio. El resultado siempre es **un único componente conexo y cero nodos
sueltos**, y el panel *Informe* dice exactamente cuántas aristas puso cada paso.

Si prefieres ver el grafo «crudo», desmarca la exhaustividad asistida y filtra
por tipo de relación en el visor: las aristas débiles se distinguen a simple
vista (línea discontinua o punteada).

## Formatos de exportación

| Formato | Extensión | Para qué |
|---|---|---|
| JSON nativo | `.json` | grafo completo con evidencias, menciones y métricas |
| GraphML | `.graphml` | Gephi, yEd, Cytoscape, NetworkX |
| GEXF | `.gexf` | Gephi |
| CSV de nodos / aristas | `.nodes.csv` / `.edges.csv` | hojas de cálculo, Gephi |
| Cypher | `.cypher` | importar en Neo4j |
| DOT | `.dot` | Graphviz (`dot -Tpdf grafo.dot -o grafo.pdf`) |
| Mermaid | `.mmd` | Markdown, Obsidian, documentación |
| RDF Turtle | `.ttl` | web semántica, SPARQL |
| JSON-LD | `.jsonld` | datos enlazados |
| Paquete para LLM | `.llm.md` | pasarle el grafo a otro modelo |
| HTML autónomo | `.html` | visor interactivo en un solo archivo, sin servidor |

El HTML autónomo lleva dentro los datos y la librería de visualización: se
puede enviar por correo o subir a cualquier sitio y funciona sin conexión.

## Uso desde la terminal

```bash
python3 cli.py texto.txt                       # json + html + paquete LLM
python3 cli.py texto.txt -f graphml -o salida/
python3 cli.py texto.txt -m local              # sin modelo, sin coste
cat texto.txt | python3 cli.py - --modelo claude-sonnet-5
python3 cli.py --listar-formatos
```

Opciones útiles: `--fragmento 2500` (tamaño del fragmento), `--paralelo 3`
(fragmentos simultáneos), `--sin-exhaustividad`, `--fusion-llm`, `--no-guardar`.

## Comprobar que todo funciona

```bash
python3 pruebas.py
```

Ejercita segmentación, parseo de JSON, fusión de entidades, índice de
menciones, garantía de exhaustividad, métricas, la tubería completa con el
motor local y los doce exportadores. No gasta llamadas al modelo.

## Motores y coste

| Motor | Requisito | Coste | Calidad |
|---|---|---|---|
| `claude-cli` (por defecto) | CLI `claude` con sesión | se carga a tu cuenta de Claude | alta |
| `api` | `ANTHROPIC_API_KEY` | tarifa de la Messages API | alta |
| `local` | nada | cero | orientativa |

Medición real sobre un texto de 1 626 caracteres (un fragmento):

| Modelo | Coste | Tiempo | Resultado |
|---|---|---|---|
| `claude-opus-5` (por defecto) | ≈ 0,29 $ | ≈ 95 s | 55 nodos, 62 relaciones |
| `claude-sonnet-5` | ≈ 4 veces menos | ≈ 20 s | calidad muy parecida |

Para textos largos, `claude-sonnet-5` suele ser la opción sensata; el modelo se
elige en el desplegable de la interfaz o con `--modelo` en la terminal.

### Qué significan esas cifras según cómo estés autenticado

La CLI `claude` informa de un `total_cost_usd` por llamada y la aplicación lo
muestra como «coste equivalente». **No siempre es un cargo**:

- **Sesión de suscripción** (Pro o Max, `billingType: stripe_subscription`): no
  hay facturación por token. El uso se descuenta de los límites del plan —la
  ventana móvil de unas 5 horas y el tope semanal—, y la cifra en dólares es
  solo el equivalente a tarifa de API, útil para comparar modelos. Al agotar el
  límite la CLI devuelve un error y hay que esperar a la siguiente ventana;
  nunca cobra de más, salvo que el «uso extra» esté activado en la cuenta.
- **Clave de API** (`ANTHROPIC_API_KEY`, motor `api`): ahí sí es un cargo real
  a la cuenta de facturación de la consola.

Para saber en cuál estás: si `echo $ANTHROPIC_API_KEY` está vacío y en
`~/.claude.json` figura `"billingType": "stripe_subscription"`, estás en el
primer caso. Con suscripción, el recurso escaso es la **cuota**, no el dinero:
`claude-opus-5` gasta unas cinco veces más cuota que `claude-sonnet-5` por el
mismo texto, así que para lotes largos conviene Sonnet.

El motor `claude-cli` lanza la CLI con las herramientas, los ajustes de usuario
y los servidores MCP desactivados. No es cosmético: sin esa precaución cada
llamada arrastra decenas de miles de tokens de contexto y cuesta unas 50 veces
más.

## Cómo funciona por dentro

1. **Segmentación** (`chunker.py`): corta por oraciones respetando abreviaturas
   y agrupa en fragmentos solapados, conservando los desplazamientos del texto.
2. **Extracción** (`llm.py`, `prompts.py`): por cada fragmento se pide al modelo
   un JSON con entidades (etiqueta, tipo, alias, descripción, evidencia) y
   relaciones (origen, predicado, destino, tipo, confianza, evidencia). A cada
   fragmento se le pasa la lista de entidades ya conocidas para que reutilice
   las mismas etiquetas.
3. **Fusión de duplicados** (`normalize.py`): reglas de normalización (acentos,
   artículos, siglas, apellidos, plurales) y, opcionalmente, consulta al modelo
   para los casos dudosos.
4. **Índice de menciones** (`mentions.py`): localiza todas las apariciones
   literales de cada entidad y sus alias, dando prioridad a la forma más larga.
5. **Exhaustividad** (`exhaustive.py`): la cascada descrita arriba.
6. **Métricas** (`analysis.py`): grado, PageRank, intermediación de Brandes y
   comunidades por modularidad (movimiento local tipo Louvain).
7. **Exportación** (`exporters.py`) y **persistencia** (`store.py`, carpeta
   `data/`, un JSON por grafo).

## Publicar grafos en GitHub Pages

```bash
python3 publicar.py                 # publica todos los grafos de data/
python3 publicar.py revolucion      # solo los que casen con ese texto
```

Exporta cada grafo elegido como visor autónomo en `docs/grafos/` y genera
`docs/index.html`. Con Pages configurado sobre la rama `main` y la carpeta
`/docs`, basta un `git push` para actualizar el sitio.

## Estructura

```
textgraph/
├── server.py            interfaz web + API (biblioteca estándar)
├── cli.py               línea de comandos
├── pruebas.py           comprobaciones sin modelo
├── publicar.py          genera el sitio de GitHub Pages
├── iniciar.command      lanzador para macOS
├── textgraph/           el motor
│   ├── chunker.py  llm.py  prompts.py  local.py
│   ├── normalize.py  mentions.py  exhaustive.py
│   ├── analysis.py  exporters.py  model.py  pipeline.py  store.py
├── web/                 interfaz (index.html, style.css, app.js, vendor/)
├── examples/            textos de ejemplo
├── data/                grafos guardados
└── docs/                sitio publicado en GitHub Pages
```

## API HTTP

| Método y ruta | Qué hace |
|---|---|
| `GET /api/estado` | motores disponibles, modelos, precios, formatos |
| `POST /api/extraer` | lanza una extracción; devuelve el id del trabajo |
| `GET /api/trabajo/{id}` | progreso del trabajo |
| `GET /api/grafo/{id}` | grafo completo en JSON |
| `POST /api/grafo/{id}` | guarda un grafo editado |
| `DELETE /api/grafo/{id}` | borra un grafo |
| `GET /api/proyectos` | lista de grafos guardados |
| `GET /api/exportar/{id}/{formato}` | descarga en el formato indicado |

## Límites conocidos

- El texto máximo por extracción es de 400 000 caracteres; con textos muy
  largos conviene subir el tamaño de fragmento y el paralelismo.
- Los fragmentos en paralelo aceleran mucho, pero cada oleada solo conoce las
  entidades de las oleadas anteriores: con `--paralelo 1` la coherencia de
  nombres entre fragmentos es algo mejor.
- El motor `local` sirve para comparar y para trabajar sin conexión, no para
  producir grafos de calidad.
- Las aristas `coocurrencia` y `estructural` existen para cumplir el requisito
  de exhaustividad: son un andamio, no una afirmación del texto.
