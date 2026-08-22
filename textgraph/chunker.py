"""Segmentación del texto en oraciones y fragmentos solapados."""

import re

ABREVIATURAS = {
    "sr", "sra", "srta", "dr", "dra", "prof", "profa", "ing", "lic", "mtro",
    "av", "avda", "c", "cf", "cia", "ed", "eds", "ej", "etc", "fig", "figs",
    "núm", "num", "pág", "pags", "págs", "pp", "vol", "vs", "aprox", "art",
    "ss", "s", "a.c", "d.c", "ee", "uu", "ss.mm", "mr", "mrs", "ms", "jr",
    "st", "inc", "ltd", "co", "e.g", "i.e", "no", "op", "cit", "p.ej", "u.s",
}

_CORTE = re.compile(r"[.!?…]+[\"'»”\)\]]*(\s+|$)")
_PALABRA_FIN = re.compile(r"([\wÁÉÍÓÚÑÜáéíóúñü\.]+)$", re.UNICODE)
_INICIO_VALIDO = re.compile(r"^[¿¡\"'«“\(\[\-–—]*[A-ZÁÉÍÓÚÑÜ0-9]")


def _es_abreviatura(prefijo):
    m = _PALABRA_FIN.search(prefijo.rstrip("\"'»”)]"))
    if not m:
        return False
    w = m.group(1).rstrip(".").lower()
    if not w:
        return False
    if w in ABREVIATURAS:
        return True
    # Iniciales tipo "J." o "J.R."
    return bool(re.fullmatch(r"(?:[a-záéíóúñü]\.?)+", w)) and len(w.replace(".", "")) <= 2


def sentences(text):
    """Devuelve [(inicio, fin, texto)] por oración, conservando offsets."""
    out = []
    for bloque in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        b0, b = bloque.start(), bloque.group(0)
        pos = 0
        for m in _CORTE.finditer(b):
            resto = b[m.end():]
            if _es_abreviatura(b[pos:m.start() + 1]):
                continue
            if resto and not _INICIO_VALIDO.match(resto):
                continue
            frag = b[pos:m.end()].strip()
            if frag:
                desplaz = len(b[pos:m.end()]) - len(b[pos:m.end()].lstrip())
                ini = b0 + pos + desplaz
                out.append((ini, ini + len(frag), frag))
            pos = m.end()
        frag = b[pos:].strip()
        if frag:
            desplaz = len(b[pos:]) - len(b[pos:].lstrip())
            ini = b0 + pos + desplaz
            out.append((ini, ini + len(frag), frag))
    return out


def chunk(text, max_chars=3500, overlap_sents=2):
    """Fragmentos que respetan límites de oración, con solapamiento.

    Devuelve [{"i", "text", "start", "end", "sentences"}].
    """
    sents = sentences(text)
    if not sents:
        return []
    grupos, cur = [], []
    for s in sents:
        largo = sum(len(x[2]) + 1 for x in cur) + len(s[2])
        if cur and largo > max_chars:
            grupos.append(cur)
            cur = cur[-overlap_sents:] if overlap_sents else []
        cur.append(s)
    if cur:
        grupos.append(cur)

    out = []
    for i, g in enumerate(grupos):
        out.append({
            "i": i,
            "start": g[0][0],
            "end": g[-1][1],
            "text": text[g[0][0]:g[-1][1]],
            "sentences": g,
        })
    return out


def find_quote(text, quote):
    """Localiza una cita literal (tolerante) -> (ini, fin) o None."""
    if not quote:
        return None
    q = quote.strip().strip('"“”«»')
    if not q:
        return None
    idx = text.find(q)
    if idx >= 0:
        return (idx, idx + len(q))
    patron = re.sub(r"(?:\\?\s)+", r"\\s+", re.escape(q))
    m = re.search(patron, text, re.IGNORECASE)
    if m:
        return (m.start(), m.end())
    palabras = q.split()
    if len(palabras) > 6:
        return find_quote(text, " ".join(palabras[:6]))
    return None
