# Driver Python para "goteo" (piloto) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar la fase "goteo" del ciclo de gestión de causas de un subagente de Claude Code que lee `gestion_causas/subagentes/goteo.md` a un driver Python (`gestion_causas/fases/goteo.py`) que controla todo el bucle y solo invoca a Claude (headless, `claude -p`) para el único punto que requiere razonamiento sobre texto libre: decidir si un hilo confirma que se alcanzó/pagó un acuerdo.

**Architecture:** Todo lo mecánico (causas activas, carpeta destino según tipo de audiencia, filtro de dominio confiable, de-dupe de adjuntos, detección de EERR) se implementa como funciones Python puras que llaman directo a los módulos ya existentes (`registro.py`, `carpetas.py`, `gmail_client.py`, `seguimiento.py`) — sin pasar por subprocess del CLI. Un módulo nuevo y angosto, `gestion_causas/reasoning.py`, es el único punto de contacto con Claude: arma un prompt acotado + schema JSON, corre `claude -p` como subprocess, parsea la respuesta con un reintento. `gestion_causas/orquestador.py` (nuevo, alcance mínimo en este plan) lee `_contexto_corrida.json` y despacha la fase goteo, aislando errores.

**Tech Stack:** Python 3, pytest, `subprocess` (para invocar `claude -p`), librerías ya existentes del proyecto (`gestion_causas/*.py`).

---

## Alcance de este plan

Este plan cubre **solo el piloto de la fase `goteo`**, como primer tramo migrable y
testeable del rediseño descrito en
`docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md`. Las fases
`smu`, `agenda`, `seguimiento` y `calendario` se migran en planes posteriores, una vez
validado este patrón corriendo en paralelo con el subagente `.md` viejo.

**Fuera de alcance de este plan** (a propósito, YAGNI):
- El modo "corriendo suelto sin contexto de corrida" que soporta `goteo.md` hoy (fallback
  en vivo si `_contexto_corrida.json` no existe). El driver Python de este plan **requiere**
  que `orquestador.py` haya armado el contexto antes — si no existe, falla con un mensaje
  claro. El fallback se puede agregar en un plan posterior si hace falta correr `goteo`
  suelto.
- Migrar `smu`/`agenda`/`seguimiento`/`calendario` — quedan con su subagente `.md` actual
  sin cambios.
- Desactivar `gestion-causas-orquestador` (la tarea programada actual que despacha los 5
  subagentes) — sigue corriendo igual. `orquestador.py` de este plan es un script nuevo,
  independiente, que se corre a mano en paralelo para comparar resultados (ver Task 11).
- El comprobante de pago detectado pero de un dominio no confiable, que `goteo.md` anota
  en `notas` sin descargar. En el piloto ese caso simplemente no guarda el adjunto (mismo
  comportamiento que cualquier adjunto de dominio no confiable) sin agregar la nota
  explicativa — se agrega en un ajuste posterior si hace falta.

## Sobre las rutas de archivo en los tests (`ruta_registro_causas` / `ruta_registro_ceco`)

Las funciones de `registro.py` (`causas_para_goteo`, `registrar_causa`, `obtener_causa`,
`registrar_eerr_recibido`) reciben un parámetro `ruta` con un valor por defecto
(`RUTA_REGISTRO_CAUSAS` / `RUTA_REGISTRO_CECO`) que Python resuelve **una sola vez, al
definir la función** — por eso los tests de este proyecto (ver `tests/test_registro.py`)
nunca hacen `monkeypatch.setattr(registro_mod, "RUTA_REGISTRO_CAUSAS", ...)`, porque no
tendría efecto sobre una función que ya capturó el valor original como default. En su
lugar, siempre pasan `ruta=<tmp_path>/...` explícito en cada llamada.

Por la misma razón, `gestion_causas/fases/goteo.py` recibe `ruta_registro_causas` y
`ruta_registro_ceco` como parámetros de `correr()` (con la ruta de producción como
default) y los pasa explícitamente en cada llamada a `registro_mod.*`. Los tests de este
plan pasan siempre una ruta bajo `tmp_path` — así ningún test toca
`gestion_causas/registro_causas.json` real.

---

### Task 1: Lista de dominios confiables (`seguimiento.py`)

**Files:**
- Modify: `gestion_causas/seguimiento.py`
- Test: `tests/test_seguimiento.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá al final de `tests/test_seguimiento.py`:

```python
from gestion_causas.seguimiento import es_remitente_confiable


class TestEsRemitenteConfiable:
    def test_acepta_dominios_confiables(self):
        assert es_remitente_confiable("Daniela Soto <sorostica@unimarc.cl>")
        assert es_remitente_confiable("nombre@super10.cl")
        assert es_remitente_confiable("nombre@alvi.cl")
        assert es_remitente_confiable("nombre@sb.cl")
        assert es_remitente_confiable("nombre@mayorista10.cl")
        assert es_remitente_confiable("nombre@smu.cl")
        assert es_remitente_confiable("nombre@divisionlogistica.cl")

    def test_rechaza_dominio_no_confiable(self):
        assert not es_remitente_confiable("Nico Munoz <nmunoz@gomezyriesco.cl>")
        assert not es_remitente_confiable("alguien@gmail.com")

    def test_ignora_mayusculas(self):
        assert es_remitente_confiable("Nombre <NOMBRE@SB.CL>")

    def test_remitente_vacio_no_es_confiable(self):
        assert not es_remitente_confiable("")
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_seguimiento.py -k EsRemitenteConfiable -v`
Expected: FAIL con `ImportError: cannot import name 'es_remitente_confiable'`

- [ ] **Step 3: Implementá la función**

Agregá a `gestion_causas/seguimiento.py`, después de `hilo_es_reporte_consolidado` (línea
~247):

```python
# Dominios desde los que RR.HH./legal de las 6 empresas manda documentos de
# prueba reales (contrato, finiquito, EERR, comprobante de pago) en el goteo
# — ver subagentes/goteo.md, nota "Filtro de remitente confiable" para el
# historial de cada dominio agregado.
DOMINIOS_CONFIABLES = {
    "unimarc.cl", "super10.cl", "alvi.cl", "sb.cl",
    "mayorista10.cl", "smu.cl", "divisionlogistica.cl",
}


def es_remitente_confiable(remitente: str) -> bool:
    """True si la dirección de `remitente` (puede venir como 'Nombre <mail>'
    o solo 'mail') termina en uno de `DOMINIOS_CONFIABLES`."""
    direccion = extraer_direccion(remitente)
    if "@" not in direccion:
        return False
    dominio = direccion.rsplit("@", 1)[1].lower()
    return dominio in DOMINIOS_CONFIABLES
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_seguimiento.py -k EsRemitenteConfiable -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/seguimiento.py" "Actualizador de informes/tests/test_seguimiento.py"
git commit -m "feat(gestion_causas): mecanizar filtro de remitente confiable del goteo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Carpeta destino según tipo de audiencia (`carpetas.py`)

**Files:**
- Modify: `gestion_causas/carpetas.py`
- Test: `tests/test_carpetas.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá al final de `tests/test_carpetas.py`:

```python
from gestion_causas.carpetas import carpeta_destino_por_tipo_audiencia


class TestCarpetaDestinoPorTipoAudiencia:
    def test_juicio_usa_subcarpeta_exhibicion(self, tmp_path):
        carpeta_causa = tmp_path / "Perez con Alvi"
        destino = carpeta_destino_por_tipo_audiencia(carpeta_causa, "Juicio")
        assert destino == carpeta_causa / "Exhibición de documentos"

    def test_unica_usa_carpeta_normal(self, tmp_path):
        carpeta_causa = tmp_path / "Perez con Alvi"
        assert carpeta_destino_por_tipo_audiencia(carpeta_causa, "Unica") == carpeta_causa

    def test_preparatoria_usa_carpeta_normal(self, tmp_path):
        carpeta_causa = tmp_path / "Perez con Alvi"
        assert carpeta_destino_por_tipo_audiencia(carpeta_causa, "Preparatoria") == carpeta_causa

    def test_ambiguo_o_sin_tipo_usa_carpeta_normal(self, tmp_path):
        carpeta_causa = tmp_path / "Perez con Alvi"
        assert carpeta_destino_por_tipo_audiencia(carpeta_causa, "Ambiguo") == carpeta_causa
        assert carpeta_destino_por_tipo_audiencia(carpeta_causa, None) == carpeta_causa
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_carpetas.py -k CarpetaDestinoPorTipoAudiencia -v`
Expected: FAIL con `ImportError`

- [ ] **Step 3: Implementá la función**

Agregá a `gestion_causas/carpetas.py`, después de `listar_archivos_carpeta` (final del
archivo):

```python
def carpeta_destino_por_tipo_audiencia(carpeta_causa: Path, tipo: str | None) -> Path:
    """Carpeta donde guardar documentos del goteo según el tipo de la próxima
    audiencia (ver subagentes/goteo.md paso 3a): si es "Juicio", los
    documentos van en la subcarpeta "Exhibición de documentos" (no se crea acá
    — `guardar_adjunto` la crea sola si no existe). Cualquier otro tipo
    (Única, Preparatoria, Ambiguo o None) usa la carpeta de la causa
    directamente."""
    if tipo == "Juicio":
        return carpeta_causa / "Exhibición de documentos"
    return carpeta_causa
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_carpetas.py -k CarpetaDestinoPorTipoAudiencia -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/carpetas.py" "Actualizador de informes/tests/test_carpetas.py"
git commit -m "feat(gestion_causas): mecanizar carpeta destino segun tipo de audiencia

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Módulo `reasoning.py` — invocación acotada a Claude

**Files:**
- Create: `gestion_causas/reasoning.py`
- Test: `tests/test_reasoning.py`

- [ ] **Step 1: Escribe el test que falla**

Creá `tests/test_reasoning.py`:

```python
import json

from gestion_causas.reasoning import preguntar


SCHEMA_SIMPLE = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


class TestPreguntar:
    def test_devuelve_json_parseado_cuando_la_respuesta_es_valida(self):
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        resultado = preguntar("tarea de prueba", {"dato": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert resultado == {"ok": True}
        assert len(llamadas) == 1
        assert "tarea de prueba" in llamadas[0]
        assert '"dato": 1' in llamadas[0]

    def test_ignora_bloque_de_codigo_markdown(self):
        def ejecutar_falso(prompt):
            return "```json\n" + json.dumps({"ok": True}) + "\n```"

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)
        assert resultado == {"ok": True}

    def test_reintenta_una_vez_si_la_primera_respuesta_no_es_json(self):
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            if len(llamadas) == 1:
                return "esto no es JSON"
            return json.dumps({"ok": True})

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert resultado == {"ok": True}
        assert len(llamadas) == 2
        assert "no era JSON válido" in llamadas[1]

    def test_devuelve_error_si_falla_dos_veces(self):
        def ejecutar_falso(prompt):
            return "esto tampoco es JSON"

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert "error" in resultado
        assert isinstance(resultado["error"], str)
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_reasoning.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.reasoning'`

- [ ] **Step 3: Implementá el módulo**

Creá `gestion_causas/reasoning.py`:

```python
"""Único punto de contacto entre el driver Python de gestion_causas y Claude.

Se usa solo para los pasos que requieren razonamiento sobre texto libre (ver
docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md) — el
resto del flujo es Python puro. Cada llamada es acotada: un prompt corto con
el contexto mínimo necesario (nunca un .md completo ni un hilo/PDF sin
filtrar) y un schema de salida JSON fijo.
"""

from __future__ import annotations

import json
import subprocess


def preguntar(tarea: str, contexto: dict, schema: dict, *, ejecutar=None) -> dict:
    """Le pide a Claude que resuelva `tarea` sobre `contexto`, devolviendo un
    dict que cumple `schema`. Reintenta una vez si la respuesta no es JSON
    válido; si vuelve a fallar, devuelve `{"error": "<detalle>"}` en vez de
    lanzar una excepción — el llamador decide qué hacer con eso (típicamente
    anotarlo en `acciones` del resumen y seguir con la siguiente causa).

    `ejecutar` es inyectable para tests: recibe el prompt armado y devuelve el
    texto de salida de Claude. Por defecto corre `claude -p "<prompt>"`.
    """
    ejecutar = ejecutar or _ejecutar_claude

    prompt = _armar_prompt(tarea, contexto, schema)
    salida = ejecutar(prompt)
    resultado = _parsear_json(salida)
    if resultado is not None:
        return resultado

    prompt_reintento = _armar_prompt(tarea, contexto, schema, error_previo=salida)
    salida_reintento = ejecutar(prompt_reintento)
    resultado_reintento = _parsear_json(salida_reintento)
    if resultado_reintento is not None:
        return resultado_reintento

    return {
        "error": (
            "Claude no devolvió JSON válido tras 2 intentos. "
            f"Última respuesta: {salida_reintento[:500]!r}"
        )
    }


def _armar_prompt(tarea: str, contexto: dict, schema: dict, error_previo: str | None = None) -> str:
    partes = [
        tarea,
        "",
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


def _parsear_json(texto: str) -> dict | None:
    texto = texto.strip()
    if texto.startswith("```"):
        sin_cerca = texto.strip("`")
        texto = sin_cerca.split("\n", 1)[1] if "\n" in sin_cerca else sin_cerca
        if texto.lower().startswith("json"):
            texto = texto[4:]
        texto = texto.strip()
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, ValueError):
        return None


def _ejecutar_claude(prompt: str) -> str:
    resultado = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=120, check=False,
    )
    return resultado.stdout
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_reasoning.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/reasoning.py" "Actualizador de informes/tests/test_reasoning.py"
git commit -m "feat(gestion_causas): agregar reasoning.py, unico punto de contacto con Claude

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Paquete `gestion_causas/fases/` y esqueleto de `goteo.correr()`

**Files:**
- Create: `gestion_causas/fases/__init__.py`
- Create: `gestion_causas/fases/goteo.py`
- Create: `tests/fases/__init__.py`
- Test: `tests/fases/test_goteo.py`

- [ ] **Step 1: Escribe el test que falla**

Creá `tests/fases/__init__.py` (vacío) y `tests/fases/test_goteo.py`:

```python
from gestion_causas.fases import goteo


class TestCorrerSinCausasActivas:
    def test_devuelve_resumen_sin_novedades(self, tmp_path):
        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(tmp_path / "no_existe.json")},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = goteo.correr(
            contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resumen["fase"] == "goteo"
        assert resumen["titular"] == "Sin causas activas para revisar"
        assert resumen["items"] == []
        assert resumen["acciones"] == []
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.fases'`

- [ ] **Step 3: Creá el paquete y el esqueleto**

Creá `gestion_causas/fases/__init__.py` (vacío).

Creá `gestion_causas/fases/goteo.py`:

```python
"""Driver Python de la fase 'goteo' (ver spec en
docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md y,
como referencia histórica de las reglas, subagentes/goteo.md).

Revisa las causas activas por si llegaron documentos nuevos en su cadena de
correo. Nunca envía correos ni borra nada, y no toca el calendario. Depende
de que `orquestador.py` ya haya armado `_contexto_corrida.json` antes de
llamar a `correr()` — este módulo no arma su propio contexto (ver "Alcance"
del plan de implementación)."""

from __future__ import annotations

import json
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import registro as registro_mod
from gestion_causas import reasoning
from gestion_causas.carpetas import carpeta_destino_por_tipo_audiencia
from gestion_causas.seguimiento import es_remitente_confiable

NOMBRES_ADJUNTO_EXCLUIDOS = {"invite.ics"}


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    causas = registro_mod.causas_para_goteo(ruta=ruta_registro_causas)
    if not causas:
        return {
            "fase": "goteo",
            "titular": "Sin causas activas para revisar",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    return {
        "fase": "goteo",
        "titular": f"{len(causas)} causas activas revisadas",
        "metricas": [{"etiqueta": "Causas revisadas", "valor": len(causas)}],
        "items": [],
        "acciones": [],
        "notas": [],
    }
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/__init__.py" "Actualizador de informes/gestion_causas/fases/goteo.py" "Actualizador de informes/tests/fases/__init__.py" "Actualizador de informes/tests/fases/test_goteo.py"
git commit -m "feat(gestion_causas): esqueleto del driver Python de la fase goteo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Leer el mapa de hilos y recorrer causas activas

**Files:**
- Modify: `gestion_causas/fases/goteo.py`
- Test: `tests/fases/test_goteo.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_goteo.py` (junto con un helper compartido al principio del
archivo, arriba de `TestCorrerSinCausasActivas`):

```python
import json

from gestion_causas import registro as registro_mod


def _registrar_causa_activa(tmp_path, rit="M-1-2026", **extra):
    ruta_registro = tmp_path / "registro_causas.json"
    datos = {
        "empresa": "Alvi", "demandante": "Perez", "carpeta": str(tmp_path / "Perez con Alvi"),
        "thread_id": "thread-original-1", **extra,
    }
    registro_mod.registrar_causa(rit, datos, ruta=ruta_registro)
    return ruta_registro


def _mapa_hilos_vacio(tmp_path):
    ruta = tmp_path / "mapa_hilos.json"
    ruta.write_text(json.dumps({"rit_a_hilos": {}, "hilos": {}}), encoding="utf-8")
    return ruta


def _correr_goteo(contexto, tmp_path, **kwargs):
    kwargs.setdefault("ruta_registro_causas", tmp_path / "registro_causas.json")
    kwargs.setdefault("ruta_registro_ceco", tmp_path / "registro_ceco.json")
    return goteo.correr(contexto, **kwargs)


class TestCorrerCausaSinNovedades:
    def test_causa_activa_sin_hilos_en_el_mapa_no_genera_items(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_hilos_vacio(tmp_path)

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert resumen["items"] == []
        assert any(m["etiqueta"] == "Causas revisadas" and m["valor"] == 1 for m in resumen["metricas"])
```

(A partir de este Task, todos los tests nuevos usan el helper `_correr_goteo` en vez de
llamar a `goteo.correr` directo, para no repetir las dos rutas de `tmp_path` en cada uno.)

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_goteo.py -k CorrerCausaSinNovedades -v`
Expected: FAIL (`assert any(...)` — la métrica no existe todavía)

- [ ] **Step 3: Implementá la lectura del mapa y el bucle**

Reemplazá el cuerpo de `correr()` en `gestion_causas/fases/goteo.py`:

```python
def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    causas = registro_mod.causas_para_goteo(ruta=ruta_registro_causas)
    if not causas:
        return {
            "fase": "goteo",
            "titular": "Sin causas activas para revisar",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    mapa_hilos = _leer_mapa_hilos(contexto_corrida)
    mapa_audiencias = _leer_mapa_audiencias(contexto_corrida)

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = list(mapa_hilos.get("_notas", []))
    con_documentos_nuevos = 0
    identificados_eerr = 0

    for causa in causas:
        rit = causa["rit"]
        hilos_rit = mapa_hilos.get("rit_a_hilos", {}).get(rit, [])
        mensajes_hilos = [
            mensaje
            for thread_id in hilos_rit
            for mensaje in mapa_hilos.get("hilos", {}).get(thread_id, [])
        ]

        # Paso 3h: siempre se guarda la fecha de revisión, haya o no
        # novedades — permite que la próxima corrida acote el barrido.
        registro_mod.registrar_causa(
            rit, {"goteo_ultima_revision": contexto_corrida["fecha_hoy"]}, ruta=ruta_registro_causas
        )

    resumen = {
        "fase": "goteo",
        "titular": _armar_titular(con_documentos_nuevos, identificados_eerr),
        "metricas": [
            {"etiqueta": "Causas revisadas", "valor": len(causas)},
            {"etiqueta": "Con documentos nuevos", "valor": con_documentos_nuevos},
            {"etiqueta": "Identificados como EERR", "valor": identificados_eerr},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _leer_mapa_hilos(contexto_corrida: dict) -> dict:
    info = contexto_corrida.get("mapa_hilos") or {}
    ruta = info.get("ruta")
    if not ruta or not Path(ruta).exists():
        return {"rit_a_hilos": {}, "hilos": {}, "_notas": []}
    mapa = json.loads(Path(ruta).read_text(encoding="utf-8"))
    notas = []
    for entrada in mapa.get("truncado", []):
        notas.append({
            "tipo": "busqueda_truncada",
            "detalle": f"Búsqueda de {entrada['grupo']} quedó truncada ({entrada['total']} resultados)",
        })
    mapa["_notas"] = notas
    return mapa


def _leer_mapa_audiencias(contexto_corrida: dict) -> dict:
    info = contexto_corrida.get("mapa_audiencias") or {}
    ruta = info.get("ruta")
    if not ruta or not Path(ruta).exists():
        return {"rit_a_audiencia": {}}
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _armar_titular(con_documentos_nuevos: int, identificados_eerr: int) -> str:
    if con_documentos_nuevos == 0:
        return "Sin novedades"
    partes = [f"{con_documentos_nuevos} causas con documentos nuevos"]
    if identificados_eerr:
        partes.append(f"{identificados_eerr} identificados como EERR")
    return ", ".join(partes)
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/goteo.py" "Actualizador de informes/tests/fases/test_goteo.py"
git commit -m "feat(gestion_causas): goteo recorre causas activas y lee el mapa de hilos

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Guardar adjuntos de remitente confiable (carpeta destino + de-dupe)

**Files:**
- Modify: `gestion_causas/fases/goteo.py`
- Test: `tests/fases/test_goteo.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_goteo.py`. Estos tres tests necesitan que `_detectar_acuerdo_y_pago`
no llame de verdad a `reasoning.preguntar` (todavía no existe la lógica del Task 7) — se
la reemplaza con `monkeypatch` para que devuelva "sin novedades de acuerdo":

```python
class TestGuardaAdjuntosDeRemitenteConfiable:
    def test_guarda_adjunto_de_dominio_confiable_y_lo_reporta_en_items(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(tmp_path, carpeta=str(carpeta_causa))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "Daniela <sorostica@unimarc.cl>",
                    "subject": "RV: Documentos", "cuerpo_texto": "Adjunto el contrato",
                    "adjuntos": [{"filename": "contrato.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 1000}],
                }],
            },
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido falso")
        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert (carpeta_causa / "contrato.pdf").exists()
        assert resumen["items"] == [{
            "rit": "M-1-2026", "titulo": "Perez con Alvi",
            "detalle": "1 documentos nuevos: contrato.pdf",
        }]

    def test_ignora_adjunto_de_dominio_no_confiable(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(tmp_path, carpeta=str(carpeta_causa))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl",
                    "subject": "Re: Documentos", "cuerpo_texto": "",
                    "adjuntos": [{"filename": "borrador.docx", "attachment_id": "att-1", "mime_type": "application/msword", "size": 500}],
                }],
            },
        }), encoding="utf-8")

        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert not (carpeta_causa / "borrador.docx").exists()
        assert resumen["items"] == []

    def test_excluye_invite_ics_aunque_sea_dominio_confiable(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(tmp_path, carpeta=str(carpeta_causa))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "nombre@sb.cl",
                    "subject": "Aceptado: Reunión preparatoria", "cuerpo_texto": "",
                    "adjuntos": [{"filename": "invite.ics", "attachment_id": "att-1", "mime_type": "text/calendar", "size": 300}],
                }],
            },
        }), encoding="utf-8")

        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert not (carpeta_causa / "invite.ics").exists()
        assert resumen["items"] == []
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_goteo.py -k GuardaAdjuntosDeRemitenteConfiable -v`
Expected: FAIL (`AttributeError: module 'gestion_causas.fases.goteo' has no attribute
'_detectar_acuerdo_y_pago'` — se agrega recién en este task, como stub, y se completa en
el Task 7)

- [ ] **Step 3: Implementá el guardado de adjuntos**

En `gestion_causas/fases/goteo.py`, agregá el stub de `_detectar_acuerdo_y_pago` (se
completa en el Task 7) cerca de `NOMBRES_ADJUNTO_EXCLUIDOS`:

```python
def _detectar_acuerdo_y_pago(mensajes_hilos: list[dict]) -> dict:
    """Placeholder hasta el Task 7 — se reemplaza por la llamada real a
    reasoning.preguntar."""
    return {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""}
```

Reemplazá el cuerpo del `for causa in causas:` (dentro de `correr()`) por:

```python
    for causa in causas:
        rit = causa["rit"]
        hilos_rit = mapa_hilos.get("rit_a_hilos", {}).get(rit, [])
        mensajes_hilos = [
            mensaje
            for thread_id in hilos_rit
            for mensaje in mapa_hilos.get("hilos", {}).get(thread_id, [])
        ]

        tipo_audiencia = mapa_audiencias.get("rit_a_audiencia", {}).get(rit, {}).get("tipo")
        carpeta_causa = Path(causa["carpeta"])
        carpeta_destino = carpeta_destino_por_tipo_audiencia(carpeta_causa, tipo_audiencia)

        guardados = _guardar_adjuntos_confiables(mensajes_hilos, carpeta_destino)
        if guardados:
            con_documentos_nuevos += 1
            item = {
                "rit": rit,
                "titulo": f"{causa.get('demandante', '')} con {causa.get('empresa', '')}",
                "detalle": f"{len(guardados)} documentos nuevos: {', '.join(g['filename'] for g in guardados)}",
            }
            if tipo_audiencia == "Juicio":
                item["etiqueta"] = "Exhibición de documentos"
            items.append(item)
            bitacora_mod.registrar(
                f"Goteo: se guardaron {len(guardados)} documentos nuevos "
                f"({', '.join(g['filename'] for g in guardados)})"
                + (", en Exhibición de documentos por audiencia de juicio" if tipo_audiencia == "Juicio" else ""),
                rit=rit,
            )

        registro_mod.registrar_causa(
            rit, {"goteo_ultima_revision": contexto_corrida["fecha_hoy"]}, ruta=ruta_registro_causas
        )
```

Y agregá la función auxiliar, debajo de `correr()`:

```python
def _guardar_adjuntos_confiables(mensajes_hilos: list[dict], carpeta_destino: Path) -> list[dict]:
    """Guarda los adjuntos de `mensajes_hilos` que vengan de un remitente
    confiable, salvo `invite.ics` (ver subagentes/goteo.md, "Filtro de
    remitente confiable" y "Adjunto a excluir siempre"). `guardar_adjunto` ya
    hace de-dupe por nombre y por tamaño de bytes, así que no hace falta
    listar la carpeta antes. Devuelve la lista de adjuntos efectivamente
    guardados (con su `filename` original)."""
    guardados = []
    for mensaje in mensajes_hilos:
        if not es_remitente_confiable(mensaje.get("sender", "")):
            continue
        for adjunto in mensaje.get("adjuntos", []):
            nombre = adjunto["filename"]
            if nombre in NOMBRES_ADJUNTO_EXCLUIDOS:
                continue
            contenido = gmail_client.descargar_adjunto(mensaje["id"], adjunto["attachment_id"])
            if carpetas_mod.es_adjunto_firma(nombre, len(contenido)):
                continue
            resultado = carpetas_mod.guardar_adjunto(carpeta_destino, nombre, contenido)
            if resultado["guardado"]:
                guardados.append(adjunto)
    return guardados
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: PASS (todos los tests del archivo hasta este Task)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/goteo.py" "Actualizador de informes/tests/fases/test_goteo.py"
git commit -m "feat(gestion_causas): goteo guarda adjuntos de remitente confiable

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Detección de acuerdo/pago vía `reasoning.preguntar`

**Files:**
- Modify: `gestion_causas/fases/goteo.py`
- Test: `tests/fases/test_goteo.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_goteo.py`:

```python
class TestDeteccionDeAcuerdoYPago:
    def test_registra_estado_acuerdo_pendiente_pago_cuando_claude_confirma_cierre(self, tmp_path, monkeypatch):
        ruta_registro = _registrar_causa_activa(tmp_path, carpeta=str(tmp_path / "Perez con Alvi"))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl",
                    "subject": "Re: Acuerdo", "cuerpo_texto": "Se aprobó el acuerdo por $500.000", "adjuntos": [],
                }],
            },
        }), encoding="utf-8")

        llamadas = []

        def preguntar_falso(tarea, contexto, schema):
            llamadas.append(contexto)
            return {"acuerdo_cerrado": True, "pago_confirmado": False, "justificacion": "Acta de conciliación aprobada"}

        monkeypatch.setattr(goteo.reasoning, "preguntar", preguntar_falso)

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["estado_acuerdo"] == "pendiente_pago"
        assert len(llamadas) == 1
        assert resumen["acciones"] == [{
            "rit": "M-1-2026", "que": "Acuerdo alcanzado, pendiente de pago", "urgencia": "alta",
        }]

    def test_no_llama_a_claude_si_la_causa_no_tiene_hilos_nuevos(self, tmp_path, monkeypatch):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_hilos_vacio(tmp_path)

        llamadas = []
        monkeypatch.setattr(goteo.reasoning, "preguntar", lambda *a, **k: llamadas.append(1))

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        _correr_goteo(contexto, tmp_path)

        assert llamadas == []

    def test_anota_accion_si_reasoning_devuelve_error(self, tmp_path, monkeypatch):
        _registrar_causa_activa(tmp_path, carpeta=str(tmp_path / "Perez con Alvi"))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {"thread-1": [{
                "id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl",
                "subject": "Re: Acuerdo", "cuerpo_texto": "algo", "adjuntos": [],
            }]},
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.reasoning, "preguntar", lambda *a, **k: {"error": "Claude no devolvió JSON válido"})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert resumen["acciones"] == [{
            "rit": "M-1-2026",
            "que": "No se pudo evaluar acuerdo/pago automáticamente: Claude no devolvió JSON válido",
            "urgencia": "media",
        }]
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_goteo.py -k DeteccionDeAcuerdoYPago -v`
Expected: FAIL — el stub de `_detectar_acuerdo_y_pago` del Task 6 no llama a
`reasoning.preguntar` ni actualiza el registro.

- [ ] **Step 3: Implementá la detección**

En `gestion_causas/fases/goteo.py`, agregá el schema como constante de módulo (cerca de
`NOMBRES_ADJUNTO_EXCLUIDOS`):

```python
SCHEMA_ACUERDO = {
    "type": "object",
    "properties": {
        "acuerdo_cerrado": {"type": "boolean"},
        "pago_confirmado": {"type": "boolean"},
        "justificacion": {"type": "string"},
    },
    "required": ["acuerdo_cerrado", "pago_confirmado", "justificacion"],
}
```

Reemplazá el stub `_detectar_acuerdo_y_pago` del Task 6 por:

```python
def _detectar_acuerdo_y_pago(mensajes_hilos: list[dict]) -> dict:
    """Le pregunta a Claude si el hilo confirma que se ALCANZÓ Y APROBÓ un
    acuerdo (no alcanza con que el tribunal haya propuesto bases de
    conciliación — ver memoria gestion_causas_bases_tribunal_no_es_acuerdo) y
    si hay un comprobante de pago asociado."""
    contexto = {
        "mensajes": [
            {
                "remitente": m.get("sender", ""),
                "asunto": m.get("subject", ""),
                "cuerpo": m.get("cuerpo_texto", ""),
            }
            for m in mensajes_hilos
        ]
    }
    tarea = (
        "Estos son los mensajes de un hilo de correo sobre una causa laboral. "
        "Decidí si el hilo confirma que se ALCANZÓ Y APROBÓ un acuerdo "
        "(avenimiento/conciliación) entre las partes. Que el tribunal haya "
        "propuesto bases de conciliación en una audiencia NO cuenta como "
        "acuerdo alcanzado — hace falta confirmación de que las partes lo "
        "cerraron (ej. 'acta de conciliación', 'avenimiento aprobado', 'se "
        "aprobó el acuerdo por $X', 'conciliación total'). Además decidí si "
        "alguno de los mensajes trae un comprobante de pago o transferencia "
        "asociado a ese acuerdo."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_ACUERDO)
```

Y en el `for causa in causas:` de `correr()`, agregá la llamada justo antes del guardado
de adjuntos (después de calcular `mensajes_hilos`, antes de `tipo_audiencia = ...`):

```python
        if mensajes_hilos:
            causa_registrada = registro_mod.obtener_causa(rit, ruta=ruta_registro_causas) or {}
            estado_actual = causa_registrada.get("estado_acuerdo")
            if estado_actual not in ("pendiente_pago", "pago_recibido_pendiente_confirmar"):
                deteccion = _detectar_acuerdo_y_pago(mensajes_hilos)
                if deteccion.get("error"):
                    acciones.append({
                        "rit": rit,
                        "que": f"No se pudo evaluar acuerdo/pago automáticamente: {deteccion['error']}",
                        "urgencia": "media",
                    })
                elif deteccion.get("acuerdo_cerrado"):
                    registro_mod.registrar_causa(rit, {"estado_acuerdo": "pendiente_pago"}, ruta=ruta_registro_causas)
                    bitacora_mod.registrar("Acuerdo alcanzado, pendiente de pago", rit=rit)
                    acciones.append({"rit": rit, "que": "Acuerdo alcanzado, pendiente de pago", "urgencia": "alta"})
            elif estado_actual == "pendiente_pago":
                deteccion = _detectar_acuerdo_y_pago(mensajes_hilos)
                if deteccion.get("error"):
                    acciones.append({
                        "rit": rit,
                        "que": f"No se pudo evaluar acuerdo/pago automáticamente: {deteccion['error']}",
                        "urgencia": "media",
                    })
                elif deteccion.get("pago_confirmado"):
                    registro_mod.registrar_causa(
                        rit, {"estado_acuerdo": "pago_recibido_pendiente_confirmar"}, ruta=ruta_registro_causas
                    )
                    bitacora_mod.registrar(
                        "Comprobante de pago recibido, pendiente que Nico confirme el cierre", rit=rit
                    )
                    acciones.append({
                        "rit": rit, "que": "Pago recibido, pendiente confirmar cierre", "urgencia": "alta",
                    })
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: PASS (todos los tests del archivo hasta este Task)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/goteo.py" "Actualizador de informes/tests/fases/test_goteo.py"
git commit -m "feat(gestion_causas): goteo detecta acuerdo/pago via reasoning.preguntar

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**Nota:** el comprobante de pago de un dominio no confiable (caso "se detectó pero no se
descarga automáticamente" de `goteo.md` paso 3c2) queda **fuera de este piloto** — el
guardado de adjuntos del Task 6 ya solo guarda de dominios confiables, así que ese caso
borde (anotar en `notas` que se vio un comprobante pero no se descargó) se agrega en un
task de ajuste posterior si Nico lo pide después de comparar corridas reales.

---

### Task 8: Detección y registro de EERR

**Files:**
- Modify: `gestion_causas/fases/goteo.py`
- Test: `tests/fases/test_goteo.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_goteo.py`:

```python
class TestDeteccionDeEerr:
    def test_registra_eerr_cuando_el_nombre_del_adjunto_calza_y_hay_ceco_y_fecha_despido(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(
            tmp_path, carpeta=str(carpeta_causa), ceco="1234", fecha_despido="2026-01-15",
        )
        ruta_ceco = tmp_path / "registro_ceco.json"

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {"thread-1": [{
                "id": "msg-1", "thread_id": "thread-1", "sender": "nombre@sb.cl",
                "subject": "EERR", "cuerpo_texto": "",
                "adjuntos": [{"filename": "EERR 2026.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 900}],
            }]},
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido")
        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path, ruta_registro_ceco=ruta_ceco)

        reusable = registro_mod.buscar_eerr_reusable("1234", "2026-01-15", ruta=ruta_ceco)
        assert reusable == {"fecha_despido": "2026-01-15", "rit_causa": "M-1-2026"}
        assert any(m["etiqueta"] == "Identificados como EERR" and m["valor"] == 1 for m in resumen["metricas"])
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_goteo.py -k DeteccionDeEerr -v`
Expected: FAIL (`buscar_eerr_reusable` devuelve `None`, la métrica queda en 0)

- [ ] **Step 3: Implementá la detección de EERR**

En `gestion_causas/fases/goteo.py`, dentro del `for causa in causas:`, justo después del
bloque `if guardados:` del Task 6 (antes de `registro_mod.registrar_causa(rit,
{"goteo_ultima_revision": ...}, ...)`):

```python
        for adjunto_guardado in guardados:
            if not carpetas_mod.parece_eerr(adjunto_guardado["filename"]):
                continue
            ceco = causa.get("ceco")
            fecha_despido = causa.get("fecha_despido")
            if ceco and fecha_despido:
                registro_mod.registrar_eerr_recibido(ceco, fecha_despido, rit, ruta=ruta_registro_ceco)
                identificados_eerr += 1
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: PASS (todos los tests del archivo)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/goteo.py" "Actualizador de informes/tests/fases/test_goteo.py"
git commit -m "feat(gestion_causas): goteo detecta y registra EERR recibido

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: `gestion_causas/orquestador.py` — driver mínimo para la fase goteo

**Files:**
- Create: `gestion_causas/orquestador.py`
- Test: `tests/test_orquestador.py`

- [ ] **Step 1: Escribe el test que falla**

Creá `tests/test_orquestador.py`:

```python
import json

import pytest

from gestion_causas import orquestador


class TestCorrerOrquestador:
    def test_corre_goteo_y_devuelve_su_resumen(self, tmp_path):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(tmp_path / "no_existe.json")},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }), encoding="utf-8")

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["goteo"]["fase"] == "goteo"
        assert resultado["fases"]["goteo"]["titular"] == "Sin causas activas para revisar"

    def test_falla_de_una_fase_no_interrumpe_el_resultado(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-15"}), encoding="utf-8")

        def goteo_falla(contexto_corrida, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(orquestador.fases_goteo, "correr", goteo_falla)

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["goteo"]["fase"] == "goteo"
        assert "boom" in resultado["fases"]["goteo"]["error"]

    def test_falla_si_no_existe_el_contexto_de_corrida(self, tmp_path):
        ruta_contexto = tmp_path / "no_existe.json"

        with pytest.raises(FileNotFoundError):
            orquestador.correr(ruta_contexto=ruta_contexto)
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_orquestador.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.orquestador'`

- [ ] **Step 3: Implementá el driver**

Creá `gestion_causas/orquestador.py`:

```python
"""Driver mínimo del orquestador de gestion_causas, en Python.

Alcance de este archivo (ver plan
docs/superpowers/plans/2026-09-15-driver-python-goteo-piloto.md): solo
despacha la fase 'goteo'. Las demás fases (smu, agenda, seguimiento,
calendario) se agregan en planes posteriores, una vez validado este patrón.
No reemplaza todavía a la tarea programada `gestion-causas-orquestador` — se
corre a mano en paralelo para comparar resultados contra el subagente viejo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import registro as registro_mod
from gestion_causas.fases import goteo as fases_goteo

RUTA_CONTEXTO_DEFAULT = Path(__file__).parent / "_contexto_corrida.json"


def correr(
    ruta_contexto: Path = RUTA_CONTEXTO_DEFAULT,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    if not Path(ruta_contexto).exists():
        raise FileNotFoundError(
            f"No existe el contexto de corrida en {ruta_contexto}. "
            "Este driver requiere que ya se haya armado con "
            "`python -m gestion_causas.cli contexto-corrida` antes de correrlo."
        )
    contexto_corrida = json.loads(Path(ruta_contexto).read_text(encoding="utf-8"))

    fases = {}
    for nombre, funcion in (("goteo", fases_goteo.correr),):
        try:
            fases[nombre] = funcion(
                contexto_corrida,
                ruta_registro_causas=ruta_registro_causas,
                ruta_registro_ceco=ruta_registro_ceco,
            )
        except Exception as e:
            mensaje = f"{type(e).__name__}: {e}"
            bitacora_mod.registrar(f"Fase '{nombre}' falló: {mensaje}")
            fases[nombre] = {"fase": nombre, "error": mensaje}

    return {"fecha_hoy": contexto_corrida.get("fecha_hoy"), "fases": fases}


def main(argv=None) -> int:
    resultado = correr()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_orquestador.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/orquestador.py" "Actualizador de informes/tests/test_orquestador.py"
git commit -m "feat(gestion_causas): orquestador.py minimo, despacha la fase goteo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Correr la suite completa y verificar que nada se rompió

**Files:** ninguno (solo verificación)

- [ ] **Step 1: Corré toda la suite de tests del proyecto**

Run: `pytest -v`
Expected: PASS — todos los tests existentes (`test_registro.py`, `test_carpetas.py`,
`test_seguimiento.py`, `test_gmail_client.py`, `test_panel.py`, `test_cli.py`, etc.) más
los nuevos de este plan, sin ningún FAIL ni ERROR.

- [ ] **Step 2: Si algo falla, arreglalo antes de seguir**

No avances al Task 11 con tests rotos — si algo falla, es una regresión de este plan (por
ejemplo, un import circular entre `gestion_causas/fases/goteo.py` y `gestion_causas/cli.py`,
o un test que quedó escribiendo en una ruta de producción por no pasar `ruta_registro_causas`
explícito).

---

### Task 11: Verificación manual — correr en paralelo con el subagente `.md`

**Files:** ninguno (verificación manual, no se commitea código)

Este task es manual, para confirmar antes de dar por migrada la fase — es el mismo
criterio de "correr en paralelo antes de desactivar" del diseño original del
orquestador.

- [ ] **Step 1: Armá el contexto de corrida real**

Desde `Actualizador de informes`:
```bash
python -m gestion_causas.cli contexto-corrida --ruta-cache gestion_causas/cache_eventos_calendario.json --ruta-mapa-audiencias gestion_causas/_mapa_audiencias.json --ruta-mapa-hilos gestion_causas/_hilos_corrida.json --salida gestion_causas/_contexto_corrida.json --dias-adelante 200
```

- [ ] **Step 2: Corré el driver Python nuevo**

```bash
python -m gestion_causas.orquestador
```

Esto sí va a golpear Gmail real (descarga y guarda adjuntos, actualiza el registro) — no
es un dry-run. Avisale a Nico antes de correrlo la primera vez, para que sepa que va a
comparar resultados contra lo que hace hoy el subagente `goteo.md`.

- [ ] **Step 3: Compará el resumen contra lo que produce hoy el subagente `goteo.md`**

Pedile a Nico que revise: mismos documentos guardados, mismas causas con `estado_acuerdo`
actualizado, mismo contenido de `bitacora.md`. Cualquier diferencia se investiga y se
corrige con un task nuevo antes de considerar el piloto terminado — **no** se desactiva
`subagentes/goteo.md` todavía; esa decisión es de un plan posterior, una vez que varias
corridas paralelas coincidan.
