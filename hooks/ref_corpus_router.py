#!/usr/bin/env python3
"""UserPromptSubmit: encamina el corpus de terceros de `ref/` hacia el trabajo.

EL PROBLEMA QUE RESUELVE — medido
===============================================
un proyecto de ERP tiene 1.140 ficheros y ~32 MB de material de terceros
en `ref/` y tenia CERO puntos de contacto automaticos: ni CLAUDE.md, ni un hook,
ni una skill lo mandaban leer. Se leyo a mano dos veces en dos fases; la Fase 3
no lo toco. Una linea en CLAUDE.md pidiendolo por favor no lo arregla: Segner
(Anthropic, «Steering Claude Code») es explicito en que un «cada vez
que X, siempre Y» pertenece a un hook, no al fichero de memoria, porque una regla
enunciada falla justo cuando hay presion.

QUE HACE
========
Cruza los nombres de modulo del ERP que aparecen en el trabajo EN CURSO (la peticion
del usuario y los documentos de la fase abierta) contra `infra/ref/ref-index.tsv`,
y emite las rutas del corpus que hablan de esos modulos. Nada mas: rutas y
recuentos, nunca contenido de terceros — citar es por fichero y linea (O-15).

POR QUE NO ES CARO
==================
- Inerte fuera de este proyecto: sin `infra/ref/ref-index.tsv` sale en silencio.
- Inerte cuando no hay coincidencia: la mayoria de las peticiones no nombran
  modulos y no emite nada.
- No se repite: recuerda por sesion que modulos ya encamino y solo habla de los
  nuevos. Chroma («Context Rot») mide que un solo distractor degrada el
  rendimiento; repetir el mismo bloque cada turno ES el distractor.
- Techo duro de MAX_MODULOS lineas.

SALIDA
  stdout -> se inyecta como contexto adicional. Silencio = no habia nada que decir.
  Nunca sale distinto de 0: un router de contexto no bloquea el trabajo.
"""
import json
import os
import re
import sys
from pathlib import Path

MAX_MODULOS = 8          # techo duro de lineas de corpus por turno
MAX_RUTAS = 3            # rutas por modulo; el resto se resume en un contador
MIN_APARICIONES = 4      # un modulo apenas mencionado no merece desviar la atencion


def salir_callado():
    sys.exit(0)


def raiz_proyecto(cwd: str) -> Path | None:
    p = Path(cwd or ".").resolve()
    for cand in [p, *p.parents]:
        if (cand / "infra" / "ref" / "ref-index.tsv").is_file():
            return cand
    return None


def cargar_indice(raiz: Path) -> dict:
    indice = {}
    for linea in (raiz / "infra" / "ref" / "ref-index.tsv").read_text(
            encoding="utf-8", errors="replace").splitlines():
        if not linea or linea.startswith("#"):
            continue
        partes = linea.split("\t")
        if len(partes) != 3:
            continue
        modulo, total, rutas = partes
        try:
            total = int(total)
        except ValueError:
            continue
        indice[modulo] = (total, rutas.split(","))
    return indice


_FASE = re.compile(r"^(\d+)[-_]")


def fase_abierta(raiz: Path) -> Path | None:
    """La carpeta de fase con el NUMERO mas alto: el trabajo en curso.

    Se elige por numero y no por mtime a proposito — abrir un fichero de una fase
    cerrada para consultarla no debe convertirla en «la fase en curso».

    ⛔ Y se exige que el nombre EMPIECE POR NUMERO. Ordenar por cadena parece
    equivalente y no lo es: el `sync-fernando-apps.sh` creo
    `.planning/phases/ICT-integracion-vertical-ict/` para dejar ahi su informe de
    divergencia, «ICT» ordena despues de «03», y este encaminador se puso a mirar
    una carpeta vacia y a callar. Callaba en silencio y con exito: exit 0, sin
    salida, indistinguible de «no habia coincidencias». Una carpeta que no empieza
    por numero no es una fase.
    """
    fases = raiz / ".planning" / "phases"
    if not fases.is_dir():
        return None
    cands = [(int(m.group(1)), d) for d in fases.iterdir() if d.is_dir()
             for m in [_FASE.match(d.name)] if m]
    return max(cands)[1] if cands else None


def tokens_del_trabajo(raiz: Path, prompt: str, patron: re.Pattern) -> set:
    tokens = set(patron.findall(prompt))
    fase = fase_abierta(raiz)
    if fase:
        # Solo los documentos de cabecera de la fase: contexto, plan e
        # investigacion. Los SUMMARY son el registro de lo YA hecho.
        for f in sorted(fase.glob("*.md")):
            n = f.name.upper()
            if not any(k in n for k in ("CONTEXT", "CONTEXTO", "PLAN", "INVESTIGACION", "RESEARCH")):
                continue
            try:
                tokens |= set(patron.findall(f.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return tokens


def ya_encaminados(session_id: str) -> tuple[Path, set]:
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "ref-corpus-router"
    base.mkdir(parents=True, exist_ok=True)
    f = base / f"{re.sub(r'[^A-Za-z0-9_-]', '_', session_id or 'sin-sesion')}.txt"
    vistos = set(f.read_text(encoding="utf-8").split()) if f.is_file() else set()
    return f, vistos


def main() -> int:
    try:
        entrada = json.load(sys.stdin)
    except Exception:
        salir_callado()

    raiz = raiz_proyecto(entrada.get("cwd", ""))
    if raiz is None:
        salir_callado()

    indice = cargar_indice(raiz)
    if not indice:
        salir_callado()

    # El patron se deriva del propio indice: sin lista de prefijos duplicada aqui
    # que se desincronice de la del generador.
    patron = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in sorted(indice, key=len, reverse=True)) + r")\b")

    tokens = tokens_del_trabajo(raiz, entrada.get("prompt", "") or "", patron)
    if not tokens:
        salir_callado()

    fichero_vistos, vistos = ya_encaminados(entrada.get("session_id", ""))
    nuevos = [m for m in tokens if m not in vistos and indice[m][0] >= MIN_APARICIONES]
    if not nuevos:
        salir_callado()

    nuevos.sort(key=lambda m: (-indice[m][0], m))
    nuevos = nuevos[:MAX_MODULOS]

    lineas = [
        "Corpus de terceros en `ref/` que habla de los modulos de este trabajo "
        "(material de Fernando, SOLO LECTURA — citar por fichero y linea, nunca pegar):",
    ]
    for m in nuevos:
        total, rutas = indice[m]
        muestra = rutas[:MAX_RUTAS]
        resto = len(rutas) - len(muestra)
        cola = f" (+{resto} mas)" if resto > 0 else ""
        lineas.append(f"- `{m}` ({total} menciones): " + " · ".join(muestra) + cola)
    lineas.append("Indice completo: `infra/ref/ref-index.tsv` · mapa del curso: "
                  "`ref/fernando-openteach/INDICE-GLOBAL.md`")

    print("\n".join(lineas))
    fichero_vistos.write_text("\n".join(sorted(vistos | set(nuevos))), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # Un router de contexto que revienta no debe llevarse por delante el turno.
        sys.exit(0)
