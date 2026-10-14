import json, subprocess, sys
import os
HOOK = os.path.join(os.path.dirname(os.path.realpath(__file__)), "gsd_output_discipline.py")

def run(content, path=".planning/phases/01-x/01-PLAN.md"):
    payload = json.dumps({"hook_event_name":"PostToolUse","tool_name":"Write",
                          "tool_input":{"file_path":path,"content":content}})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)
    assert r.returncode == 0, f"exit {r.returncode}: {r.stderr}"
    if not r.stdout.strip():
        return None
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

CASES = [
 # (nombre, texto, debe_marcar)
 ("Regla1: identificador desnudo, sujeto",
  "ADR-15 is not satisfied in this phase.\n", True),
 ("Regla1: identificador desnudo, objeto",
  "We are blocked on D-48 until the owner rules.\n", True),
 ("Regla1: forma correcta con parentesis",
  "The requirement that we write no TypeScript (ADR-15) is not satisfied.\n", False),
 ("Regla1: forma correcta con guion",
  "MH-3 — a logged-out user cannot reach /dashboard. Failed.\n", False),
 ("Regla1: encabezado con punto",
  "### F-1. One live sub-AA element on Trends in Ceramic Night\n", False),
 ("Regla1: fila de tabla con celda descriptiva",
  "| FU-2 | the live 4.04:1 Trends delta chip | CLOSED |\n", False),
 ("Regla1: dentro de bloque de codigo",
  "```\nKNOWN_HEADING_GAPS: settings-general\nADR-15 fails here\n```\n", False),
 ("Regla1: dentro de frontmatter",
  "---\nrequirements: [AUTH-01, QA-01, QA-02]\n---\n\nPlain prose here.\n", False),
 ("Regla1: dentro de span de codigo",
  "The guard rejects `ADR-15` as a literal string.\n", False),
 ("Regla2: frase larga duplicada no contigua",
  "The negative control removed the guard at line 31 and the test failed as expected.\n"
  "\nSome unrelated filler sentence sits here in between the two copies of the claim.\n\n"
  "The negative control removed the guard at line 31 and the test failed as expected.\n", True),
 ("Regla2: dos frases largas distintas",
  "The negative control removed the guard at line 31 and the test failed as expected.\n"
  "\nFiller between the two so they are not adjacent in the document at all here.\n\n"
  "The visual baseline suite fails on fifty files against a demo account cycle boundary.\n", False),
 ("Regla2: frase corta repetida (gramatica, no redundancia)",
  "Verified.\n\nfiller line here\n\nVerified.\n", False),
 ("Fuera de .planning: inerte",
  "ADR-15 is not satisfied.\n", False),
]

fails = 0
for nombre, texto, debe in CASES:
    path = "src/foo.md" if "Fuera de" in nombre else ".planning/phases/01-x/01-PLAN.md"
    out = run(texto, path)
    marco = out is not None
    ok = (marco == debe)
    fails += not ok
    print(f"{'PASS' if ok else '*** FAIL ***':<14} {nombre:<52} marco={marco} esperado={debe}")
    if not ok and out:
        print("    " + out.splitlines()[1] if len(out.splitlines())>1 else "")
print()
print(f"casos fallidos: {fails}/{len(CASES)}")

# ---------------------------------------------------------------------------
# MODO CHAT (Stop). Los dos primeros casos NO son inventados: son los dos mensajes
# reales de un proyecto de ERP, el que el usuario tuvo que corregir
# y el corregido. Un detector que no separe esos dos no sirve para lo que se pidio.
# ---------------------------------------------------------------------------
import os, tempfile

MALO = """Sí. Hecho:

## Lo que queda

| | |
|---|---|
| `06-07` | ⛔ bloqueada por las tres puertas: firma de Manuel, EIPD, certificado FNMT |
| `26R001` (serie rectificativa) | número inventado por nosotros — hay que preguntarle |
| Entregable de la gestoría | decidir si es el `xlsx` del libro más una exportación |
"""

BUENO = """**1 · El número con el que arrancan las facturas rectificativas.**
Una rectificativa corrige a otra ya emitida. Yo la dejé configurada para que la primera
sea `26R001` — pero ese número me lo he inventado: no hay ninguna en el corpus.
"""

def run_chat(texto, active=False):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                "content": [{"type": "text", "text": texto}]}}) + "\n")
        ruta = f.name
    payload = json.dumps({"hook_event_name": "Stop", "transcript_path": ruta,
                          "stop_hook_active": active})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)
    os.unlink(ruta)
    assert r.returncode == 0, f"exit {r.returncode}: {r.stderr}"
    if not r.stdout.strip():
        return None
    return json.loads(r.stdout).get("decision")

CASOS_CHAT = [
 ("chat: el mensaje real que el usuario corrigio", MALO, False, True),
 ("chat: el mismo contenido ya reescrito", BUENO, False, False),
 ("chat: segunda pasada, sin bucle", MALO, True, False),
 ("chat: la ola nombrada antes del codigo",
  "La ventana de produccion sigue parada por el certificado (06-07).\n", False, False),
 ("chat: codigo como sujeto de vinieta",
  "- **ADR-012** sin firmar\n", False, True),
 ("chat: codigo como sujeto de encabezado",
  "## 07-04\nCorre el inventario.\n", False, True),
 ("chat: dentro de bloque de codigo",
  "```\n06-07 blocked\n```\n", False, False),
 ("chat: citando al usuario",
  "> 06-07 blocked\n\nCorregido: la ventana de produccion sigue parada (06-07).\n", False, False),
 ("chat: licencia y codificacion no son identificadores",
  "AGPL-3 es la licencia y UTF-8 la codificacion del volcado.\n", False, False),
 ("chat: numero de factura como sujeto de fila",
  "| `26F314` | la siguiente factura real |\n", False, True),
 # La otra mitad: el codigo no encabeza nada, y la frase sigue sin decir que es.
 ("chat: pedir permiso por el codigo",
  "¿Arranco con 05-01?\n", False, True),
 ("chat: dar por cerrado por el codigo",
  "MEM-02 cerrado.\n", False, True),
 ("chat: rango de lineas de un fichero no es un codigo",
  "El umbral vive en `lib/thresholds.ts:14-45` y sale del contrato de color.\n", False, False),
 ("chat: el codigo detras de la cosa nombrada",
  "Arranco la ola del vigilante fiscal (05-01).\n", False, False),
]

for nombre, texto, activo, debe in CASOS_CHAT:
    dec = run_chat(texto, activo)
    bloqueo = dec == "block"
    ok = bloqueo == debe
    fails += not ok
    print(f"{'PASS' if ok else '*** FAIL ***':<14} {nombre:<52} bloqueo={bloqueo} esperado={debe}")

# Regla 1 en documentos, con los prefijos que la lista cerrada anterior no veia.
CASOS_DOC_NUEVOS = [
 ("Regla1: prefijo de proyecto que la lista cerrada no conocia",
  "FISCAL-01 sigue sin cerrar.\n", True),
 ("Regla1: decision numerada por fase (D6-3)",
  "D6-3 no se cumple.\n", True),
 ("Regla1: la ola, sin prefijo",
  "06-07 no se ejecuta.\n", True),
 ("Regla1: la ola, nombrada",
  "La ventana de produccion no se ejecuta sin el certificado (06-07).\n", False),
 ("Regla1: licencia, no identificador",
  "AGPL-3 aqui.\n", False),
]
for nombre, texto, debe in CASOS_DOC_NUEVOS:
    out = run(texto)
    marco = out is not None
    ok = marco == debe
    fails += not ok
    print(f"{'PASS' if ok else '*** FAIL ***':<14} {nombre:<52} marco={marco} esperado={debe}")

print()
print(f"casos fallidos totales: {fails}/{len(CASES) + len(CASOS_CHAT) + len(CASOS_DOC_NUEVOS)}")
sys.exit(1 if fails else 0)
