# Driver Python — fase `agenda` Plan B — minuta laboral — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar el paso 4 de `gestion_causas/subagentes/agenda.md` (hito de 4 días hábiles antes de una audiencia Única o Preparatoria: invocar la skill `/minuta-laboral` sobre la carpeta de la causa y registrar `minuta_ejecutada`) a `gestion_causas/fases/agenda.py`, completando la migración de la fase `agenda` (Plan A ya cubrió los pasos 1, 2, 3 y 5).

**Architecture:** La skill `/minuta-laboral` (`~/.claude/skills/.../minuta-laboral/SKILL.md`) no se toca — sigue siendo una skill de Claude Code aparte, fuera de este rediseño (ver spec, sección "Fuera de alcance"). Lo que se migra es solo la orquestación alrededor: calcular el hito, chequear los flags del registro, invocar la skill como subprocess, y verificar+registrar el resultado. A diferencia de los 6 puntos de razonamiento de `reasoning.preguntar` (JSON acotado, herramienta `Read` únicamente), la minuta necesita que Claude opere con permisos amplios (`Read`, `Write`, `Bash` — la skill corre `pymupdf`/`pypdf` y genera un `.docx`/`.pdf`) dentro de la carpeta de la causa. Se agrega una función nueva y separada en `reasoning.py`, `invocar_skill(...)`, en vez de forzar este caso dentro de `preguntar` (que asume JSON de salida y `Read`-only).

**Tech Stack:** Python 3, pytest, `gestion_causas.reasoning` (subprocess de `claude -p`).

**Spec:** `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md` y `gestion_causas/subagentes/agenda.md` paso 4 (reglas completas, referencia histórica).

## Global Constraints

- No se reimplementa la lógica de la minuta (lectura de plantilla, cálculo de montos, generación del `.docx`/PDF) — eso lo sigue haciendo la skill `/minuta-laboral` tal cual existe hoy.
- El acceso de Claude se acota a la carpeta de la causa (`--add-dir <carpeta>`), pero necesita `Read`, `Write` y `Bash` (a diferencia de los otros puntos de razonamiento) porque la skill instala paquetes de Python y escribe archivos. Nunca `--dangerously-skip-permissions`.
- Se verifica el resultado por efecto observable (aparece un `.docx` nuevo que menciona "Minuta" en la carpeta), no solo por el exit code del subprocess — un exit code 0 no garantiza que la skill haya completado su flujo.
- Aplica solo a audiencias Única o Preparatoria (Juicio queda fuera, agenda.md paso 4).
- Nunca corre dos veces para la misma causa: se saltea si `minuta_ejecutada: true` ya está en el registro.
- Igual que el paso 3, respeta `aplica_minuta_laboral: false` (causas que no son demanda laboral estándar contra la empresa).
- No se toca `cli.py`, `panel.py` ni las fases `smu`/`goteo` ya migradas.

---

## Alcance de este plan

Cubre el paso 4 completo de `agenda.md`: hito de 4 días hábiles, flags de causa, invocación
de la skill, verificación del resultado y registro de `minuta_ejecutada`.

**Fuera de alcance (YAGNI):**
- Cualquier cambio a la skill `/minuta-laboral` misma.
- Reintentos automáticos si la skill falla — igual que los demás puntos de razonamiento, un
  fallo se anota en `acciones` para revisión manual y la corrida sigue con la siguiente causa.
- Timeout configurable por causa — se usa un timeout fijo, generoso (la skill procesa PDFs
  escaneados y puede tardar varios minutos).

## Tasks

### 1. `reasoning.invocar_skill` — invocación con permisos amplios acotados a una carpeta

- [ ] En `gestion_causas/reasoning.py`, agregar `TIMEOUT_SKILL_SEGUNDOS = 1800` (30 min —
  bien por encima de `TIMEOUT_SEGUNDOS`, la skill hace OCR/PDF y puede tardar).
- [ ] Agregar `invocar_skill(prompt: str, carpeta: Path, *, ejecutar=None, timeout=TIMEOUT_SKILL_SEGUNDOS) -> dict`:
  - `ejecutar` inyectable para tests (mismo patrón que `preguntar`), por defecto
    `_ejecutar_claude_skill`.
  - No parsea JSON — devuelve `{"ok": True, "salida": <stdout>}` si el subprocess termina con
    exit code 0, o `{"error": "<detalle>"}` si lanza una excepción (timeout, binario no
    encontrado, exit code distinto de cero). Sin reintento (a diferencia de `preguntar`): un
    prompt de skill no es determinístico de la misma forma que un JSON mal formado, y
    reintentar podría duplicar trabajo de la skill (que ya puede haber escrito archivos
    parciales).
- [ ] Agregar `_ejecutar_claude_skill(prompt, carpeta, *, timeout) -> str`: mismo patrón que
  `_ejecutar_claude` (resolver `claude` con `shutil.which`, stdin en vez de argv, `encoding="utf-8"`
  explícito), pero con `--allowedTools "Read,Write,Bash" --add-dir <carpeta>` en vez de solo
  `Read` (la skill necesita instalar paquetes de pip y escribir el `.docx`/PDF generado).
- [ ] Tests en `tests/test_reasoning.py`: `invocar_skill` devuelve `{"ok": True, ...}` cuando
  `ejecutar` no lanza excepción; devuelve `{"error": ...}` sin lanzar cuando `ejecutar` lanza
  una excepción; no reintenta (un solo llamado a `ejecutar`).

### 2. `fases/agenda.py` — paso 4 completo

- [ ] `TIPOS_CON_MINUTA = {"Única", "Preparatoria"}`.
- [ ] `_debe_generar_minuta(causa, audiencia, fecha_hoy) -> bool`: análogo a
  `_debe_generar_ofrecimiento` pero con `TIPOS_CON_MINUTA`, flag `aplica_minuta_laboral`
  (en vez de `aplica_ofrecimiento`), flag `minuta_ejecutada` (en vez de
  `oferta_borrador_creado`), y hito `dias_mod.dias_habiles_antes(fecha_audiencia, 4)` (en vez
  de `dias_corridos_antes(..., 14)`). Notar que esta fase **no** mira `estado_acuerdo` — la
  minuta de prueba sigue siendo necesaria aunque haya un acuerdo en curso, a diferencia del
  ofrecimiento (si esto resulta ser un problema en la práctica, es un ajuste posterior).
- [ ] `_docs_minuta_existentes(carpeta: Path) -> set[str]`: nombres de archivo (`.name`) de
  todos los `.docx` en `carpeta` cuyo nombre contiene "Minuta" (case-insensitive) — usado
  antes/después de invocar la skill para detectar si generó un archivo nuevo.
- [ ] `_invocar_minuta_laboral(carpeta: Path, rit: str) -> dict`: arma el prompt
  (`f"/minuta-laboral {carpeta}"` con una instrucción corta pidiendo que trabaje sobre esa
  carpeta puntual) y llama a `reasoning.invocar_skill`. Devuelve el dict de `invocar_skill`
  tal cual (el llamador decide qué hacer con `{"error": ...}`).
- [ ] `_procesar_minuta(causa, audiencia, fecha_hoy, ruta_registro_causas, acciones) -> bool`:
  - Si no corresponde (`_debe_generar_minuta` es False), devuelve `False` sin hacer nada.
  - Si la carpeta no existe, anota una acción (urgencia media) y devuelve `False` — igual
    criterio que "no se encontró demanda.pdf" del paso 3.
  - Guarda `_docs_minuta_existentes(carpeta)` antes de invocar.
  - Invoca `_invocar_minuta_laboral`. Si devuelve `{"error": ...}`, anota una acción
    (urgencia media, mismo mensaje del error) y devuelve `False` — no marca
    `minuta_ejecutada`, para que se reintente en la corrida siguiente.
  - Si no hay error, recalcula `_docs_minuta_existentes(carpeta)`: si no apareció ningún
    archivo nuevo, anota una acción (urgencia media: "la skill terminó pero no se detectó
    una minuta nueva en la carpeta — revisar a mano") y devuelve `False` (tampoco marca
    `minuta_ejecutada`).
  - Si apareció un archivo nuevo: `registro_mod.registrar_causa(rit, {"minuta_ejecutada": True}, ...)`,
    anota en bitácora ("Minuta generada a N días hábiles de la audiencia", mismo mensaje que
    agenda.md paso 4d), devuelve `True`.
- [ ] En `correr()`: después de `_procesar_ofrecimiento`, llamar también a `_procesar_minuta`
  para la misma causa (una causa puede generar ambos en la misma corrida, ej. si "toca" el
  hito de 14 días y el de 4 días hábiles el mismo día — son hitos independientes, no
  mutuamente excluyentes). Sumar un contador `minutas_generadas` y una métrica nueva
  ("Minutas generadas"). Agregar un `item` al resumen cuando se genera una minuta (mismo
  formato que el de ofrecimiento, `detalle="Minuta de prueba generada"`).
- [ ] Actualizar `_armar_titular` para mencionar también las minutas cuando corresponda (ej.
  "1 borrador de ofrecimiento creado, 2 minutas generadas" — mismo formato que el ejemplo de
  agenda.md paso 5).
- [ ] Actualizar el docstring del módulo (ya no dice "Plan B, todavía no migrado").

### 3. Tests

- [ ] `tests/fases/test_agenda.py`, clase `TestDebeGenerarMinuta`: casos análogos a
  `TestDebeGenerarOfrecimiento` (tipo Única/Preparatoria/Juicio, hito ya pasado/no llegó,
  `aplica_minuta_laboral: false`, `minuta_ejecutada: true` ya presente). Confirmar que
  `estado_acuerdo` NO bloquea la minuta (a diferencia del ofrecimiento).
- [ ] Clase `TestProcesarMinutaIntegracion`: mockeando `agenda.reasoning.invocar_skill`,
  cubrir: éxito (aparece un `.docx` nuevo con "Minuta" en el nombre → marca
  `minuta_ejecutada`, agrega item), la skill devuelve error (no marca el flag, agrega
  acción), la skill "ok" pero no aparece ningún archivo nuevo (no marca el flag, agrega
  acción distinta), carpeta inexistente (acción, no invoca la skill).
- [ ] Test de `correr()` de punta a punta con una causa que dispara ambos hitos el mismo día
  (ofrecimiento Y minuta) — confirma que ambos corren y ambas métricas/items aparecen.

### 4. Documentación

- [ ] `README.md`: actualizar la fila de `agenda` en la tabla de estado de la migración a
  "✅ migrada (Plan A + Plan B)".
