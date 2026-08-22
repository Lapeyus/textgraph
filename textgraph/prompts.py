# -*- coding: utf-8 -*-
"""Prompts de extracción de grafos de conocimiento."""

TIPOS = ("PERSONA, ORGANIZACION, LUGAR, TIEMPO, EVENTO, OBRA, CONCEPTO, "
         "OBJETO, MAGNITUD, PROCESO, DISCIPLINA, OTRO")

SISTEMA = (
    "Eres un motor de extracción de grafos de conocimiento. Analizas texto y "
    "devuelves EXCLUSIVAMENTE un objeto JSON válido, sin explicaciones, sin "
    "comentarios y sin bloques de código. Nunca inventas información que no "
    "esté sostenida por el texto."
)

EXTRACCION = u"""Extrae el grafo de conocimiento COMPLETO del siguiente fragmento de texto.

## Reglas de entidades
1. EXHAUSTIVIDAD: extrae toda entidad con contenido semántico propio: personas, organizaciones, lugares, fechas y periodos, eventos, obras y documentos, conceptos y teorías, objetos, magnitudes con unidad, procesos y disciplinas. Si algo se menciona en el texto, merece un nodo.
2. NO extraigas pronombres, artículos ni referencias vacías: resuélvelos a la entidad a la que apuntan ("ella" -> "Marie Curie").
3. Usa como `label` la forma canónica más completa que aparezca en el texto ("Premio Nobel de Física", no "el Nobel"). Recoge en `aliases` las demás formas usadas.
4. `tipo` debe ser uno de: {tipos}.
5. `descripcion`: máximo 15 palabras, derivada solo del texto.
6. `evidencia`: fragmento LITERAL y contiguo del texto (copiado carácter a carácter) donde aparece la entidad.

## Reglas de relaciones
7. EXHAUSTIVIDAD: toda entidad debe participar en AL MENOS UNA relación. Antes de responder, verifica entidad por entidad que aparece como `origen` o `destino` de alguna relación. Si una queda suelta, busca en el texto con qué se conecta (aunque sea una relación de contexto como "ocurre en", "pertenece a", "se menciona junto a").
8. `etiqueta`: predicado corto en minúsculas, 1 a 4 palabras, en la lengua del texto ("descubrió", "nació en", "es parte de", "causa", "se opone a"). Evita el genérico "relacionado con" salvo que no exista nada mejor.
9. `evidencia`: fragmento LITERAL y contiguo del texto que justifica la relación.
10. `tipo`: "explicita" si el texto la afirma directamente; "implicita" si se deduce con seguridad del texto (correferencia, contexto compartido).
11. `confianza`: 0.0 a 1.0.
12. Dirección: `origen` -> `destino` debe leerse como una frase con sentido junto a la etiqueta.
13. No dupliques la misma relación en ambos sentidos.

## Formato de salida (JSON estricto)
{{"entidades":[{{"label":"...","tipo":"...","aliases":["..."],"descripcion":"...","evidencia":"..."}}],
"relaciones":[{{"origen":"...","destino":"...","etiqueta":"...","tipo":"explicita","confianza":0.9,"evidencia":"..."}}]}}

`origen` y `destino` deben coincidir EXACTAMENTE con algún `label` de la lista de entidades.
{contexto}
## Texto a analizar
<<<TEXTO
{texto}
TEXTO

Devuelve solo el JSON."""

CONTEXTO_ENTIDADES = u"""
## Entidades ya identificadas en fragmentos anteriores
Reutiliza EXACTAMENTE estos `label` cuando la misma entidad reaparezca (no crees variantes):
{lista}
"""

RECONCILIACION = u"""Un grafo de conocimiento extraído de un texto tiene entidades AISLADAS: aparecen en el texto pero ninguna relación las conecta. Toda entidad mencionada en un texto guarda alguna relación con el resto: encuéntrala.

## Entidades aisladas y su contexto textual
{aisladas}

## Entidades ya presentes en el grafo (usa sus label EXACTOS como destino)
{catalogo}

`etiqueta`: predicado corto en minúsculas, de 1 a 4 palabras, en la lengua del texto («forma parte de», «ocurre en»); nunca en MAYÚSCULAS_CON_GUIONES.

Para CADA entidad aislada devuelve una o más relaciones que la conecten con alguna entidad del grafo (o con otra entidad aislada). Usa la evidencia textual disponible; si la conexión no es explícita, apóyate en el contexto compartido y marca `tipo` como "implicita".

## Formato de salida (JSON estricto)
{{"relaciones":[{{"origen":"...","destino":"...","etiqueta":"...","tipo":"implicita","confianza":0.6,"evidencia":"..."}}]}}

Devuelve solo el JSON. No inventes entidades nuevas."""

PUENTES = u"""Un grafo de conocimiento extraído de un solo texto quedó partido en {n} grupos desconectados. Como todo procede del mismo texto, existen conexiones entre los grupos que la extracción no capturó.

## Grupos y sus entidades más relevantes
{grupos}

## Texto original (resumen de fragmentos)
{texto}

`etiqueta`: predicado corto en minúsculas, de 1 a 4 palabras, en la lengua del texto («forma parte de», «precede a»); nunca en MAYÚSCULAS_CON_GUIONES.

Propón relaciones que conecten los grupos entre sí, apoyándote en el texto. Al menos una relación por cada grupo distinto del primero, de modo que todos queden unidos al grupo 1 directa o indirectamente.

## Formato de salida (JSON estricto)
{{"relaciones":[{{"origen":"...","destino":"...","etiqueta":"...","tipo":"implicita","confianza":0.6,"evidencia":"..."}}]}}

Usa `label` EXACTOS de los listados. Devuelve solo el JSON."""

FUSION = u"""Estas parejas de entidades proceden del mismo texto y podrían designar la MISMA cosa (variantes, abreviaturas, apellido vs. nombre completo, siglas) o cosas DISTINTAS.

{parejas}

Para cada pareja decide si son la misma entidad. Si lo son, indica cuál `label` es la forma canónica (la más completa e informativa).

## Formato de salida (JSON estricto)
{{"fusiones":[{{"a":"...","b":"...","misma":true,"canonico":"..."}}]}}

Devuelve solo el JSON."""
