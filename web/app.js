/* textgraph — interfaz del visor de grafos de conocimiento */
(function () {
"use strict";

var COLORES = {
  PERSONA: "#e8743b", ORGANIZACION: "#19a979", LUGAR: "#1f77b4", TIEMPO: "#945ecf",
  EVENTO: "#e6444c", OBRA: "#c8a032", CONCEPTO: "#13a4b4", OBJETO: "#6c8893",
  MAGNITUD: "#bf399e", PROCESO: "#f5a623", DISCIPLINA: "#4e79a7", OTRO: "#9aa0a6"
};
var PALETA_COM = ["#2f6df6", "#19a979", "#e8743b", "#945ecf", "#e6444c", "#13a4b4",
  "#c8a032", "#bf399e", "#4e79a7", "#f5a623", "#6c8893", "#8bc34a"];
var ESTILO_REL = {
  explicita: { dashes: false, color: "#8a94a6", ancho: 1.6 },
  implicita: { dashes: [6, 4], color: "#e0a33c", ancho: 1.3 },
  coocurrencia: { dashes: [2, 5], color: "#b6bdc9", ancho: 1.0 },
  estructural: { dashes: [1, 6], color: "#d3d8e0", ancho: 0.8 }
};

var E = {
  grafo: null, id: null, red: null, dsNodos: null, dsAristas: null,
  seleccion: null, edicion: false, embebido: !!window.GRAFO_EMBEBIDO,
  filtros: { tipos: null, relaciones: null, conf: 0, vecindario: false, prof: 1 },
  formatos: [], sondeo: null
};

function $(s) { return document.querySelector(s); }
function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
function esc(t) {
  return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function aviso(msg, error) {
  var a = $("#aviso");
  a.textContent = msg;
  a.className = "aviso" + (error ? " error" : "");
  clearTimeout(aviso._t);
  aviso._t = setTimeout(function () { a.classList.add("oculto"); }, error ? 8000 : 3500);
}
function api(url, opciones) {
  return fetch(url, opciones).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (!r.ok) throw new Error(d.error || ("HTTP " + r.status));
      return d;
    });
  });
}

/* ------------------------------------------------------------ arranque */
function init() {
  if (E.embebido) {
    document.body.classList.add("embebido");
    $("#panel-entrada").remove();
    $("main").classList.add("sin-panel");
    $("#btn-panel").classList.add("oculto");
    $("#btn-edicion").classList.add("oculto");
    cargarGrafo(window.GRAFO_EMBEBIDO);
  } else {
    api("/api/estado").then(function (d) {
      E.formatos = d.formatos;
      E.precios = d.precios || {};
      pintarMotores(d);
      pintarMenuExportar();
      estimar();
    }).catch(function (e) { aviso("No se pudo hablar con el servidor: " + e.message, true); });
    cargarProyectos();
  }
  enlazarEventos();
}

function pintarMotores(d) {
  var sel = $("#engine"), opciones = [];
  if (d.motores["claude-cli"]) opciones.push(["claude-cli", "Claude (CLI local)"]);
  if (d.motores.api) opciones.push(["api", "Claude (API con clave)"]);
  if (d.motores["codex-cli"]) opciones.push(["codex-cli", "Codex (CLI local)"]);
  if (d.motores["gemini-cli"]) opciones.push(["gemini-cli", "Gemini (CLI local)"]);
  if (d.motores["antigravity-cli"]) opciones.push(["antigravity-cli", "Antigravity (CLI local)"]);
  opciones.push(["local", "Heurístico sin modelo (offline)"]);
  sel.innerHTML = opciones.map(function (o) {
    return '<option value="' + o[0] + '">' + esc(o[1]) + "</option>";
  }).join("");
  E.modelos = d.modelos || {};
  E.defectos = d.modelo_por_defecto || {};
  pintarModelos();
  actualizarAyudaMotor();
}

/* Cada motor tiene su propia lista de modelos (Claude o GPT). */
function pintarModelos() {
  var motor = $("#engine").value;
  var lista = (E.modelos || {})[motor] || [];
  if (!lista.length) return;                 // motor local: se conserva la lista
  $("#modelo").innerHTML = lista.map(function (x) {
    return '<option value="' + esc(x) + '"' +
      (x === (E.defectos || {})[motor] ? " selected" : "") + ">" + esc(x) + "</option>";
  }).join("");
}

function actualizarAyudaMotor() {
  var v = $("#engine").value, t = {
    "claude-cli": "Usa la CLI `claude` ya instalada y autenticada. No necesita clave de API; el coste se carga a tu cuenta de Claude.",
    "codex-cli": "Usa la CLI `codex` (OpenAI) ya instalada y autenticada. No necesita clave de API; el consumo se carga a tu cuenta de ChatGPT u OpenAI.",
    "gemini-cli": "Usa la CLI `gemini` (Google) ya instalada y autenticada. No necesita clave de API; el consumo se carga a tu cuenta de Google.",
    "antigravity-cli": "Usa la CLI `agy` de Antigravity (Google) ya instalada y autenticada. Da acceso a modelos Gemini, Claude y GPT-OSS; el consumo sale de la cuota de tu plan de Antigravity.",
    api: "Usa la Messages API con la variable ANTHROPIC_API_KEY.",
    local: "Reglas lingüísticas locales: sin coste ni red, pero mucha menos precisión. Útil para comparar."
  }[v] || "";
  $("#ayuda-motor").textContent = t;
  $("#modelo").disabled = (v === "local");
}

function cargarProyectos() {
  return api("/api/proyectos").then(function (d) {
    $("#proyectos").innerHTML = d.proyectos.length ? d.proyectos.map(function (p) {
      var f = new Date(p.modificado * 1000).toLocaleString("es");
      return '<li data-id="' + esc(p.id) + '"' + (p.id === E.id ? ' class="activo"' : "") + '>' +
        "<span><b>" + esc(p.titulo || p.id) + "</b><br><span class='tenue'>" +
        p.nodos + " nodos · " + p.aristas + " relaciones · " + esc(f) + "</span></span>" +
        '<button class="borrar" title="Borrar">✕</button></li>';
    }).join("") : '<li class="tenue" style="border:0">Todavía no hay grafos guardados.</li>';
  }).catch(function () {});
}

/* ------------------------------------------------------------ extracción */
function construir() {
  var texto = $("#texto").value.trim();
  if (!texto) { aviso("Pega primero un texto.", true); return; }
  var cuerpo = {
    texto: texto, titulo: $("#titulo").value.trim(), engine: $("#engine").value,
    modelo: $("#modelo").disabled ? "" : $("#modelo").value,
    max_chars: +$("#max_chars").value, paralelo: +$("#paralelo").value,
    exhaustividad: $("#exhaustividad").checked,
    fusion_llm: $("#fusion_llm").checked
  };
  $("#btn-construir").disabled = true;
  $("#progreso").classList.remove("oculto");
  api("/api/extraer", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo)
  }).then(function (d) { sondear(d.trabajo); })
    .catch(function (e) { fallo(e.message); });
}

function sondear(jid) {
  clearInterval(E.sondeo);
  E.sondeo = setInterval(function () {
    api("/api/trabajo/" + jid).then(function (t) {
      var pct = Math.round(100 * (t.hecho || 0) / (t.total || 1));
      $("#barra-relleno").style.width = pct + "%";
      $("#progreso-msg").textContent = t.mensaje || "";
      if (t.estado === "listo") {
        clearInterval(E.sondeo);
        $("#btn-construir").disabled = false;
        $("#progreso").classList.add("oculto");
        abrir(t.grafo_id);
        cargarProyectos();
      } else if (t.estado === "error") {
        clearInterval(E.sondeo);
        fallo(t.error || "error desconocido");
      }
    }).catch(function (e) { clearInterval(E.sondeo); fallo(e.message); });
  }, 900);
}

function fallo(msg) {
  $("#btn-construir").disabled = false;
  $("#progreso").classList.add("oculto");
  aviso("Falló la extracción: " + msg, true);
}

function abrir(gid) {
  return api("/api/grafo/" + gid).then(function (d) {
    E.id = gid;
    cargarGrafo(d);
    cargarProyectos();
  }).catch(function (e) { aviso(e.message, true); });
}


/* Estimación orientativa de llamadas y coste antes de lanzar la extracción.
   Calibrado con extracciones reales sobre textos en español: la entrada es
   ~ caracteres/3.6 + 900 por llamada (instrucciones) y la salida ronda
   4000 tokens por llamada (razonamiento) + 15 tokens por token de texto. */
function estimar() {
  var el = $("#estimacion"); if (!el) return;
  var texto = $("#texto").value || "";
  var chars = texto.length;
  if (!chars) { el.textContent = ""; return; }
  var frag = Math.max(1, Math.ceil(chars / (+$("#max_chars").value || 3500)));
  // Las pasadas de exhaustividad y de fusión solo gastan una llamada cuando
  // hacen falta, de ahí el medio punto en lugar de uno entero.
  var llamadas = frag + ($("#exhaustividad").checked ? 0.5 : 0) +
                 ($("#fusion_llm").checked ? 0.5 : 0);
  if ($("#engine").value === "local") {
    el.textContent = frag + " fragmento(s) · motor local: sin coste ni llamadas al modelo.";
    return;
  }
  var precio = (E.precios || {})[$("#modelo").value];
  // El razonamiento del modelo domina la salida y varía mucho según la
  // familia; estas constantes salen de extracciones medidas. Cada CLI añade
  // además sus propias instrucciones por llamada: `codex` ~12k tokens (en su
  // mayoría cacheados al 10 %, ~4000 efectivos) y `agy` ~13k sin cachear.
  var m = $("#modelo").value, motor = $("#engine").value;
  var razonamiento = /opus|fable|mythos/.test(m) ? 6000 :
                     /haiku/.test(m) ? 1200 :
                     /^gpt-/.test(m) ? 800 : 1800;
  var porLlamada = motor === "codex-cli" ? 4000 :
                   motor === "antigravity-cli" ? 13000 : 900;
  var tin = (chars / 3.6) + llamadas * porLlamada;
  var tout = llamadas * razonamiento + 15 * (chars / 3.6);
  var txt = frag + " fragmento(s) · ~" + Math.round(llamadas) + " llamada(s) al modelo";
  if (precio) {
    var usd = (tin / 1e6) * precio[0] + (tout / 1e6) * precio[1];
    var rango = "$" + (usd * 0.6).toFixed(2) + "–$" + (usd * 1.8).toFixed(2);
    var cuenta = {
      "claude-cli": "con sesión de suscripción se descuenta de los límites del plan",
      "codex-cli": "con sesión de ChatGPT se descuenta de los límites del plan",
      "gemini-cli": "con sesión de Google se descuenta de la cuota del plan",
      "antigravity-cli": "se descuenta de la cuota de tu plan de Antigravity"
    }[motor];
    txt += cuenta
      ? " · consumo equivalente a " + rango + " de API; " + cuenta + ", no se factura aparte"
      : " · coste orientativo " + rango;
  }
  el.textContent = txt;
}

/* ------------------------------------------------------------ pintado */
function cargarGrafo(d) {
  E.grafo = d;
  E.filtros.tipos = new Set(Object.keys(d.stats.por_tipo_entidad || {}));
  E.filtros.relaciones = new Set(Object.keys(d.stats.por_tipo_relacion || {}));
  E.seleccion = null;
  $("#vacio").classList.add("oculto");
  document.title = (d.title || "textgraph") + " · textgraph";
  pintarRed();
  pintarChips();
  pintarLeyenda();
  pintarFiltros();
  pintarTexto();
  pintarTablas();
  pintarInforme();
  $("#tab-detalle").innerHTML = '<p class="tenue">Selecciona un nodo o una relación ' +
    "para ver su detalle y las evidencias textuales que la sostienen.</p>";
}

function nodoVis(n) {
  var color = $("#color-por") && $("#color-por").value === "comunidad"
    ? PALETA_COM[(n.metrics && n.metrics.comunidad || 0) % PALETA_COM.length]
    : (COLORES[n.type] || COLORES.OTRO);
  var rel = (n.metrics && n.metrics.pagerank_rel) || 0.2;
  return {
    id: n.id, label: n.label, tipo: n.type,
    value: Math.max(1, (n.metrics && n.metrics.grado) || 1),
    size: 10 + 26 * Math.sqrt(rel),
    color: { background: color, border: "#ffffff",
             highlight: { background: color, border: "#1c2430" } },
    borderWidth: 2,
    font: { size: 12 + 8 * rel, color: "#1c2430", strokeWidth: 4, strokeColor: "#f6f7f9",
            face: "-apple-system, Segoe UI, Inter, sans-serif" },
    title: n.type + (n.description ? " · " + n.description : "")
  };
}

function aristaVis(e, i) {
  var s = ESTILO_REL[e.type] || ESTILO_REL.explicita;
  return {
    id: e.id || ("e" + i), from: e.source, to: e.target, label: e.label, tipo: e.type,
    conf: e.confidence,
    arrows: { to: { enabled: e.directed !== false, scaleFactor: 0.5 } },
    dashes: s.dashes, width: s.ancho + 1.4 * (e.confidence || 0.5),
    color: { color: s.color, highlight: "#2f6df6", opacity: 0.9 },
    font: { size: 10, color: "#697586", strokeWidth: 4, strokeColor: "#f6f7f9",
            align: "horizontal" },
    smooth: { type: "continuous", roundness: 0.2 },
    title: e.label + " (" + e.type + (e.evidence ? ") — " + e.evidence : ")")
  };
}

/* Constantes de la física según el nivel de separación (0 = disposición
   compacta normal): a más nivel, más repulsión entre nodos, muelles más
   largos y menos gravedad hacia el centro, así el grafo se expande sin
   perder ninguna conexión. */
function fisicaBarnesHut(nivel) {
  return { gravitationalConstant: -5200 * Math.pow(1.6, nivel),
           centralGravity: 0.42 / Math.pow(1.5, nivel),
           springLength: 115 * Math.pow(1.3, nivel),
           springConstant: 0.035, damping: 0.4,
           avoidOverlap: Math.min(1, 0.28 + 0.2 * nivel) };
}

function pintarRed() {
  var g = E.grafo;
  E.dsNodos = new vis.DataSet(g.nodes.map(nodoVis));
  E.dsAristas = new vis.DataSet(g.edges.map(aristaVis));
  E.separacion = 0;
  actualizarBotonSeparar();
  var opciones = {
    nodes: { shape: "dot", scaling: { min: 8, max: 40 }, shadow: false },
    edges: { selectionWidth: 2.5, hoverWidth: 0.6 },
    physics: {
      enabled: $("#fisica").checked,
      solver: "barnesHut",
      barnesHut: fisicaBarnesHut(0),
      stabilization: { iterations: 260, updateInterval: 30 }
    },
    interaction: { hover: true, multiselect: true, tooltipDelay: 220,
                   navigationButtons: false, keyboard: false },
    layout: { improvedLayout: g.nodes.length < 300 }
  };
  if (E.red) E.red.destroy();
  E.red = new vis.Network($("#red"), { nodes: E.dsNodos, edges: E.dsAristas }, opciones);

  E.red.on("click", function (p) {
    if (p.nodes.length) mostrarNodo(p.nodes[0]);
    else if (p.edges.length) mostrarArista(p.edges[0]);
    else { E.seleccion = null; aplicarFiltros(); }
  });
  E.red.on("doubleClick", function (p) {
    if (p.nodes.length) E.red.focus(p.nodes[0], { scale: 1.3, animation: true });
  });
  E.red.once("stabilizationIterationsDone", function () { encajar(true); });
  // Red de seguridad: si la física sigue moviendo los nodos tras estabilizar,
  // un segundo encaje deja el grafo entero a la vista.
  clearTimeout(pintarRed._t);
  pintarRed._t = setTimeout(function () {
    if (E.red && !E.red.getSelectedNodes().length) encajar(true);
  }, 1900);
  aplicarEtiquetas();
  aplicarFiltros();
}

/* Separa los nodos amontonados: sube la repulsión de la física y da un
   empujón radial inmediato desde el centro (visible incluso con la física
   apagada). Cada clic separa más; pasado el nivel máximo, el siguiente clic
   vuelve a la disposición compacta. Las conexiones no se tocan. */
function separar() {
  if (!E.red) return;
  var previo = E.separacion || 0;
  E.separacion = previo >= 4 ? 0 : previo + 1;
  // factor del empujón radial; al reiniciar deshace la expansión acumulada
  var factor = E.separacion ? 1.35 : Math.pow(1.35, -previo);
  var pos = E.red.getPositions(), ids = Object.keys(pos);
  var cx = 0, cy = 0;
  ids.forEach(function (id) { cx += pos[id].x; cy += pos[id].y; });
  cx /= ids.length || 1; cy /= ids.length || 1;
  ids.forEach(function (id) {
    E.red.moveNode(id, cx + (pos[id].x - cx) * factor,
                   cy + (pos[id].y - cy) * factor);
  });
  E.red.setOptions({ physics: { barnesHut: fisicaBarnesHut(E.separacion) } });
  if ($("#fisica").checked) {
    E.red.startSimulation();
    E.red.once("stabilized", function () { encajar(true); });
  }
  actualizarBotonSeparar();
  // encaje de cortesía mientras la física sigue moviendo los nodos
  clearTimeout(separar._t);
  separar._t = setTimeout(function () { encajar(true); }, 700);
}

function actualizarBotonSeparar() {
  var b = $("#btn-separar");
  if (!b) return;
  b.textContent = E.separacion ? "✥ Separar ×" + E.separacion : "✥ Separar";
  b.title = E.separacion >= 4
    ? "Nivel máximo: otro clic vuelve a la disposición compacta"
    : "Aleja los nodos entre sí para deshacer amontonamientos (cada clic separa más)";
}

/* Encaja el grafo en pantalla. Solo se limita el acercamiento máximo: en
   grafos pequeños vis-network se acerca tanto que se pierde el contexto. */
function encajar(suave) {
  if (!E.red) return;
  E.red.fit({ animation: false });
  var s = E.red.getScale();
  var objetivo = Math.min(1.1, s);
  if (Math.abs(objetivo - s) > 0.01) {
    E.red.moveTo({ scale: objetivo, position: E.red.getViewPosition(),
                   animation: suave ? { duration: 300 } : false });
  }
}

function aplicarEtiquetas() {
  var ver = $("#ver-etiquetas").checked;
  E.dsAristas.update(E.dsAristas.get().map(function (a) {
    return { id: a.id, font: { size: ver ? 10 : 0 } };
  }));
}

/* ------------------------------------------------------------ filtros */
function pintarFiltros() {
  var g = E.grafo;
  $("#filtro-tipos").innerHTML = Object.keys(g.stats.por_tipo_entidad).map(function (t) {
    return '<label><input type="checkbox" checked data-tipo="' + t + '">' +
      '<span class="punto" style="background:' + (COLORES[t] || COLORES.OTRO) + '"></span>' +
      t.toLowerCase() + ' <span class="tenue">(' + g.stats.por_tipo_entidad[t] + ")</span></label>";
  }).join("");
  $("#filtro-relaciones").innerHTML = Object.keys(g.stats.por_tipo_relacion).map(function (t) {
    return '<label><input type="checkbox" checked data-rel="' + t + '">' + t +
      ' <span class="tenue">(' + g.stats.por_tipo_relacion[t] + ")</span></label>";
  }).join("");
  $$("#filtro-tipos input").forEach(function (c) {
    c.onchange = function () {
      c.checked ? E.filtros.tipos.add(c.dataset.tipo) : E.filtros.tipos.delete(c.dataset.tipo);
      aplicarFiltros();
    };
  });
  $$("#filtro-relaciones input").forEach(function (c) {
    c.onchange = function () {
      c.checked ? E.filtros.relaciones.add(c.dataset.rel) : E.filtros.relaciones.delete(c.dataset.rel);
      aplicarFiltros();
    };
  });
}

function vecindario(id, prof) {
  var vistos = new Set([id]), frontera = [id];
  var ady = {};
  E.grafo.edges.forEach(function (e) {
    (ady[e.source] = ady[e.source] || []).push(e.target);
    (ady[e.target] = ady[e.target] || []).push(e.source);
  });
  for (var d = 0; d < prof; d++) {
    var nueva = [];
    frontera.forEach(function (n) {
      (ady[n] || []).forEach(function (v) {
        if (!vistos.has(v)) { vistos.add(v); nueva.push(v); }
      });
    });
    frontera = nueva;
  }
  return vistos;
}

function aplicarFiltros() {
  if (!E.grafo) return;
  var f = E.filtros;
  var visiblesPorTipo = new Set();
  E.grafo.nodes.forEach(function (n) { if (f.tipos.has(n.type)) visiblesPorTipo.add(n.id); });
  var entorno = (f.vecindario && E.seleccion && E.seleccion.tipo === "nodo")
    ? vecindario(E.seleccion.id, f.prof) : null;

  E.dsNodos.update(E.grafo.nodes.map(function (n) {
    var oculto = !visiblesPorTipo.has(n.id) || (entorno && !entorno.has(n.id));
    return { id: n.id, hidden: oculto };
  }));
  E.dsAristas.update(E.grafo.edges.map(function (e, i) {
    var oculto = !f.relaciones.has(e.type) || (e.confidence || 0) < f.conf - 1e-9 ||
      !visiblesPorTipo.has(e.source) || !visiblesPorTipo.has(e.target) ||
      (entorno && (!entorno.has(e.source) || !entorno.has(e.target)));
    return { id: e.id || ("e" + i), hidden: oculto };
  }));
  pintarChips();
}

/* ------------------------------------------------------------ paneles */
function pintarChips() {
  var g = E.grafo; if (!g) return;
  var st = g.stats, meta = g.meta || {}, uso = meta.uso || {};
  var visN = E.dsNodos ? E.dsNodos.get().filter(function (n) { return !n.hidden; }).length : st.nodos;
  var chips = [
    ["Nodos", visN === st.nodos ? st.nodos : visN + "/" + st.nodos, ""],
    ["Relaciones", st.aristas, ""],
    ["Componentes", st.componentes, st.componentes === 1 ? "ok" : "alerta"],
    ["Sin conectar", st.huerfanos, st.huerfanos === 0 ? "ok" : "alerta"],
    ["Densidad", st.densidad, ""]
  ];
  if (uso.coste_usd != null && uso.coste_usd > 0)
    chips.push(["Coste equiv.", "$" + uso.coste_usd.toFixed(3), "",
                "Lo que habrían costado estos tokens a tarifa de API. Con la CLI " +
                "autenticada por suscripción no es un cargo: el uso se descuenta " +
                "de los límites de tu plan."]);
  if (meta.segundos) chips.push(["Tiempo", meta.segundos + " s", ""]);
  if (meta.modelo) chips.push(["Modelo", meta.modelo, ""]);
  $("#chips").innerHTML = chips.map(function (c) {
    return '<span class="chip ' + c[2] + '"' +
      (c[3] ? ' title="' + esc(c[3]) + '"' : "") + ">" + c[0] +
      " <b>" + esc(c[1]) + "</b></span>";
  }).join("");
  $("#subtitulo").textContent = g.title || "del texto al grafo de conocimiento";
}

function pintarLeyenda() {
  var tipos = Object.keys(E.grafo.stats.por_tipo_entidad);
  $("#leyenda").innerHTML = tipos.map(function (t) {
    return '<span><i class="punto" style="background:' + (COLORES[t] || COLORES.OTRO) +
      '"></i>' + t.toLowerCase() + "</span>";
  }).join("") + '<span style="width:100%;border-top:1px solid var(--borde);margin-top:2px;padding-top:4px">' +
    "— explícita · – – deducida · ·· co-ocurrencia · ⋯ estructural</span>";
}

function nodo(id) {
  return E.grafo.nodes.filter(function (n) { return n.id === id; })[0];
}

function mostrarNodo(id) {
  var n = nodo(id); if (!n) return;
  E.seleccion = { tipo: "nodo", id: id };
  activarPestana("detalle");
  var m = n.metrics || {};
  var salientes = E.grafo.edges.filter(function (e) { return e.source === id; });
  var entrantes = E.grafo.edges.filter(function (e) { return e.target === id; });

  var html = '<div class="titulo-nodo"><h2>' + esc(n.label) + "</h2></div>" +
    '<span class="tipo-badge" style="background:' + (COLORES[n.type] || COLORES.OTRO) + '">' +
    n.type + "</span>";
  if (n.description) html += "<p>" + esc(n.description) + "</p>";
  if (n.aliases && n.aliases.length)
    html += '<p class="tenue">También aparece como: ' + n.aliases.map(esc).join(" · ") + "</p>";

  html += '<div class="metricas">' +
    metrica(m.grado || 0, "grado") +
    metrica((m.pagerank_rel != null ? Math.round(m.pagerank_rel * 100) : 0) + "%", "centralidad") +
    metrica((m.intermediacion_rel != null ? Math.round(m.intermediacion_rel * 100) : 0) + "%", "intermediación") +
    metrica(n.mentions ? n.mentions.length : 0, "menciones") + "</div>";

  if (salientes.length) html += bloqueRel("Relaciones que parten de aquí", salientes, "target");
  if (entrantes.length) html += bloqueRel("Relaciones que llegan aquí", entrantes, "source");

  if (n.mentions && n.mentions.length) {
    html += '<div class="bloque"><h3>Apariciones en el texto</h3>' +
      n.mentions.slice(0, 12).map(function (mm, i) {
        return '<div class="rel"><a class="enlace" data-mencion="' + mm.start + '">«' +
          esc(mm.quote) + "»</a><span class='ev'>" + esc(mm.contexto || "") + "</span></div>";
      }).join("") + "</div>";
  }
  $("#tab-detalle").innerHTML = html;
  enlazarDetalle();
  if (E.red) E.red.selectNodes([id], true);
  if (E.filtros.vecindario) aplicarFiltros();
  resaltarTexto(id);
}

function metrica(v, etiqueta) {
  return '<div class="metrica"><b>' + esc(v) + "</b><span>" + etiqueta + "</span></div>";
}

function bloqueRel(titulo, aristas, campo) {
  return '<div class="bloque"><h3>' + titulo + " (" + aristas.length + ")</h3>" +
    aristas.map(function (e) {
      var otro = nodo(e[campo]);
      return '<div class="rel ' + e.type + '">' +
        '<span class="pred" data-arista="' + esc(e.id) + '">' + esc(e.label) + "</span> " +
        (campo === "target" ? "→ " : "← ") +
        '<a class="enlace" data-nodo="' + esc(e[campo]) + '">' +
        esc(otro ? otro.label : e[campo]) + "</a>" +
        (e.evidence ? '<span class="ev">«' + esc(e.evidence) + "»</span>" : "") + "</div>";
    }).join("") + "</div>";
}

function mostrarArista(id) {
  var e = E.grafo.edges.filter(function (x) { return (x.id || "") === id; })[0];
  if (!e) return;
  E.seleccion = { tipo: "arista", id: id };
  activarPestana("detalle");
  var a = nodo(e.source), b = nodo(e.target);
  var explicacion = {
    explicita: "El texto afirma esta relación de forma directa.",
    implicita: "Deducida por el modelo a partir del contexto o de correferencias.",
    coocurrencia: "Ambas entidades comparten oración, pero el texto no enuncia un predicado.",
    estructural: "Enlace de último recurso para que ninguna entidad quede aislada; el vínculo semántico es débil."
  }[e.type] || "";
  $("#tab-detalle").innerHTML =
    '<div class="titulo-nodo"><h2>' + esc(e.label) + "</h2></div>" +
    '<p><a class="enlace" data-nodo="' + esc(e.source) + '">' + esc(a ? a.label : e.source) +
    "</a> → <a class='enlace' data-nodo='" + esc(e.target) + "'>" + esc(b ? b.label : e.target) + "</a></p>" +
    '<div class="metricas">' + metrica(e.type, "tipo") +
    metrica(Math.round((e.confidence || 0) * 100) + "%", "confianza") + "</div>" +
    (e.evidence ? '<div class="bloque"><h3>Evidencia textual</h3><div class="rel ' + e.type +
      '">«' + esc(e.evidence) + "»</div></div>" : "") +
    '<p class="tenue">' + explicacion + "</p>";
  enlazarDetalle();
  if (E.red) E.red.selectEdges([id]);
}

function enlazarDetalle() {
  $$("#tab-detalle [data-nodo]").forEach(function (a) {
    a.onclick = function () { mostrarNodo(a.dataset.nodo); };
  });
  $$("#tab-detalle [data-arista]").forEach(function (a) {
    a.onclick = function () { mostrarArista(a.dataset.arista); };
  });
  $$("#tab-detalle [data-mencion]").forEach(function (a) {
    a.onclick = function () {
      activarPestana("texto");
      var m = $('#tab-texto mark[data-start="' + a.dataset.mencion + '"]');
      if (m) { m.scrollIntoView({ block: "center", behavior: "smooth" });
               m.classList.add("activa"); }
    };
  });
}

/* ------------------------------------------------------------ texto */
function pintarTexto() {
  var g = E.grafo, texto = g.text || "";
  var marcas = [];
  g.nodes.forEach(function (n) {
    (n.mentions || []).forEach(function (m) {
      if (typeof m.start === "number") marcas.push({ ini: m.start, fin: m.end, id: n.id });
    });
  });
  marcas.sort(function (a, b) { return a.ini - b.ini; });
  var out = "", pos = 0;
  marcas.forEach(function (m) {
    if (m.ini < pos) return;
    out += esc(texto.slice(pos, m.ini)) +
      '<mark data-nodo="' + esc(m.id) + '" data-start="' + m.ini + '">' +
      esc(texto.slice(m.ini, m.fin)) + "</mark>";
    pos = m.fin;
  });
  out += esc(texto.slice(pos));
  $("#tab-texto").innerHTML = out ||
    '<p class="tenue">No hay texto asociado a este grafo.</p>';
  $$("#tab-texto mark").forEach(function (m) {
    m.onclick = function () { mostrarNodo(m.dataset.nodo); };
  });
}

function resaltarTexto(id) {
  $$("#tab-texto mark").forEach(function (m) {
    m.classList.toggle("activa", m.dataset.nodo === id);
  });
}

/* ------------------------------------------------------------ tablas */
function pintarTablas() {
  var g = E.grafo;
  var nodos = g.nodes.slice().sort(function (a, b) {
    return ((b.metrics || {}).grado || 0) - ((a.metrics || {}).grado || 0);
  });
  var html = "<h3 class='bloque'>Entidades (" + g.nodes.length + ")</h3>" +
    "<table><thead><tr><th>Entidad</th><th>Tipo</th><th>Grado</th><th>Menc.</th></tr></thead><tbody>" +
    nodos.map(function (n) {
      return '<tr data-nodo="' + esc(n.id) + '"><td>' + esc(n.label) + "</td><td>" +
        '<span class="punto" style="background:' + (COLORES[n.type] || COLORES.OTRO) +
        ';margin-right:4px"></span>' + n.type.toLowerCase() + "</td><td>" +
        ((n.metrics || {}).grado || 0) + "</td><td>" + (n.mentions || []).length +
        "</td></tr>";
    }).join("") + "</tbody></table>" +
    "<h3 class='bloque'>Relaciones (" + g.edges.length + ")</h3>" +
    "<table><thead><tr><th>Origen</th><th>Predicado</th><th>Destino</th><th>Tipo</th></tr></thead><tbody>" +
    g.edges.map(function (e) {
      var a = nodo(e.source), b = nodo(e.target);
      return '<tr data-arista="' + esc(e.id) + '"><td>' + esc(a ? a.label : e.source) +
        "</td><td>" + esc(e.label) + "</td><td>" + esc(b ? b.label : e.target) +
        "</td><td>" + e.type.slice(0, 4) + "</td></tr>";
    }).join("") + "</tbody></table>";
  $("#tab-tablas").innerHTML = html;
  $$("#tab-tablas [data-nodo]").forEach(function (tr) {
    tr.onclick = function () { mostrarNodo(tr.dataset.nodo); };
  });
  $$("#tab-tablas [data-arista]").forEach(function (tr) {
    tr.onclick = function () { mostrarArista(tr.dataset.arista); };
  });
}

function pintarInforme() {
  var g = E.grafo, meta = g.meta || {}, ex = meta.exhaustividad || {}, uso = meta.uso || {};
  var filas = [
    ["Entidades", g.stats.nodos], ["Relaciones", g.stats.aristas],
    ["Componentes conexos", g.stats.componentes],
    ["Entidades sin conectar", g.stats.huerfanos],
    ["Densidad", g.stats.densidad], ["Comunidades", meta.comunidades || "—"],
    ["Motor", meta.motor || "—"], ["Modelo", meta.modelo || "—"],
    ["Llamadas al modelo", uso.llamadas != null ? uso.llamadas : "—"],
    ["Coste equivalente en API", uso.coste_usd != null ? "$" + uso.coste_usd : "—"],
    ["Tiempo total", (meta.segundos || "—") + " s"]
  ];
  var html = "<h3 class='bloque'>Resumen</h3><table><tbody>" + filas.map(function (f) {
    return "<tr><td>" + f[0] + "</td><td><b>" + esc(f[1]) + "</b></td></tr>";
  }).join("") + "</tbody></table>";

  html += "<h3 class='bloque'>Cómo se garantizó la exhaustividad</h3><table><tbody>" +
    [["Sueltas al terminar la extracción", ex.huerfanos_iniciales],
     ["Conectadas por co-ocurrencia", ex.por_coocurrencia],
     ["Conectadas por el modelo", ex.por_modelo],
     ["Conectadas por fragmento", ex.por_fragmento],
     ["Conectadas por enlace estructural", ex.por_estructura],
     ["Puentes entre componentes", ex.puentes],
     ["Sueltas al final", ex.huerfanos_finales],
     ["Componentes al final", ex.componentes_finales]].map(function (f) {
      return "<tr><td>" + f[0] + "</td><td><b>" + (f[1] != null ? f[1] : "—") + "</b></td></tr>";
    }).join("") + "</tbody></table>";

  if (g.log && g.log.length) {
    html += "<h3 class='bloque'>Registro de decisiones (" + g.log.length + ")</h3>" +
      "<div class='tenue' style='font-family:var(--mono);font-size:11.5px'>" +
      g.log.map(function (l) { return "· " + esc(l); }).join("<br>") + "</div>";
  }
  $("#tab-informe").innerHTML = html;
}

function activarPestana(nombre) {
  $$(".pestana").forEach(function (b) { b.classList.toggle("activa", b.dataset.tab === nombre); });
  ["detalle", "texto", "tablas", "informe"].forEach(function (t) {
    $("#tab-" + t).classList.toggle("oculto", t !== nombre);
  });
}

/* ------------------------------------------------------------ exportar */
function pintarMenuExportar() {
  $("#menu-exportar").innerHTML = E.formatos.map(function (f) {
    return '<a href="#" data-fmt="' + f.id + '"><b>' + esc(f.nombre) + "</b> " +
      "<code class='tenue'>" + esc(f.ext) + "</code><small>" + esc(f.uso) + "</small></a>";
  }).join("");
  $$("#menu-exportar a").forEach(function (a) {
    a.onclick = function (ev) {
      ev.preventDefault();
      if (!E.id) { aviso("Construye o abre un grafo primero.", true); return; }
      window.location = "/api/exportar/" + E.id + "/" + a.dataset.fmt;
      $("#menu-exportar").classList.remove("abierto");
    };
  });
}

function descargarJSONLocal() {
  var b = new Blob([JSON.stringify(E.grafo, null, 2)], { type: "application/json" });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(b);
  a.download = (E.grafo.title || "grafo") + ".json";
  a.click();
}

/* ------------------------------------------------------------ edición */
function guardarCambios() {
  if (!E.id) { aviso("Este grafo aún no está guardado.", true); return; }
  api("/api/grafo/" + E.id, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(E.grafo)
  }).then(function () { aviso("Cambios guardados."); cargarProyectos(); })
    .catch(function (e) { aviso(e.message, true); });
}

function nuevaEntidad() {
  var label = prompt("Nombre de la nueva entidad:");
  if (!label) return;
  var tipo = (prompt("Tipo (PERSONA, ORGANIZACION, LUGAR, TIEMPO, EVENTO, OBRA, " +
    "CONCEPTO, OBJETO, MAGNITUD, PROCESO, DISCIPLINA, OTRO):", "CONCEPTO") || "OTRO").toUpperCase();
  var id = "manual_" + label.toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 40) +
    "_" + Math.random().toString(36).slice(2, 6);
  var n = { id: id, label: label, type: COLORES[tipo] ? tipo : "OTRO", aliases: [],
            description: "", mentions: [], chunks: [], metrics: { grado: 0 } };
  E.grafo.nodes.push(n);
  E.grafo.stats.nodos++;
  E.grafo.stats.por_tipo_entidad[n.type] = (E.grafo.stats.por_tipo_entidad[n.type] || 0) + 1;
  E.filtros.tipos.add(n.type);
  E.dsNodos.add(nodoVis(n));
  pintarFiltros(); pintarTablas(); pintarLeyenda(); pintarChips();
  aviso("Entidad añadida. Recuerda guardar.");
}

function nuevaRelacion() {
  var sel = E.red ? E.red.getSelectedNodes() : [];
  if (sel.length !== 2) { aviso("Selecciona exactamente dos nodos (Ctrl/⌘ + clic).", true); return; }
  var label = prompt("Predicado de la relación (de «" + nodo(sel[0]).label +
    "» a «" + nodo(sel[1]).label + "»):");
  if (!label) return;
  var e = { id: "manual_" + Math.random().toString(36).slice(2, 8), source: sel[0],
            target: sel[1], label: label, type: "explicita", evidence: "(añadida a mano)",
            confidence: 1, directed: true, chunks: [] };
  E.grafo.edges.push(e);
  E.grafo.stats.aristas++;
  E.grafo.stats.por_tipo_relacion.explicita = (E.grafo.stats.por_tipo_relacion.explicita || 0) + 1;
  E.filtros.relaciones.add("explicita");
  E.dsAristas.add(aristaVis(e, 0));
  pintarFiltros(); pintarTablas(); pintarChips();
  aviso("Relación añadida. Recuerda guardar.");
}

function borrarSeleccion() {
  var nodos = E.red.getSelectedNodes(), aristas = E.red.getSelectedEdges();
  if (!nodos.length && !aristas.length) { aviso("No hay nada seleccionado.", true); return; }
  if (!confirm("¿Borrar " + nodos.length + " nodo(s) y " + aristas.length + " relación(es)?")) return;
  E.grafo.nodes = E.grafo.nodes.filter(function (n) { return nodos.indexOf(n.id) < 0; });
  E.grafo.edges = E.grafo.edges.filter(function (e) {
    return aristas.indexOf(e.id) < 0 && nodos.indexOf(e.source) < 0 && nodos.indexOf(e.target) < 0;
  });
  E.grafo.stats.nodos = E.grafo.nodes.length;
  E.grafo.stats.aristas = E.grafo.edges.length;
  cargarGrafo(E.grafo);
  aviso("Elementos borrados. Recuerda guardar.");
}

/* ------------------------------------------------------------ eventos */
function enlazarEventos() {
  var t = $("#texto");
  if (t) {
    t.addEventListener("input", function () {
      $("#contador").textContent = t.value.length.toLocaleString("es") + " caracteres";
    });
    $("#archivo").addEventListener("change", function (ev) {
      var f = ev.target.files[0]; if (!f) return;
      var r = new FileReader();
      r.onload = function () {
        t.value = r.result;
        t.dispatchEvent(new Event("input"));
        if (!$("#titulo").value) $("#titulo").value = f.name.replace(/\.[^.]+$/, "");
      };
      r.readAsText(f);
    });
    $("#btn-ejemplo").onclick = function () {
      fetch("ejemplo.txt").then(function (r) { return r.text(); }).then(function (x) {
        t.value = x; t.dispatchEvent(new Event("input"));
      }).catch(function () { aviso("No se encontró el ejemplo.", true); });
    };
    $("#btn-construir").onclick = construir;
    $("#engine").onchange = function () { pintarModelos(); actualizarAyudaMotor(); estimar(); };
    $("#max_chars").oninput = function () {
      $("#v-frag").textContent = this.value; estimar();
    };
    $("#paralelo").oninput = function () { $("#v-par").textContent = this.value; };
    $("#modelo").onchange = estimar;
    $("#exhaustividad").onchange = estimar;
    $("#fusion_llm").onchange = estimar;
    t.addEventListener("input", estimar);
    $("#proyectos").onclick = function (ev) {
      var li = ev.target.closest("li[data-id]"); if (!li) return;
      if (ev.target.classList.contains("borrar")) {
        if (!confirm("¿Borrar este grafo?")) return;
        api("/api/grafo/" + li.dataset.id, { method: "DELETE" }).then(cargarProyectos);
      } else abrir(li.dataset.id);
    };
  }

  $("#btn-panel").onclick = function () { $("main").classList.toggle("sin-panel"); };
  $("#btn-exportar").onclick = function () {
    if (E.embebido) { descargarJSONLocal(); return; }
    $("#menu-exportar").classList.toggle("abierto");
  };
  document.addEventListener("click", function (ev) {
    if (!ev.target.closest(".menu")) $("#menu-exportar").classList.remove("abierto");
  });

  $$(".pestana").forEach(function (b) {
    b.onclick = function () { activarPestana(b.dataset.tab); };
  });

  $("#btn-filtros").onclick = function () {
    $("#filtros").classList.toggle("oculto");
    $("#edicion").classList.add("oculto");
  };
  $("#btn-edicion").onclick = function () {
    $("#edicion").classList.toggle("oculto");
    $("#filtros").classList.add("oculto");
  };
  $("#btn-ajustar").onclick = function () { encajar(true); };
  $("#btn-separar").onclick = separar;
  $("#ver-etiquetas").onchange = aplicarEtiquetas;
  $("#fisica").onchange = function () {
    if (E.red) E.red.setOptions({ physics: { enabled: this.checked } });
  };
  $("#color-por").onchange = function () {
    if (!E.grafo) return;
    E.dsNodos.update(E.grafo.nodes.map(nodoVis));
  };
  $("#disposicion").onchange = function () { aplicarDisposicion(this.value); };
  $("#conf-min").oninput = function () {
    E.filtros.conf = +this.value;
    $("#v-conf").textContent = (+this.value).toFixed(2);
    aplicarFiltros();
  };
  $("#solo-vecindario").onchange = function () {
    E.filtros.vecindario = this.checked; aplicarFiltros();
  };
  $("#profundidad").oninput = function () {
    E.filtros.prof = +this.value; $("#v-prof").textContent = this.value;
    if (E.filtros.vecindario) aplicarFiltros();
  };
  $("#btn-reset-filtros").onclick = function () {
    $$("#filtro-tipos input,#filtro-relaciones input").forEach(function (c) { c.checked = true; });
    E.filtros.tipos = new Set(Object.keys(E.grafo.stats.por_tipo_entidad));
    E.filtros.relaciones = new Set(Object.keys(E.grafo.stats.por_tipo_relacion));
    E.filtros.conf = 0; $("#conf-min").value = 0; $("#v-conf").textContent = "0.00";
    E.filtros.vecindario = false; $("#solo-vecindario").checked = false;
    aplicarFiltros();
  };
  $("#buscar").oninput = function () {
    var q = this.value.trim().toLowerCase();
    if (!E.grafo) return;
    if (!q) { E.red.unselectAll(); E.dsNodos.update(E.grafo.nodes.map(nodoVis)); return; }
    var hits = E.grafo.nodes.filter(function (n) {
      return n.label.toLowerCase().indexOf(q) >= 0 ||
        (n.aliases || []).join(" ").toLowerCase().indexOf(q) >= 0 ||
        (n.description || "").toLowerCase().indexOf(q) >= 0;
    });
    E.dsNodos.update(E.grafo.nodes.map(function (n) {
      var base = nodoVis(n);
      var hit = hits.some(function (h) { return h.id === n.id; });
      base.opacity = hit ? 1 : 0.25;
      if (hit) base.borderWidth = 4;
      return base;
    }));
    if (hits.length) {
      E.red.selectNodes(hits.map(function (h) { return h.id; }));
      if (hits.length === 1) mostrarNodo(hits[0].id);
    }
  };
  if ($("#btn-add-nodo")) {
    $("#btn-add-nodo").onclick = nuevaEntidad;
    $("#btn-add-arista").onclick = nuevaRelacion;
    $("#btn-borrar-sel").onclick = borrarSeleccion;
    $("#btn-guardar").onclick = guardarCambios;
  }
}

function aplicarDisposicion(modo) {
  if (!E.red || !E.grafo) return;
  if (modo === "fuerza") {
    E.red.setOptions({ layout: { hierarchical: { enabled: false } },
                       physics: { enabled: $("#fisica").checked } });
    E.dsNodos.update(E.grafo.nodes.map(function (n) {
      return { id: n.id, fixed: false, x: undefined, y: undefined };
    }));
    E.red.stabilize();
  } else if (modo === "jerarquica") {
    E.red.setOptions({
      layout: { hierarchical: { enabled: true, direction: "UD", sortMethod: "hubsize",
                                levelSeparation: 140, nodeSpacing: 130, shakeTowards: "roots" } }
    });
  } else if (modo === "radial") {
    E.red.setOptions({ layout: { hierarchical: { enabled: false } }, physics: { enabled: false } });
    var centro = E.grafo.nodes.slice().sort(function (a, b) {
      return ((b.metrics || {}).pagerank || 0) - ((a.metrics || {}).pagerank || 0);
    })[0];
    if (!centro) return;
    var niveles = {}, cola = [centro.id], vis_ = {};
    vis_[centro.id] = 0;
    var ady = {};
    E.grafo.edges.forEach(function (e) {
      (ady[e.source] = ady[e.source] || []).push(e.target);
      (ady[e.target] = ady[e.target] || []).push(e.source);
    });
    while (cola.length) {
      var cur = cola.shift();
      (ady[cur] || []).forEach(function (v) {
        if (vis_[v] === undefined) { vis_[v] = vis_[cur] + 1; cola.push(v); }
      });
    }
    E.grafo.nodes.forEach(function (n) {
      var d = vis_[n.id] === undefined ? 5 : vis_[n.id];
      (niveles[d] = niveles[d] || []).push(n.id);
    });
    var actualizaciones = [];
    Object.keys(niveles).forEach(function (d) {
      var lst = niveles[d], radio = 260 * (+d);
      lst.forEach(function (id, i) {
        var ang = (2 * Math.PI * i) / lst.length + (+d) * 0.4;
        actualizaciones.push({ id: id, x: radio * Math.cos(ang), y: radio * Math.sin(ang),
                               fixed: { x: true, y: true } });
      });
    });
    E.dsNodos.update(actualizaciones);
    encajar(true);
    $("#fisica").checked = false;
  }
}

// Se expone el estado para depurar desde la consola del navegador.
window.textgraph = E;
document.addEventListener("DOMContentLoaded", init);
})();
