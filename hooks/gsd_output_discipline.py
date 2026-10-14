#!/usr/bin/env python3
"""Disciplina de salida, en las dos superficies donde se incumple.

  PostToolUse(Write|Edit) -> el documento `.planning/` que se acaba de escribir. AVISA.
  Stop                    -> la respuesta de chat, antes de que llegue al terminal. CORTA.

EL PROBLEMA QUE RESUELVE
========================
`references/mandatory-initial-read.md` lleva las dos reglas de salida y lo cargan los
cinco agentes que escriben documentos. Pero es doctrina: entra en contexto y ahi compite
con todo lo demas. En una sesion de desarrollo larga, una regla enunciada falla justo
cuando hay presion — que es exactamente cuando importa.

Este hook mira lo que se acaba de ESCRIBIR y devuelve el incumplimiento al agente como
contexto al que tiene que reaccionar. No es un recordatorio, es una medicion sobre el
texto real.

QUE DETECTA, Y SOLO ESTO
========================
1. IDENTIFICADOR DESNUDO (Regla 1). Se marca cuando fallan LAS DOS senales: la oracion del
   identificador no llega a MIN_CONTENIDO_ORACION palabras con carga, Y tampoco usa la forma
   canonica `palabras (D-20)` / `D-20 — palabras`. Exigir solo la forma marcaba prosa
   correcta; exigir solo el contenido dejaba pasar `blocked on D-48 until the owner rules`.

2. FRASE CASI DUPLICADA (Regla 2, mitad mecanica). Dos frases largas del mismo documento
   con similitud >= UMBRAL_SIMILITUD y no contiguas. Es la redundancia estructural — el
   mismo hecho reimpreso en la tabla resumen y en la prosa.

MEDIDO, NO SUPUESTO
===================
Afinado contra los 1220 documentos `.planning/` reales de estos proyectos, no contra la
intuicion. La primera version exigia la forma literal y marcaba 3778 sitios, entre ellos
prosa correcta como `D-20 capped guest fields at {status, name, vmid}`. La version actual
marca 728 y deja el 75% de los documentos limpios. La suite esta en
`scratchpad/test_hook.py` y se probo capaz de fallar mutando el detector.

QUE NO DETECTA, Y NO SE VENDE COMO RESUELTO
===========================================
Si un parrafo es segunda copia de otro dicho con otras palabras. Eso sigue siendo criterio
del agente. El hook cubre los dos modos de fallo mecanicos, no la regla completa.

POR QUE NO ES CARO
==================
- Inerte fuera de GSD: si la ruta no cae en `.planning/`, sale en silencio.
- Inerte en codigo: solo mira `.md`.
- Techo duro de MAX_AVISOS lineas; nunca vuelca el documento.
- ADVIERTE, NUNCA BLOQUEA. En desarrollo un hook que corta escrituras estorba mas de lo
  que arregla. Sale 0 siempre, incluso al romperse.

SALIDA
  documento -> JSON con hookSpecificOutput.additionalContext (aviso).
  chat      -> JSON con {"decision": "block", "reason": ...} (corta el turno, una vez).
  Silencio = nada que decir.
"""
import difflib
import json
import re
import sys

MAX_AVISOS = 6           # techo duro de hallazgos reportados
MIN_PALABRAS_FRASE = 12  # frases mas cortas se repiten por gramatica, no por redundancia
UMBRAL_SIMILITUD = 0.90  # difflib ratio; por debajo son dos frases sobre el mismo tema
MIN_SEPARACION = 2       # frases contiguas casi iguales suelen ser una enumeracion legitima
MAX_FRASES = 3000        # techo de coste; por encima se salta el pase de duplicados.
                         # Medido: el documento mas grande del corpus real (1485 frases,
                         # DESIGN-CONTRACT.md) tarda 0,79 s con el prefiltro puesto, asi que
                         # 1200 dejaba fuera el unico documento que lo superaba sin ahorrar
                         # nada. A 3000 no se salta ninguno y el peor caso sigue muy por
                         # debajo del timeout de 10 s del hook.
PREFILTRO_JACCARD = 0.6  # solapamiento de palabras antes de pagar difflib
MIN_CONTENIDO_ORACION = 5  # palabras con carga en la oracion del identificador; por debajo, va desnudo

# Palabras que no aportan significado al identificador. Deliberadamente corta: la lista
# solo tiene que evitar que "per", "the" y "is" cuenten como haber nombrado la cosa.
VACIAS = {
    "the", "and", "for", "with", "that", "this", "was", "are", "not", "per", "its",
    "has", "have", "但", "into", "from", "but", "all", "any", "our", "out", "via",
    "which", "what", "when", "then", "than", "each", "also", "already", "still",
    "los", "las", "una", "por", "con", "que", "del", "para", "como", "esta", "este",
    "sobre", "desde", "entre", "sus", "son", "hay",
}

# QUE CUENTA COMO IDENTIFICADOR, Y POR QUE YA NO ES UNA LISTA DE PREFIJOS.
# La primera version llevaba la lista cerrada `ADR|MH|FU|...|D|T|F|M|B|R`, escrita mirando
# los proyectos de frontend. Medido despues sobre las 8800 apariciones reales del corpus de
# un proyecto de ERP, esa lista veia 1609 — el 18 %. Se le escapaban `ENG-02`,
# `CRM-08`, `FISCAL-01`, `TYP-05` (prefijos que ese proyecto acuna y la lista no conocia),
# `D3-5` y `D6-3` (decision numerada por fase, que no es `D-\d+`), `06-07` (la ola, que es
# la forma que mas se usa en chat) y `26R001` (un numero de factura, que no es un
# identificador de plan pero se lee igual de opaco).
#
# Asi que el prefijo se abre y lo que se cierra es la lista de lo que NO es un identificador:
# licencias, codificaciones y hashes, que son las unicas familias que el patron abierto
# recogia de mas en el corpus (AGPL-3, LGPL-3, UTF-8, SHA-256, PEP-668 — 300 apariciones).
PREFIJOS_NO = {
    "UTF", "ISO", "SHA", "MD", "CRC", "AES", "RSA", "TLS", "SSL", "HTTP", "HTTPS",
    "AGPL", "LGPL", "GPL", "BSD", "MIT", "CC", "RFC", "PEP", "CVE", "UTC", "GMT",
    "IEC", "ANSI", "UNE", "EN", "RD", "WCAG", "AA", "AAA", "COVID", "RS", "USB",
}
RE_IDENT = re.compile(r"""(?<![\w-])(
      (?:[A-Z][A-Z0-9]{0,7}-\d{1,3}(?:\.\d+)?[a-z]?)   # ADR-012, ENG-02, D-48, D3-5, T-04
    | (?:[01]\d-\d{2})                                  # 06-07: la ola, sin prefijo
)(?!\.\d)(?![\w-])""", re.X)
# Solo en chat. `26R001`/`26F314` son datos, no identificadores de plan: en un documento
# fiscal la cifra ES el contenido, en una linea de estado es un codigo que nadie descifra.
RE_IDENT_CHAT = re.compile(r"""(?<![\w-])(
      (?:[A-Z][A-Z0-9]{0,7}-\d{1,3}(?:\.\d+)?[a-z]?)
    | (?:[01]\d-\d{2})
    | (?:\d{2}[A-Z]\d{3})                               # 26R001, 26F314
)(?!\.\d)(?![\w-])""", re.X)


def _es_identificador(tok: str) -> bool:
    """Filtra la familia que el patron abierto recoge de mas: licencias y codificaciones."""
    return tok.split("-")[0] not in PREFIJOS_NO

# Formas que SI cumplen la Regla 1, evaluadas sobre el entorno inmediato del identificador.
# Medido sobre el corpus real: sin `·` ni fin-de-linea esto marcaba encabezados correctos
# del tipo `### R-8 · web_environment_ribbon tiene fecha de caducidad`, que es justo la
# forma que la regla pide. Un separador distinto no es un incumplimiento.
RE_TRAS_IDENT_OK = re.compile(r"^\s*[—–·•:,|-]\s*\S")   # `D-20 — palabras`, `R-8 · palabras`


def partir_oraciones(linea: str) -> list:
    """Trocea en oraciones sin cortar detras de un identificador.

    `### F-1. One live sub-AA element on Trends` es UNA oracion donde F-1 queda nombrado.
    Un split ingenuo por `.` lo parte en `### F-1.` (identificador desnudo, falso positivo)
    y el resto. Se marcan los finales de identificador y no se corta ahi.
    """
    finales = {m.end(1) for m in RE_IDENT.finditer(linea)}
    trozos, ini = [], 0
    for i, ch in enumerate(linea):
        if ch in ".!?;" and i + 1 < len(linea) and linea[i + 1].isspace() and i not in finales:
            trozos.append(linea[ini:i + 1])
            ini = i + 1
    trozos.append(linea[ini:])
    return [t for t in trozos if t.strip()]


def es_ruta_gsd(ruta: str) -> bool:
    """Solo documentos de planificacion. Fuera de ahi el hook no existe."""
    return ".planning/" in ruta.replace("\\", "/") and ruta.endswith(".md")


def sin_codigo(texto: str) -> list:
    """Devuelve [(nlinea, linea)] fuera de fences y de frontmatter YAML.

    Un ejemplo dentro de un bloque de codigo no incumple nada, y el frontmatter
    declara identificadores por diseno (`requirements: [AUTH-01, QA-01]`).
    """
    fuera, en_fence, en_fm = [], False, False
    for i, linea in enumerate(texto.splitlines(), 1):
        if i == 1 and linea.strip() == "---":
            en_fm = True
            continue
        if en_fm:
            if linea.strip() == "---":
                en_fm = False
            continue
        if linea.lstrip().startswith("```"):
            en_fence = not en_fence
            continue
        if not en_fence:
            fuera.append((i, linea))
    return fuera


def identificadores_desnudos(lineas: list) -> list:
    """Regla 1. Marca el identificador que no lleva su significado al lado.

    Se mide SIGNIFICADO ADYACENTE, no puntuacion. Una version anterior exigia la forma
    literal `palabras (D-20)` o `D-20 — palabras`, y sobre el corpus real marcaba prosa
    correcta como `D-20 capped guest fields at {status, name, vmid} — six fields`, que
    nombra la cosa perfectamente. La regla pide que el lector no tenga que abrir otro
    fichero; eso se comprueba contando cuanto contenido acompana al identificador en su
    propia oracion, no que separador se uso.
    """
    hallazgos = []
    for n, linea in lineas:
        if not any(_es_identificador(m.group(1)) for m in RE_IDENT.finditer(linea)):
            continue
        # Fila de tabla: el nombre vive en la celda de al lado.
        if linea.lstrip().startswith("|"):
            celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
            if len([c for c in celdas if len(c.split()) >= 3]) >= 1:
                continue
        # No se trocea justo detras de un identificador: `### F-1. One live element` es
        # UNA oracion en la que F-1 queda nombrado, no un `F-1.` suelto seguido de otra.
        for oracion in partir_oraciones(linea):
            ids = [i for i in RE_IDENT.findall(oracion) if _es_identificador(i)]
            if not ids:
                continue
            # Fuera markdown, rutas, spans de codigo y los propios identificadores: lo que
            # queda es lo que un lector obtiene sin ir a buscar nada.
            resto = RE_IDENT.sub(" ", oracion)
            # Un span de codigo o una ruta SI son contenido: `QA-01 requires
            # `tools/contrast-audit.mjs`` nombra la cosa. Vaciarlos dejaba la oracion en
            # una palabra y marcaba prosa tecnica correcta — era la causa dominante de
            # falso positivo medida sobre el corpus. Cuentan como un termino cada uno.
            resto = re.sub(r"`[^`]*`", " termino ", resto)
            resto = re.sub(r"\[([^\]]*)\]\([^)]*\)", r" \1 ", resto)
            resto = re.sub(r"[\w./-]*\.(?:md|tsx?|mjs|py|json|css)\b", " termino ", resto)
            resto = re.sub(r"[^\w\s]", " ", resto)
            contenido = [
                w for w in resto.lower().split()
                if len(w) > 2 and w not in VACIAS and not w.isdigit()
            ]
            if len(contenido) >= MIN_CONTENIDO_ORACION:
                continue
            # Segunda senal, y hace falta que fallen LAS DOS. La forma canonica
            # `palabras (D-20)` o `D-20 — palabras` cumple la regla aunque la oracion
            # sea corta; marcar ahi seria castigar prosa correcta.
            if forma_canonica(oracion, ids[0]):
                continue
            # Dentro de un span de codigo es una cita literal del identificador
            # (`el guard rechaza \`ADR-15\` como cadena`), no prosa que lo invoque.
            m = RE_IDENT.search(oracion)
            if m and oracion[:m.start(1)].count("`") % 2 == 1:
                continue
            hallazgos.append((n, ids[0], oracion.strip()[:90]))
            break  # un aviso por linea; el agente ya sabe donde mirar
    return hallazgos


def forma_canonica(oracion: str, ident: str) -> bool:
    """True si el identificador va en la forma que la regla pide, y por tanto cumple."""
    m = RE_IDENT.search(oracion)
    if not m:
        return False
    antes, despues = oracion[:m.start(1)], oracion[m.end(1):]
    if antes.rstrip().endswith("(") or antes.count("(") > antes.count(")"):
        return True                      # `palabras llanas (D-20)`
    if RE_TRAS_IDENT_OK.match(despues):
        return True                      # `D-20 — palabras llanas`
    return bool(re.match(r"\s*\([^)]{4,}\)", despues))   # `D-3 (prove-then-switch)`


def frases(lineas: list) -> list:
    """[(nlinea, normalizada)] de frases largas, sin markdown ni identificadores."""
    salida = []
    for n, linea in lineas:
        if linea.lstrip().startswith(("#", ">", "|")):
            continue
        for frase in re.split(r"(?<=[.!?])\s+", linea):
            limpia = re.sub(r"[`*_\[\]()#]", "", frase)
            limpia = re.sub(r"\s+", " ", limpia).strip().lower()
            if len(limpia.split()) >= MIN_PALABRAS_FRASE:
                salida.append((n, limpia))
    return salida


def duplicados(fs: list) -> list:
    """Regla 2, mitad mecanica. Pares de frases largas casi identicas y no contiguas.

    Comparar todos contra todos con difflib es O(n^2) sobre el comparador caro: medido,
    159 frases costaban 1,41 s, y un hook lento se acaba desactivando. Se filtra antes
    con solapamiento de conjuntos de palabras (barato) y solo se confirma con difflib lo
    que ya parece un duplicado.
    """
    if len(fs) > MAX_FRASES:
        return []  # documento fuera de rango; el chequeo de Regla 1 sigue corriendo
    conj = [(n, t, frozenset(t.split())) for n, t in fs]
    hallazgos, ya_visto = [], set()
    for i in range(len(conj)):
        n1, a, sa = conj[i]
        if n1 in ya_visto:
            continue
        for j in range(i + 1, len(conj)):
            n2, b, sb = conj[j]
            if n2 - n1 < MIN_SEPARACION or n2 in ya_visto:
                continue
            if abs(len(a) - len(b)) / max(len(a), len(b)) > 0.25:
                continue
            union = len(sa | sb)
            if not union or len(sa & sb) / union < PREFILTRO_JACCARD:
                continue
            if difflib.SequenceMatcher(None, a, b).ratio() >= UMBRAL_SIMILITUD:
                ya_visto.add(n1)
                ya_visto.add(n2)
                hallazgos.append((n1, n2, a[:80]))
                break
    return hallazgos


# ---------------------------------------------------------------------------
# MODO CHAT (Stop): la mitad que faltaba
# ---------------------------------------------------------------------------
# El hook nacio mirando solo lo que se ESCRIBE en `.planning/`, y ahi la regla se cumplia.
# Lo que el usuario tuvo que corregir dos veces no fue un documento: fue el
# mensaje de cierre de sesion, una tabla cuyas filas eran `06-07`, `26R001` y `D6-3`. Esa
# superficie no pasa por Write ni por Edit, asi que el hook no la veia y "el arnes no
# funciona" era literal.
#
# En chat la senal fuerte es distinta a la de un documento. `06-07 — bloqueada por las tres
# puertas` tiene contenido de sobra en la oracion y aun asi es justo lo prohibido: el SUJETO
# de la linea es un codigo. Un documento puede permitirselo porque el lector tiene el indice
# al lado; en el terminal no lo tiene. Asi que aqui se marca la posicion, no la cantidad de
# palabras: identificador al principio de linea, de vinieta, de encabezado o de celda, sin
# nada con significado delante.
#
# BLOQUEA una vez, y solo con esa senal. Los `stop` de Claude Code no admiten aviso: o se
# deja pasar o se corta. Cortar con una senal ambigua entrena a desactivar el hook, asi que
# el caso mediano (identificador a mitad de frase) se deja pasar a proposito.

RE_MARCA_CODIGO = re.compile(r"^\s*```")


def _palabras_con_carga(texto: str) -> int:
    """Cuenta lo que un lector saca del texto: fuera markdown, emoji y palabras vacias."""
    limpio = re.sub(r"[^\w\s]", " ", texto, flags=re.UNICODE)
    return len([w for w in limpio.lower().split()
                if len(w) > 2 and w not in VACIAS and not w.isdigit()])


def _unidades(texto: str) -> list:
    """[(nlinea, unidad)] — la linea, o cada celda si es fila de tabla. Sin fences.

    Una celda es una unidad propia: en la tabla que provoco esto el codigo era la primera
    celda y la explicacion la segunda, que es exactamente el fallo.
    """
    fuera, en_fence = [], False
    for n, linea in enumerate(texto.splitlines(), 1):
        if RE_MARCA_CODIGO.match(linea):
            en_fence = not en_fence
            continue
        if en_fence or linea.lstrip().startswith(">"):
            continue  # citar al usuario no es hablar por codigos
        if linea.lstrip().startswith("|"):
            celdas = linea.strip().strip("|").split("|")
            if all(set(c.strip()) <= set("-: ") for c in celdas):
                continue  # separador de tabla
            fuera.extend((n, c) for c in celdas)
        else:
            fuera.append((n, linea))
    return fuera


RE_RANGO = re.compile(r"[:.]\d")   # `thresholds.ts:14-45` es un rango de lineas, no una ola


def identificadores_sin_nombre(texto: str) -> list:
    """La otra mitad de la Regla 1 en chat: el identificador cuya frase no lo nombra.

    `¿Arranco con 05-01?` y `MEM-02 cerrado.` no encabezan nada raro y aun asi son el fallo
    entero: pedir una decision por su codigo. Se mide igual que en un documento — palabras
    con carga en la frase y forma canonica — porque aqui la posicion ya no dice nada.

    Medido sobre 3618 mensajes reales: la regla del sujeto sola cortaba 154 (4,3 %); con
    esta, 222 (6,1 %). Los 68 que anade son incumplimientos, mirados uno a uno.
    """
    hallazgos = []
    for n, unidad in _unidades(texto):
        for oracion in partir_oraciones(unidad):
            ids = [m.group(1) for m in RE_IDENT_CHAT.finditer(oracion)
                   if _es_identificador(m.group(1))
                   and not RE_RANGO.search(oracion[max(0, m.start(1) - 2):m.start(1)])]
            if not ids:
                continue
            resto = re.sub(r"`[^`]*`", " termino ", RE_IDENT_CHAT.sub(" ", oracion))
            if _palabras_con_carga(resto) >= MIN_CONTENIDO_ORACION:
                continue
            if forma_canonica(oracion, ids[0]):
                continue
            hallazgos.append((n, ids[0], oracion.strip()[:80]))
            break
    return hallazgos


def identificadores_sujeto(texto: str) -> list:
    """Identificadores que ENCABEZAN una linea, vinieta, encabezado o celda.

    Nada con significado delante del codigo = la cosa esta nombrada por su codigo. Los
    adornos (`#`, `-`, `**`, backticks, emoji, numeracion) no cuentan como nombrarla.
    """
    hallazgos = []
    for n, unidad in _unidades(texto):
        for m in RE_IDENT_CHAT.finditer(unidad):
            ident = m.group(1)
            if not _es_identificador(ident):
                continue
            if RE_RANGO.search(unidad[max(0, m.start(1) - 2):m.start(1)]):
                continue  # `thresholds.ts:14-45`
            if _palabras_con_carga(unidad[:m.start(1)]):
                break  # ya se nombro algo antes; no es el sujeto
            hallazgos.append((n, ident, unidad.strip()[:80]))
            break
    return hallazgos


def _texto_final(ruta: str) -> str:
    """El ultimo mensaje de texto del asistente en el transcript.

    Se leen los ultimos 2 MB y no el fichero entero: una sesion larga pasa de 100 MB y el
    hook corre al final de CADA turno, en los quince proyectos.
    """
    recortado = False
    try:
        with open(ruta, "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            recortado = tam > 2_000_000
            # `seek(0, 2)` dejo el puntero en EOF: sin volver atras `read()` devuelve vacio
            # y el hook pasa siempre. Fallo real, cazado por el fixture del mensaje malo.
            f.seek(tam - 2_000_000 if recortado else 0)
            crudo = f.read().decode("utf-8", "replace")
    except Exception:
        return ""
    ultimo = ""
    for linea in crudo.splitlines()[1 if recortado else 0:]:
        try:
            d = json.loads(linea)
        except Exception:
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        partes = [c.get("text", "") for c in d.get("message", {}).get("content", [])
                  if isinstance(c, dict) and c.get("type") == "text"]
        junto = "\n".join(p for p in partes if p.strip())
        if junto.strip():
            ultimo = junto
    return ultimo


def main_chat(datos: dict) -> None:
    """Stop: corta el turno si la respuesta nombra las cosas por su codigo."""
    if datos.get("stop_hook_active"):
        sys.exit(0)  # ya se corto una vez este turno; a la segunda se deja pasar

    texto = _texto_final(datos.get("transcript_path") or "")
    hallazgos = identificadores_sujeto(texto)
    vistos = {(n, i) for n, i, _ in hallazgos}
    hallazgos += [h for h in identificadores_sin_nombre(texto) if (h[0], h[1]) not in vistos]
    if not hallazgos:
        sys.exit(0)

    hallazgos.sort()
    lineas = [f"  L{n}: «{ctx}» — `{ident}` sin decir que es" for n, ident, ctx in hallazgos[:MAX_AVISOS]]
    cola = "" if len(hallazgos) <= MAX_AVISOS else f"\n  (+{len(hallazgos) - MAX_AVISOS} mas)"
    razon = (
        "DISCIPLINA DE SALIDA — la respuesta nombra "
        f"{len(hallazgos)} cosa(s) por su codigo en vez de decir lo que son:\n"
        + "\n".join(lineas) + cola
        + "\n\nReescribe esas lineas ANTES de terminar: primero la cosa en palabras llanas, "
        "y el codigo detras entre parentesis si sirve para buscarla. "
        "«La ventana de produccion, parada por la firma de Manuel y su certificado (06-07)», "
        "no «06-07: bloqueada». Vale para todo: estados, preguntas, bloqueos y tablas."
    )
    json.dump({"decision": "block", "reason": razon}, sys.stdout)
    sys.exit(0)


def analizar(texto: str) -> list:
    """Devuelve la lista de lineas de aviso. Vacia = el documento cumple."""
    lineas = sin_codigo(texto)
    avisos = []
    for n, ident, ctx in identificadores_desnudos(lineas):
        avisos.append(
            f"  L{n}: `{ident}` va solo. Regla 1 pide `palabras llanas ({ident})` "
            f"o `{ident} — palabras llanas`.  ...{ctx}"
        )
    for n1, n2, frag in duplicados(frases(lineas)):
        avisos.append(
            f"  L{n1} y L{n2}: la misma frase dos veces. Deja la que lleve mas y "
            f'borra la otra, no las dos.  "{frag}..."'
        )
    return avisos


def main() -> None:
    try:
        datos = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    evento = datos.get("hook_event_name") or ""
    if evento in ("Stop", "SubagentStop"):
        main_chat(datos)
        return

    entrada = datos.get("tool_input") or {}
    ruta = entrada.get("file_path") or ""
    if not es_ruta_gsd(ruta):
        sys.exit(0)

    # Write trae el cuerpo entero; Edit solo el fragmento nuevo. En ambos casos se mide
    # lo que se acaba de escribir, no el fichero en disco: el hook corre antes de que
    # merezca la pena releerlo, y el fragmento basta para los dos modos de fallo.
    texto = entrada.get("content") or entrada.get("new_string") or ""
    if not texto.strip():
        sys.exit(0)

    avisos = analizar(texto)
    if not avisos:
        sys.exit(0)

    total = len(avisos)
    mostrados = avisos[:MAX_AVISOS]
    cola = "" if total <= MAX_AVISOS else f"\n  (+{total - MAX_AVISOS} mas del mismo tipo)"

    mensaje = (
        f"DISCIPLINA DE SALIDA — {total} incumplimiento(s) en {ruta}:\n"
        + "\n".join(mostrados)
        + cola
        + "\n\nArreglalo en el documento antes de seguir. Regla 1: nombra la cosa, el "
        "identificador va detras entre parentesis. Regla 2: quita la copia repetida, "
        "NUNCA el contenido — jamas un hecho, una cifra, una ruta, el POR QUE de una "
        "decision, ni el registro de control (que un check se probo capaz de fallar, "
        "que control corrio y que devolvio). Esto no aplica a codigo, comentarios, "
        "tests ni pasos de verificacion."
    )

    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": mensaje}},
        sys.stdout,
    )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Un hook de disciplina jamas rompe una escritura.
        sys.exit(0)
