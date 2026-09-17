# Driver Python para "smu" — borrador de documentos a solicitar (Plan B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completar la fase `smu` (Fase 2 del proyecto: paso 2k de `gestion_causas/subagentes/smu.md`) migrando a Python puro el armado del borrador de documentos a solicitar — CECO, reuso de EERR de una causa anterior del mismo local, detección de ajustes según lo demandado (leyendo el PDF de la demanda) y creación del borrador con deduplicación — dejando a Claude solo la interpretación de texto libre que Python no puede resolver con regex.

**Architecture:** Se extiende `gestion_causas/reasoning.py` con una capacidad nueva y acotada: `preguntar(..., ruta_archivo=<path>)` deja que Claude lea un archivo puntual con su propia herramienta `Read` (necesario para PDFs escaneados, que se leen en modo visión), invocando `claude -p --allowedTools Read --add-dir <carpeta>` en vez de pasarle todo por JSON. `gestion_causas/fases/smu.py` (ya existente, Plan A) se extiende con el resto del paso 2k: CECO por regex, un solo llamado a Claude que lee la demanda y detecta fecha de despido + ajustes, reuso de EERR (funciones ya existentes de `registro.py`/`carpetas.py`), armado de la lista de documentos y creación del borrador (`gmail_client.crear_borrador`, ya existente).

**Tech Stack:** Python 3, pytest, librerías ya usadas por el proyecto (`gestion_causas.gmail_client`, `gestion_causas.registro`, `gestion_causas.carpetas`).

**Spec:** `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md` (diseño general del driver) y `gestion_causas/subagentes/smu.md` paso 2k (reglas completas del borrador de documentos, referencia histórica).

## Global Constraints

- Nunca se envían correos ni se borra nada — `crear_borrador` (ya existente) solo crea borradores; un humano los revisa y envía a mano.
- El borrador nunca se duplica: si la cadena ya tiene un borrador (`gmail_client.listar_borradores_de_hilo`), no se crea uno nuevo.
- El paso completo (CECO, ajustes, borrador) se salta si no se guardó la demanda (`demanda_guardada` es False) — sin demanda no hay de dónde sacar los ajustes.
- Aplica igual para las 6 empresas del proyecto, incluidas Preunic y Salcobrand (no depende de `EMPRESAS_SIN_EXCEL`).
- El acceso de Claude al sistema de archivos se acota al mínimo: solo la herramienta `Read`, solo en la carpeta que contiene el PDF de la demanda (`--allowedTools Read --add-dir <carpeta>`) — nunca `--dangerously-skip-permissions`.
- Las funciones de `registro.py`/`carpetas.py` siguen recibiendo `ruta`/rutas explícitas en los tests (nunca se monkeypatchea una constante de módulo tipo `RUTA_REGISTRO_CECO` esperando que afecte un valor ya bindeado por default — ver la nota completa en `docs/superpowers/plans/2026-09-15-driver-python-goteo-piloto.md`).
- No se toca `gestion_causas/cli.py`, `gestion_causas/panel.py`, `tests/test_cli.py`, `tests/test_panel.py` ni `gestion_causas/subagentes/seguimiento.md` — hay otra sesión trabajando en esos archivos en paralelo.

---

## Alcance de este plan (Plan B de 2, ver Plan A ya ejecutado)

Cubre el paso 2k completo de `smu.md`: buscar el CECO, detectar ajustes leyendo la demanda,
reusar EERR si corresponde, armar la lista de documentos y crear el borrador. Se apoya en
todo lo que Plan A ya dejó funcionando (`fases/smu.py::correr()`, cuadro-resumen, filtro de
empresa, carpeta, demanda guardada, registro, etiquetado).

**Fuera de alcance de este plan** (YAGNI):
- El destinatario del borrador se calcula siempre como el remitente del primer mensaje del
  hilo (`extraer_direccion(primer_mensaje["sender"])`) — smu.md permite "quien corresponda
  en el hilo", pero afinar ese criterio (ej. mirar los CC) es un ajuste posterior si en la
  práctica el destinatario por defecto no sirve.
- `verificar-borradores-pendientes` (que avisa si Nico no envió un borrador) ya lo corre el
  orquestador en su paso 4 con `registro.causas_con_borrador_pendiente` — este plan solo
  necesita dejar `borrador_documentos_draft_id` bien guardado en el registro, no reimplementa
  esa verificación.
- Ningún cambio a `cli.py` (el CLI viejo sigue teniendo sus propios comandos equivalentes,
  usados por el subagente `smu.md` mientras siga activo en paralelo).

## Punto que se queda con Claude (1, además de los 2 que ya usa Plan A)

**Lectura de la demanda** — un solo llamado que, leyendo el PDF con la herramienta `Read`
(modo visión si es un escaneo, acotado a Hechos/Antecedentes y Petitorio/Por tanto), decide:
la fecha exacta de despido, si se demanda una base de cálculo distinta de la indemnización
(dispara "Últimas 6 liquidaciones de remuneraciones"), y cualquier otro concepto atípico que
necesite un antecedente puntual. El CECO, en cambio, se busca con regex sobre el texto de los
mensajes del hilo — no requiere interpretación, solo tolerancia a variantes de formato.

---

### Task 1: `reasoning.py` — lectura de archivo acotada con `Read`

**Files:**
- Modify: `gestion_causas/reasoning.py`
- Test: `tests/test_reasoning.py`

**Interfaces:**
- Produces: `preguntar(tarea, contexto, schema, *, ejecutar=None, ruta_archivo=None) -> dict`
  (nuevo kwarg `ruta_archivo`, backward-compatible — si no se pasa, comportamiento idéntico
  al actual). `_ejecutar_claude(prompt, ruta_archivo=None) -> str`.

- [ ] **Step 1: Escribe los tests que fallan**

Agregá a `tests/test_reasoning.py`:

```python
class TestEjecutarClaudeConRutaArchivo:
    def test_agrega_allowedtools_read_y_add_dir_de_la_carpeta_del_archivo(self, monkeypatch, tmp_path):
        from gestion_causas import reasoning as reasoning_mod

        carpeta = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        carpeta.mkdir(parents=True)
        ruta_demanda = carpeta / "demanda.pdf"

        llamadas = []

        class ResultadoFalso:
            returncode = 0
            stdout = "ok"
            stderr = ""

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: "C:\\ruta\\falsa\\claude.CMD")
        monkeypatch.setattr(reasoning_mod.subprocess, "run", lambda args, **kwargs: llamadas.append((args, kwargs)) or ResultadoFalso())

        reasoning_mod._ejecutar_claude("un prompt", ruta_archivo=ruta_demanda)

        args, kwargs = llamadas[0]
        assert args == [
            "C:\\ruta\\falsa\\claude.CMD", "-p",
            "--allowedTools", "Read",
            "--add-dir", str(carpeta),
        ]
        assert kwargs.get("input") == "un prompt"

    def test_sin_ruta_archivo_no_agrega_allowedtools(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        llamadas = []

        class ResultadoFalso:
            returncode = 0
            stdout = "ok"
            stderr = ""

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: "C:\\ruta\\falsa\\claude.CMD")
        monkeypatch.setattr(reasoning_mod.subprocess, "run", lambda args, **kwargs: llamadas.append((args, kwargs)) or ResultadoFalso())

        reasoning_mod._ejecutar_claude("un prompt")

        args, kwargs = llamadas[0]
        assert args == ["C:\\ruta\\falsa\\claude.CMD", "-p"]


class TestPreguntarConRutaArchivo:
    def test_pasa_ruta_archivo_a_ejecutar_y_lo_menciona_en_el_prompt(self, tmp_path):
        from gestion_causas.reasoning import preguntar

        ruta_demanda = tmp_path / "demanda.pdf"
        llamadas = []

        def ejecutar_falso(prompt, ruta_archivo=None):
            llamadas.append((prompt, ruta_archivo))
            return json.dumps({"ok": True})

        resultado = preguntar(
            "tarea de prueba", {"dato": 1}, SCHEMA_SIMPLE,
            ejecutar=ejecutar_falso, ruta_archivo=ruta_demanda,
        )

        assert resultado == {"ok": True}
        prompt, ruta_recibida = llamadas[0]
        assert ruta_recibida == ruta_demanda
        assert str(ruta_demanda) in prompt

    def test_sin_ruta_archivo_ejecutar_se_llama_solo_con_el_prompt(self):
        from gestion_causas.reasoning import preguntar

        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert len(llamadas) == 1


class TestTimeoutSubidoA180:
    def test_timeout_segundos_es_180(self):
        from gestion_causas.reasoning import TIMEOUT_SEGUNDOS
        assert TIMEOUT_SEGUNDOS == 180
```

- [ ] **Step 2: Corré los tests y confirmá que fallan**

Run: `pytest tests/test_reasoning.py -v`
Expected: FAIL — `_ejecutar_claude`/`preguntar` todavía no aceptan `ruta_archivo`, y
`TIMEOUT_SEGUNDOS` todavía es 120.

- [ ] **Step 3: Implementá el soporte de `ruta_archivo`**

En `gestion_causas/reasoning.py`, cambiá `TIMEOUT_SEGUNDOS`:

```python
TIMEOUT_SEGUNDOS = 180
```

Reemplazá `preguntar` completo:

```python
def preguntar(
    tarea: str, contexto: dict, schema: dict, *, ejecutar=None, ruta_archivo=None
) -> dict:
    """Le pide a Claude que resuelva `tarea` sobre `contexto`, devolviendo un
    dict que cumple `schema`. Reintenta una vez si la respuesta no es JSON
    válido (o si `ejecutar` lanza una excepción); si vuelve a fallar, devuelve
    `{"error": "<detalle>"}` en vez de lanzar una excepción — el llamador
    decide qué hacer con eso (típicamente anotarlo en `acciones` del resumen
    y seguir con la siguiente causa).

    `ejecutar` es inyectable para tests: recibe el prompt armado y devuelve el
    texto de salida de Claude. Por defecto corre `claude -p`, pasando el
    prompt por stdin (no como argumento de línea de comandos, ver
    `_ejecutar_claude`). Una excepción de `ejecutar` (timeout, binario no
    encontrado, exit code distinto de cero, etc.) nunca se propaga fuera de
    `preguntar`.

    `ruta_archivo` (opcional) deja que Claude lea ese archivo puntual con su
    propia herramienta `Read` (necesario para PDFs, incluidos escaneos que se
    leen en modo visión) en vez de intentar meter su contenido en `contexto`
    como texto. Cuando se entrega, se pasa como segundo argumento a
    `ejecutar` (`ejecutar(prompt, ruta_archivo=ruta_archivo)`); si no se
    entrega, `ejecutar` se llama igual que siempre (`ejecutar(prompt)`), así
    que ningún llamador existente que no use `ruta_archivo` se ve afectado.
    """
    ejecutar = ejecutar or _ejecutar_claude

    error_previo: str | None = None
    salida = ""
    for intento in range(2):
        prompt = _armar_prompt(tarea, contexto, schema, error_previo=error_previo, ruta_archivo=ruta_archivo)
        try:
            if ruta_archivo is not None:
                salida = ejecutar(prompt, ruta_archivo=ruta_archivo)
            else:
                salida = ejecutar(prompt)
        except Exception as exc:  # noqa: BLE001 - una llamada externa (subprocess) no debe tumbar el batch
            error_previo = f"{type(exc).__name__}: {exc}"
            continue

        resultado = _parsear_json(salida)
        if resultado is not None:
            return resultado

        error_previo = salida

    return {
        "error": (
            "Claude no devolvió JSON válido tras 2 intentos. "
            f"Última respuesta: {error_previo[:500]!r}"
        )
    }
```

Reemplazá `_armar_prompt` completo:

```python
def _armar_prompt(
    tarea: str, contexto: dict, schema: dict, error_previo: str | None = None, ruta_archivo=None
) -> str:
    partes = [tarea, ""]
    if ruta_archivo is not None:
        partes += [
            f"Antes de responder, usá tu herramienta Read para leer el archivo en esta "
            f"ruta absoluta: {ruta_archivo}",
            "",
        ]
    partes += [
        "Contexto (JSON):",
        json.dumps(contexto, ensure_ascii=False, indent=2),
        "",
    ]
    if error_previo is not None:
        partes += [f"Tu respuesta anterior no era JSON válido: {error_previo!r}", ""]
    partes += [
        "Responde ÚNICAMENTE con un objeto JSON válido que cumpla este schema, "
        "sin texto antes ni después, y sin envolverlo en ```:",
        json.dumps(schema, ensure_ascii=False, indent=2),
    ]
    return "\n".join(partes)
```

Reemplazá `_ejecutar_claude` completo:

```python
def _ejecutar_claude(prompt: str, ruta_archivo=None) -> str:
    """Corre `claude -p`, pasando el prompt por stdin (no como argumento de
    línea de comandos) — en Windows, un prompt largo (el contexto de una
    causa con muchos correos puede ser de decenas de miles de caracteres)
    excede el límite de longitud de línea de comandos del sistema operativo
    si se pasa como argv, y falla con `WinError 206` / "línea de comandos
    demasiado larga" (confirmado en una corrida real). Por stdin no hay ese
    límite.

    En Windows, `claude` es un shim `.CMD` de npm que `subprocess.run` no
    encuentra si se le pasa el nombre desnudo (sin pasar por una shell) —
    hay que resolver la ruta completa con `shutil.which` primero (también
    confirmado en una corrida real: sin esto, todas las llamadas fallaban
    con `FileNotFoundError: [WinError 2]`).

    Se fuerza `encoding="utf-8"` explícitamente: con `text=True` sin
    `encoding`, Python usa la codepage por defecto del sistema operativo
    (en Windows, típicamente `cp1252`, no UTF-8) para escribir el stdin en
    el hilo interno `_writerthread` de `subprocess`. El contexto real de
    una causa suele traer caracteres fuera de ese rango (guiones no
    separables, flechas, etc.), lo que hace fallar la escritura en ese
    hilo en silencio: `claude -p` no recibe stdin, agota el timeout de
    espera y termina con exit code distinto de cero (confirmado en una
    corrida real, con la mitad de las llamadas de razonamiento fallando
    así).

    Si se entrega `ruta_archivo`, se agrega `--allowedTools Read --add-dir
    <carpeta_del_archivo>` — el mínimo privilegio necesario para que Claude
    pueda leer ESE archivo puntual con su herramienta Read (soporta PDFs,
    incluido modo visión para escaneos sin capa de texto) sin habilitar
    ninguna otra herramienta ni acceso a ningún otro directorio. Nunca se
    usa `--dangerously-skip-permissions`."""
    ejecutable = shutil.which("claude")
    if ejecutable is None:
        raise RuntimeError("No se encontró el ejecutable 'claude' en el PATH.")

    argv = [ejecutable, "-p"]
    if ruta_archivo is not None:
        argv += ["--allowedTools", "Read", "--add-dir", str(Path(ruta_archivo).parent)]

    resultado = subprocess.run(
        argv,
        input=prompt,
        capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SEGUNDOS, check=False,
    )
    if resultado.returncode != 0:
        raise RuntimeError(
            f"claude -p terminó con código {resultado.returncode}: {resultado.stderr[:500]}"
        )
    return resultado.stdout
```

Agregá el import de `Path` al principio del archivo (junto a los imports existentes de
`json`, `shutil`, `subprocess`):

```python
from pathlib import Path
```

- [ ] **Step 4: Corré los tests y confirmá que pasan**

Run: `pytest tests/test_reasoning.py -v`
Expected: PASS (todos los tests del archivo, incluidos los ya existentes).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/reasoning.py" "Actualizador de informes/tests/test_reasoning.py"
git commit -m "feat(gestion_causas): reasoning soporta lectura acotada de un archivo con Read

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

(Commit ese trailer verbatim, sin importar qué modelo lo ejecute.)

---

### Task 2: CECO por regex sobre los mensajes del hilo

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

**Interfaces:**
- Consumes: nada nuevo de otras tasks.
- Produces: `_buscar_ceco_en_mensajes(mensajes: list[dict]) -> str | None`.

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`:

```python
class TestBuscarCecoEnMensajes:
    def test_encuentra_ceco_en_el_primer_mensaje(self):
        mensajes = [{"cuerpo_texto": "Les confirmamos el CECO: T-4521 para esta causa."}]
        assert smu._buscar_ceco_en_mensajes(mensajes) == "T-4521"

    def test_encuentra_ceco_en_un_mensaje_posterior(self):
        mensajes = [
            {"cuerpo_texto": "Estimados, queda pendiente el CECO."},
            {"cuerpo_texto": "El CECO es 8890."},
        ]
        assert smu._buscar_ceco_en_mensajes(mensajes) == "8890"

    def test_sin_ceco_en_ningun_mensaje_devuelve_none(self):
        mensajes = [{"cuerpo_texto": "No hay CECO mencionado acá."}]
        assert smu._buscar_ceco_en_mensajes(mensajes) is None
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k BuscarCecoEnMensajes -v`
Expected: FAIL con `AttributeError: module 'gestion_causas.fases.smu' has no attribute '_buscar_ceco_en_mensajes'`

- [ ] **Step 3: Implementá la función**

En `gestion_causas/fases/smu.py`, agregá `import re` junto a los imports existentes (después
de `from __future__ import annotations`, antes de `from pathlib import Path`), y agregá la
función cerca de `_dominio`/`_origen_cadena` (funciones auxiliares del módulo):

```python
_PATRON_CECO = re.compile(r"ceco\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-]{1,15})", re.IGNORECASE)


def _buscar_ceco_en_mensajes(mensajes: list[dict]) -> str | None:
    """Busca un CECO mencionado en cualquiera de los mensajes del hilo (ver
    subagentes/smu.md paso 2f: puede venir en el primer mensaje o en una
    respuesta posterior, ej. "nos confirme el CECO 8890"). Best-effort por
    regex, sin Claude — si de verdad no está en ningún mensaje, se completa
    en una corrida futura cuando llegue."""
    for mensaje in mensajes:
        coincidencia = _PATRON_CECO.search(mensaje.get("cuerpo_texto", ""))
        if coincidencia:
            return coincidencia.group(1).upper()
    return None
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -k BuscarCecoEnMensajes -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu busca el CECO por regex en los mensajes del hilo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Ajustes de la demanda (Claude lee el PDF) + guardar CECO/fecha_despido en el registro

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

**Interfaces:**
- Consumes: `reasoning.preguntar(tarea, contexto, schema, *, ejecutar=None, ruta_archivo=None)` (Task 1), `_buscar_ceco_en_mensajes` (Task 2).
- Produces: `SCHEMA_AJUSTES_DEMANDA`, `_evaluar_ajustes_demanda(campos: dict, ruta_demanda: Path) -> dict` (con claves `fecha_despido`, `ajuste_base_calculo`, `otros_ajustes`, o `error`). La entrada del registro de cada causa nueva ahora incluye `"ceco"` y `"fecha_despido"`.

**Nota importante:** a partir de esta task, **toda** causa nueva con demanda guardada dispara
un segundo llamado a `reasoning.preguntar` (además del ya existente para el "Resumen" del
Excel). Los tests `TestResumenYExcel` y `TestRegistrarEtiquetarYMarcarProcesado`
(`tests/fases/test_smu.py`, ya existentes de Plan A) monkeypatchean `smu.reasoning.preguntar`
con un lambda de 3 parámetros posicionales (`lambda tarea, contexto, schema: ...`) que se
usa para **todos** los llamados a reasoning dentro de `correr()` en esa corrida de test —
incluido este nuevo. Como el código llama `reasoning.preguntar(..., ruta_archivo=...)` para
el ajuste, hay que actualizar esos dos lambdas para que acepten `ruta_archivo=None` (si no,
truena con `TypeError: unexpected keyword argument 'ruta_archivo'`). El resto del código
sigue accediendo a los campos de la respuesta con `.get(...)` con default, así que una
respuesta "equivocada" (como la del fake, que solo trae `"resumen"`) no rompe nada — el
ajuste simplemente queda vacío para esos tests, que no afirman nada sobre `ceco`/`fecha_despido`.

- [ ] **Step 1: Escribe los tests que fallan**

Agregá a `tests/fases/test_smu.py`:

```python
class TestAjustesDeLaDemanda:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        return carpeta_causa

    def test_llama_a_reasoning_con_ruta_archivo_y_guarda_fecha_despido_y_ceco(self, tmp_path, monkeypatch):
        carpeta_causa = self._monkeypatch_comunes(monkeypatch, tmp_path)
        llamadas = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None):
            if schema is smu.SCHEMA_AJUSTES_DEMANDA:
                llamadas.append(ruta_archivo)
                return {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            return {"resumen": "Texto de prueba."}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert llamadas == [carpeta_causa / "demanda.pdf"]
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["fecha_despido"] == "2026-01-08"

    def test_guarda_el_ceco_encontrado_en_los_mensajes(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI + "\nCECO: T-900\n", "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["ceco"] == "T-900"

    def test_sin_demanda_guardada_no_llama_a_reasoning_de_ajustes(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [],
        }])

        llamadas_ajustes = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None):
            if schema is smu.SCHEMA_AJUSTES_DEMANDA:
                llamadas_ajustes.append(1)
                return {"fecha_despido": None, "ajuste_base_calculo": False, "otros_ajustes": []}
            return {"resumen": "Texto de prueba."}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert llamadas_ajustes == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["fecha_despido"] is None
```

Además, en `TestResumenYExcel` y `TestRegistrarEtiquetarYMarcarProcesado`, cambiá cada
`monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema: ...)`
existente por la misma expresión agregando `ruta_archivo=None` al lambda:
`lambda tarea, contexto, schema, ruta_archivo=None: ...` (mismo cuerpo, no cambia el
`return`). Son 4 apariciones en total entre esas dos clases — actualizalas todas.

- [ ] **Step 2: Corré los tests y confirmá que fallan**

Run: `pytest tests/fases/test_smu.py -k AjustesDeLaDemanda -v`
Expected: FAIL — `smu.SCHEMA_AJUSTES_DEMANDA` no existe todavía y el registro no guarda
`fecha_despido`/`ceco`.

- [ ] **Step 3: Implementá la función de ajustes y guardá los campos en el registro**

En `gestion_causas/fases/smu.py`, agregá el schema y la función cerca de las otras funciones
de reasoning (junto a `SCHEMA_RESUMEN`/`_generar_resumen_narrativo`):

```python
SCHEMA_AJUSTES_DEMANDA = {
    "type": "object",
    "properties": {
        "fecha_despido": {"type": ["string", "null"]},
        "ajuste_base_calculo": {"type": "boolean"},
        "otros_ajustes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["fecha_despido", "ajuste_base_calculo", "otros_ajustes"],
}


def _evaluar_ajustes_demanda(campos: dict, ruta_demanda: Path) -> dict:
    """Lee el PDF de la demanda (Claude la lee con su propia herramienta
    Read, en modo visión si es un escaneo) para detectar, más allá de lo
    que ya viene resumido en el cuadro: la fecha exacta de despido, si se
    demanda una base de cálculo distinta de la indemnización (dispara
    pedir las últimas 6 liquidaciones), y cualquier otro concepto atípico
    que necesite un antecedente puntual para desvirtuarlo (ver
    subagentes/smu.md paso 2k.1 y 2k.4)."""
    contexto = {"campos_del_cuadro": campos}
    tarea = (
        "Leé el archivo de la demanda indicado más abajo con tu herramienta Read (si es "
        "un PDF escaneado sin capa de texto, se lee en modo visión página por página — no "
        "leas más de ~10-12 páginas salvo que el petitorio esté evidentemente más "
        "adelante). Andá directo a la sección de Hechos/Antecedentes (primeras páginas, "
        "después de la identificación de las partes) y a la sección final de "
        "Petitorio/Por tanto — saltate el cuerpo intermedio de fundamentos de derecho "
        "(citas de ley, doctrina, jurisprudencia), no aporta nada nuevo frente al cuadro.\n\n"
        "De ahí extraé: (1) la fecha exacta de despido (formato AAAA-MM-DD, o null si no "
        "se puede determinar con certeza); (2) si se demanda una diferencia en la base de "
        "cálculo de la indemnización por años de servicio o de la sustitutiva de aviso "
        "previo (ajuste_base_calculo=true en ese caso); (3) cualquier otro concepto "
        "demandado atípico más allá de lo típico (ej. un descuento indebido en el "
        "finiquito por un préstamo, una diferencia por horas extraordinarias) — por cada "
        "uno, un string corto y escueto con el nombre del antecedente que permitiría "
        "desvirtuarlo o estudiar su procedencia (ej. 'Antecedentes de la procedencia del "
        "préstamo'), sin explicar por qué. Si no hay ninguno, devolvé una lista vacía."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_AJUSTES_DEMANDA, ruta_archivo=ruta_demanda)
```

Dentro del `for hilo_resumen in hilos:`, justo después de
`if registro_mod.causa_ya_registrada(rit, ruta=ruta_registro_causas): continue`, agregá la
búsqueda de CECO:

```python
        ceco = _buscar_ceco_en_mensajes(mensajes)
```

Y después del bloque que guarda la demanda (después de `if not demanda_guardada: notas.append(...)`),
agregá la evaluación de ajustes:

```python
        ajustes: dict = {}
        if demanda_guardada:
            ajustes = _evaluar_ajustes_demanda(campos, carpeta / "demanda.pdf")
            if ajustes.get("error"):
                acciones.append({
                    "rit": rit,
                    "que": f"No se pudieron detectar los ajustes de la demanda automáticamente: {ajustes['error']}",
                    "urgencia": "media",
                })
```

Finalmente, en el dict que arma `registro_mod.registrar_causa(...)`, agregá las dos claves
nuevas:

```python
        registro_mod.registrar_causa(
            rit,
            {
                "empresa": empresa,
                "demandante": campos.get("demandante", ""),
                "carpeta": str(carpeta),
                "thread_id": thread_id,
                "tiene_demanda": demanda_guardada,
                "aplica_excel": empresa not in EMPRESAS_SIN_EXCEL,
                "ceco": ceco,
                "fecha_despido": ajustes.get("fecha_despido"),
            },
            ruta=ruta_registro_causas,
        )
```

- [ ] **Step 4: Corré los tests y confirmá que pasan**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (todos los tests del archivo, incluidos los de Plan A ya ajustados).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu detecta ajustes de la demanda leyendo el PDF y guarda ceco/fecha_despido

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Reuso de EERR de una causa anterior del mismo CECO

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Modify: `gestion_causas/orquestador.py`
- Test: `tests/fases/test_smu.py`
- Test: `tests/test_orquestador.py`

**Interfaces:**
- Consumes: `registro_mod.buscar_eerr_reusable(ceco, fecha_despido, dias_tolerancia=90, ruta=...) -> dict | None`, `registro_mod.obtener_causa(rit, ruta=...) -> dict | None`, `carpetas_mod.listar_archivos_carpeta(carpeta) -> list`, `carpetas_mod.parece_eerr(nombre) -> bool`, `carpetas_mod.copiar_archivo_local(origen, carpeta_destino, nombre_archivo) -> dict` (todas ya existentes, sin cambios).
- Produces: `correr()` gana el kwarg `ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO`. Variable local `eerr_reusable: dict | None` disponible para Task 5.

- [ ] **Step 1: Escribe los tests que fallan**

Agregá a `tests/fases/test_smu.py`:

```python
class TestReusoDeEerr:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path, cuerpo_extra=""):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI + cuerpo_extra, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))
        return carpeta_causa

    def test_copia_el_eerr_de_la_causa_anterior_cuando_hay_uno_reusable(self, tmp_path, monkeypatch):
        carpeta_causa = self._monkeypatch_comunes(monkeypatch, tmp_path, cuerpo_extra="\nCECO: T-900\n")

        carpeta_causa_anterior = tmp_path / "Minutas" / "Soto con Alvi M-9-2025"
        carpeta_causa_anterior.mkdir(parents=True)
        (carpeta_causa_anterior / "EERR 2025.pdf").write_bytes(b"eerr viejo")

        ruta_registro = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("M-9-2025", {"carpeta": str(carpeta_causa_anterior)}, ruta=ruta_registro)

        ruta_ceco = tmp_path / "registro_ceco.json"
        registro_mod.registrar_eerr_recibido("T-900", "2025-11-01", "M-9-2025", ruta=ruta_ceco)

        smu.correr(
            {"fecha_hoy": "2026-09-16"},
            ruta_registro_causas=ruta_registro,
            ruta_registro_ceco=ruta_ceco,
        )

        assert (carpeta_causa / "EERR 2025.pdf").exists()

    def test_sin_eerr_reusable_no_copia_nada(self, tmp_path, monkeypatch):
        carpeta_causa = self._monkeypatch_comunes(monkeypatch, tmp_path, cuerpo_extra="\nCECO: T-901\n")

        ruta_registro = tmp_path / "registro_causas.json"
        ruta_ceco = tmp_path / "registro_ceco.json"

        smu.correr(
            {"fecha_hoy": "2026-09-16"},
            ruta_registro_causas=ruta_registro,
            ruta_registro_ceco=ruta_ceco,
        )

        assert list(carpeta_causa.iterdir()) == [carpeta_causa / "demanda.pdf"]
```

Y a `tests/test_orquestador.py`, agregá (en la clase `TestOrquestadorDespachaSmu` ya
existente, o como test suelto si esa clase no existe con ese nombre en el archivo actual):

```python
    def test_smu_recibe_ruta_registro_ceco(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-16"}), encoding="utf-8")

        llamadas = []
        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])
        monkeypatch.setattr(orquestador.fases_smu, "correr", lambda *a, **k: llamadas.append(k) or {"fase": "smu"})

        orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert llamadas[0]["ruta_registro_ceco"] == tmp_path / "registro_ceco.json"
```

- [ ] **Step 2: Corré los tests y confirmá que fallan**

Run: `pytest tests/fases/test_smu.py -k ReusoDeEerr -v` y
`pytest tests/test_orquestador.py -k smu_recibe_ruta_registro_ceco -v`
Expected: FAIL — `correr()` no acepta `ruta_registro_ceco` todavía, y `orquestador.py` no se
lo pasa.

- [ ] **Step 3: Implementá el reuso de EERR**

En `gestion_causas/fases/smu.py`, cambiá la firma de `correr()`:

```python
def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
```

Después del bloque de ajustes agregado en Task 3 (después del `if ajustes.get("error"):
acciones.append(...)`), agregá:

```python
        eerr_reusable = None
        if demanda_guardada and ceco and ajustes.get("fecha_despido"):
            eerr_reusable = registro_mod.buscar_eerr_reusable(
                ceco, ajustes["fecha_despido"], ruta=ruta_registro_ceco
            )
            if eerr_reusable:
                causa_reusable = registro_mod.obtener_causa(
                    eerr_reusable["rit_causa"], ruta=ruta_registro_causas
                )
                if causa_reusable and causa_reusable.get("carpeta"):
                    carpeta_reusable = Path(causa_reusable["carpeta"])
                    nombre_eerr = next(
                        (
                            nombre for nombre in carpetas_mod.listar_archivos_carpeta(carpeta_reusable)
                            if carpetas_mod.parece_eerr(nombre)
                        ),
                        None,
                    )
                    if nombre_eerr:
                        carpetas_mod.copiar_archivo_local(
                            carpeta_reusable / nombre_eerr, carpeta, nombre_eerr
                        )
```

En `gestion_causas/orquestador.py`, cambiá la tupla de fases para que `smu` también reciba
`ruta_registro_ceco`:

```python
    fases = {}
    for nombre, funcion, kwargs_extra in (
        ("smu", fases_smu.correr, {"ruta_registro_ceco": ruta_registro_ceco}),
        ("goteo", fases_goteo.correr, {"ruta_registro_ceco": ruta_registro_ceco}),
    ):
```

- [ ] **Step 4: Corré los tests y confirmá que pasan**

Run: `pytest tests/fases/test_smu.py tests/test_orquestador.py -v`
Expected: PASS (todos los tests de ambos archivos).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/gestion_causas/orquestador.py" "Actualizador de informes/tests/fases/test_smu.py" "Actualizador de informes/tests/test_orquestador.py"
git commit -m "feat(gestion_causas): smu reusa el EERR de una causa anterior del mismo CECO

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Armar la lista de documentos a solicitar

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

**Interfaces:**
- Consumes: `ajustes` dict de Task 3 (`ajuste_base_calculo`, `otros_ajustes`), `eerr_reusable` de Task 4.
- Produces: `LISTA_DOCUMENTOS_BASE: list[str]`, `_armar_lista_documentos(ajustes: dict, eerr_reusado: bool) -> list[str]` (función pura, sin llamadas externas).

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`:

```python
class TestArmarListaDocumentos:
    def test_lista_base_sin_ajustes_ni_reuso(self):
        lista = smu._armar_lista_documentos({"ajuste_base_calculo": False, "otros_ajustes": []}, eerr_reusado=False)
        assert lista == [
            "Contrato de trabajo y anexos",
            "Carta de despido",
            "Finiquito",
            "EERR del local de los años 2024, 2025 y 2026",
            "Comparativa de dotación del local antes y después del despido",
            "Testigos",
            "Absolvente",
        ]

    def test_con_reuso_de_eerr_quita_el_punto_del_eerr(self):
        lista = smu._armar_lista_documentos({"ajuste_base_calculo": False, "otros_ajustes": []}, eerr_reusado=True)
        assert not any("EERR" in d for d in lista)
        assert len(lista) == 6

    def test_ajuste_base_calculo_agrega_liquidaciones_antes_de_testigos(self):
        lista = smu._armar_lista_documentos({"ajuste_base_calculo": True, "otros_ajustes": []}, eerr_reusado=False)
        indice = lista.index("Últimas 6 liquidaciones de remuneraciones")
        assert indice == lista.index("Testigos") - 1

    def test_otros_ajustes_se_agregan_antes_de_testigos_en_orden(self):
        lista = smu._armar_lista_documentos(
            {"ajuste_base_calculo": False, "otros_ajustes": ["Antecedentes del préstamo", "Registro de horas extra"]},
            eerr_reusado=False,
        )
        indice_testigos = lista.index("Testigos")
        assert lista[indice_testigos - 2] == "Antecedentes del préstamo"
        assert lista[indice_testigos - 1] == "Registro de horas extra"

    def test_ajuste_base_calculo_y_otros_ajustes_combinados(self):
        lista = smu._armar_lista_documentos(
            {"ajuste_base_calculo": True, "otros_ajustes": ["Antecedentes del préstamo"]},
            eerr_reusado=True,
        )
        assert not any("EERR" in d for d in lista)
        indice_testigos = lista.index("Testigos")
        assert lista[indice_testigos - 2] == "Últimas 6 liquidaciones de remuneraciones"
        assert lista[indice_testigos - 1] == "Antecedentes del préstamo"
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k ArmarListaDocumentos -v`
Expected: FAIL con `AttributeError: module 'gestion_causas.fases.smu' has no attribute '_armar_lista_documentos'`

- [ ] **Step 3: Implementá la función**

En `gestion_causas/fases/smu.py`, agregá cerca de `QUERY_CANDIDATOS` (constantes de módulo):

```python
LISTA_DOCUMENTOS_BASE = [
    "Contrato de trabajo y anexos",
    "Carta de despido",
    "Finiquito",
    "EERR del local de los años 2024, 2025 y 2026",
    "Comparativa de dotación del local antes y después del despido",
    "Testigos",
    "Absolvente",
]
```

Y agregá la función junto a las demás funciones auxiliares del módulo:

```python
def _armar_lista_documentos(ajustes: dict, eerr_reusado: bool) -> list[str]:
    """Arma la lista de documentos a solicitar (ver subagentes/smu.md paso
    2k.2-2k.4): parte de la lista base, quita el punto del EERR si se
    reusó uno de una causa anterior del mismo CECO, y agrega los ajustes
    que detectó Claude (base de cálculo distinta, u otros conceptos
    atípicos) justo antes de Testigos y Absolvente."""
    lista = list(LISTA_DOCUMENTOS_BASE)
    if eerr_reusado:
        lista = [documento for documento in lista if "EERR" not in documento]

    ajustes_a_insertar = []
    if ajustes.get("ajuste_base_calculo"):
        ajustes_a_insertar.append("Últimas 6 liquidaciones de remuneraciones")
    ajustes_a_insertar += list(ajustes.get("otros_ajustes", []))

    if not ajustes_a_insertar:
        return lista

    indice_testigos = lista.index("Testigos")
    return lista[:indice_testigos] + ajustes_a_insertar + lista[indice_testigos:]
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -k ArmarListaDocumentos -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu arma la lista de documentos a solicitar

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Crear el borrador (con deduplicación) y guardarlo en el registro

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

**Interfaces:**
- Consumes: `_armar_lista_documentos` (Task 5), `eerr_reusable` (Task 4), `gmail_client.listar_borradores_de_hilo(thread_id) -> list`, `gmail_client.crear_borrador(destinatario, asunto, cuerpo_texto, thread_id=None, html=False) -> dict` (ambas ya existentes), `extraer_direccion` (ya importado en el módulo).
- Produces: `_cuerpo_html_lista(documentos: list[str]) -> str`. La entrada del registro gana `"borrador_documentos_draft_id"` y `"documentos_solicitados"`. El resumen final gana las métricas "Borradores de documentos creados" y "EERR reusado".

- [ ] **Step 1: Escribe los tests que fallan**

Agregá a `tests/fases/test_smu.py`:

```python
class TestCrearBorradorDeDocumentos:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA Rit M-1-2026",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))
        return carpeta_causa

    def test_crea_el_borrador_como_respuesta_del_hilo_con_lista_html(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])

        llamadas = []
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: llamadas.append((a, k)) or {"id": "draft-1"})

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert len(llamadas) == 1
        args, kwargs = llamadas[0]
        assert args[0] == "persona@smu.cl"
        assert "M-1-2026" in args[1] or "DEMANDA" in args[1]
        assert "<ol>" in args[2] and "<li>Contrato de trabajo y anexos</li>" in args[2]
        assert kwargs["thread_id"] == "thread-1"
        assert kwargs["html"] is True

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["borrador_documentos_draft_id"] == "draft-1"
        assert entrada["documentos_solicitados"][0] == "Contrato de trabajo y anexos"

    def test_no_duplica_borrador_si_la_cadena_ya_tiene_uno(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [{"id": "draft-viejo"}])

        llamadas = []
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: llamadas.append(1) or {"id": "draft-nuevo"})

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert llamadas == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["borrador_documentos_draft_id"] is None

    def test_metricas_incluyen_borradores_creados_y_eerr_reusado(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        etiquetas = {m["etiqueta"] for m in resumen["metricas"]}
        assert "Borradores de documentos creados" in etiquetas
        assert "EERR reusado" in etiquetas
```

- [ ] **Step 2: Corré los tests y confirmá que fallan**

Run: `pytest tests/fases/test_smu.py -k CrearBorradorDeDocumentos -v`
Expected: FAIL — todavía no se crea ningún borrador ni se guardan esos campos.

- [ ] **Step 3: Implementá la creación del borrador**

En `gestion_causas/fases/smu.py`, agregá la función auxiliar junto a `_armar_lista_documentos`:

```python
def _cuerpo_html_lista(documentos: list[str]) -> str:
    """Cuerpo del borrador: únicamente la lista numerada de documentos, sin
    saludo ni firma (ver subagentes/smu.md paso 2k.5). Se manda como HTML
    (`<ol><li>`) para que Gmail la reciba como lista numerada nativa — así
    se puede insertar o quitar un documento en el medio sin renumerar el
    resto a mano."""
    items = "".join(f"<li>{documento}</li>" for documento in documentos)
    return f"<ol>{items}</ol>"
```

Inicializá los contadores de métricas al principio de `correr()`, junto a `causas_nuevas = 0`:

```python
    causas_nuevas = 0
    borradores_creados = 0
    eerr_reusado_contador = 0
```

Marcá con `eerr_reusado_contador += 1` el bloque de Task 4 cuando efectivamente copia el
archivo (dentro del `if nombre_eerr:`):

```python
                    if nombre_eerr:
                        carpetas_mod.copiar_archivo_local(
                            carpeta_reusable / nombre_eerr, carpeta, nombre_eerr
                        )
                        eerr_reusado_contador += 1
```

Después del bloque de reuso de EERR de Task 4 (antes del bloque que escribe la fila del
Excel, o después — no importa el orden entre ambos), agregá la creación del borrador:

```python
        documentos_solicitados: list[str] = []
        draft_id = None
        if demanda_guardada:
            documentos_solicitados = _armar_lista_documentos(ajustes, eerr_reusado=bool(eerr_reusable))
            if not gmail_client.listar_borradores_de_hilo(thread_id):
                destinatario = extraer_direccion(primer_mensaje.get("sender", ""))
                asunto = f"Re: {primer_mensaje.get('subject', '')}"
                cuerpo_html = _cuerpo_html_lista(documentos_solicitados)
                borrador = gmail_client.crear_borrador(
                    destinatario, asunto, cuerpo_html, thread_id=thread_id, html=True
                )
                draft_id = borrador.get("id")
                borradores_creados += 1
```

Agregá las dos claves nuevas al dict de `registrar_causa`:

```python
        registro_mod.registrar_causa(
            rit,
            {
                "empresa": empresa,
                "demandante": campos.get("demandante", ""),
                "carpeta": str(carpeta),
                "thread_id": thread_id,
                "tiene_demanda": demanda_guardada,
                "aplica_excel": empresa not in EMPRESAS_SIN_EXCEL,
                "ceco": ceco,
                "fecha_despido": ajustes.get("fecha_despido"),
                "borrador_documentos_draft_id": draft_id,
                "documentos_solicitados": documentos_solicitados,
            },
            ruta=ruta_registro_causas,
        )
```

Y agregá las dos métricas nuevas al `resumen` final:

```python
    resumen = {
        "fase": "smu",
        "titular": _armar_titular(causas_nuevas),
        "metricas": [
            {"etiqueta": "Causas nuevas", "valor": causas_nuevas},
            {"etiqueta": "Borradores de documentos creados", "valor": borradores_creados},
            {"etiqueta": "EERR reusado", "valor": eerr_reusado_contador},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
```

- [ ] **Step 4: Corré los tests y confirmá que pasan**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (todos los tests del archivo)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu crea el borrador de documentos con deduplicacion

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Bitácora del borrador + suite completa + verificación manual

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`, dentro de `TestCrearBorradorDeDocumentos`:

```python
    def test_bitacora_menciona_el_borrador_creado(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})

        mensajes_bitacora = []
        monkeypatch.setattr(smu.bitacora_mod, "registrar", lambda mensaje, rit=None: mensajes_bitacora.append(mensaje))

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert any("borrador" in m.lower() for m in mensajes_bitacora)
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k bitacora_menciona_el_borrador_creado -v`
Expected: FAIL — la bitácora actual no menciona el borrador.

- [ ] **Step 3: Extendé el mensaje de bitácora**

En `gestion_causas/fases/smu.py`, reemplazá la llamada a `bitacora_mod.registrar` existente:

```python
        bitacora_mod.registrar(
            f"Causa nueva registrada ({empresa}), carpeta '{carpeta.name}'"
            + ("" if demanda_guardada else " — sin demanda adjunta, súbela a mano")
            + (f"; borrador de documentos creado ({len(documentos_solicitados)} items)" if draft_id else ""),
            rit=rit,
        )
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (todos los tests del archivo)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): bitacora de smu menciona el borrador de documentos creado

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Corré toda la suite**

Run: `pytest -q`
Expected: PASS — todos los tests existentes más los nuevos de este plan, sin FAIL ni ERROR
(aparte de cualquier falla preexistente ya conocida y no relacionada con este plan).

- [ ] **Step 7: Si algo falla, arreglalo antes de seguir**

- [ ] **Step 8: Verificación manual — correr en paralelo con el subagente `smu.md`**

Mismo criterio que se usó para Plan A y para `goteo`: armar el contexto de corrida
(`python -m gestion_causas.cli contexto-corrida ...`), correr
`python -m gestion_causas.orquestador`, y comparar el resultado contra lo que produce hoy el
subagente `smu.md` en la próxima corrida real. **Antes** de correrlo contra Gmail real,
confirmar con Nico que quiere esa corrida en vivo — esta fase ahora también crea borradores
de correo de verdad (aunque nunca los envía) y copia archivos entre carpetas de Minutas, así
que vale la pena que lo sepa de antemano igual que las veces anteriores. No se desactiva
`subagentes/smu.md` todavía.
