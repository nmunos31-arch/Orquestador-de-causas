# Driver Python para "smu" — ingesta y registro (Plan A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar la mitad "ingesta y registro" de la fase `smu` (Fase 1 del proyecto: detectar el origen de la cadena, extraer el cuadro-resumen, filtrar por empresa, evitar duplicados, crear la carpeta, guardar la demanda, escribir la fila del Excel de Juicios Vigentes, registrar la causa, etiquetar y marcar procesado) de `gestion_causas/subagentes/smu.md` a un driver Python (`gestion_causas/fases/smu.py`), con el mismo patrón que `goteo`: mecánica en Python puro, Claude solo en los 2 puntos que requieren juicio sobre texto libre.

**Architecture:** Dos módulos nuevos y angostos (`gestion_causas/empresas.py`, `gestion_causas/cuadro_resumen.py`) hacen la extracción/normalización determinística. `fases/smu.py` controla el bucle igual que `fases/goteo.py`, llamando a `reasoning.preguntar` solo para (1) decidir si una cadena `@gomezyriesco.cl` es en realidad un reenvío citado del cuadro-resumen, y (2) redactar el párrafo "Resumen" del Excel de Juicios Vigentes (texto libre, ver `docs/2026-07-07-informe-juicios-email-design.md`).

**Tech Stack:** Python 3, pytest, `openpyxl` (ya usado por `actualizar_informe_juicios.py`), librerías existentes del proyecto.

---

## Alcance de este plan (Plan A de 2)

Cubre desde la búsqueda de correos candidatos hasta que la causa queda registrada,
etiquetada y el hilo marcado procesado — el equivalente a los pasos 1 y 2a-2j, 2l-2n de
`smu.md`. **No** cubre el paso 2k ("borrador de documentos a solicitar", que necesita leer
el PDF de la demanda, reusar EERR y crear un borrador) — eso es el Plan B, un plan
separado, a implementar después de validar este.

**Fuera de alcance de este plan** (a propósito, YAGNI — se agregan en el Plan B o después):
- El campo `fecha_despido` del registro de la causa: solo se extrae leyendo la demanda
  (paso 2k del Plan B), no forma parte del cuadro-resumen del correo. Este plan **no** lo
  incluye en el `registrar_causa` inicial — el Plan B lo agrega en su propio
  `registrar_causa` cuando procese la demanda.
- El campo `campos_faltantes` que menciona la documentación de `registro.py` — no se usa
  en ningún paso de `smu.md`, se omite.
- El modo "corriendo suelto sin contexto de corrida" — igual que `goteo`, este driver
  asume que `orquestador.py` corrió antes (aunque en este plan la fase `smu` no necesita
  nada del contexto salvo `fecha_hoy`, a diferencia de `goteo`).
- Reintentos o manejo especial si `buscar-hilos` falla por red/cuota — se deja que la
  excepción suba y la aísle `orquestador.py` (mismo criterio que ya tiene para `goteo`).

## Puntos que se quedan con Claude (2, ver spec del proyecto)

1. **Origen de la cadena cuando el primer mensaje es de `@gomezyriesco.cl`** — decidir si
   es un reenvío/acuse de recibo que cita un cuadro-resumen de `@smu.cl`/`@sb.cl` (cadena
   válida) o una conversación interna (se descarta). Los dominios `@smu.cl`/`@sb.cl`
   directos no necesitan esto — se resuelven con una comparación de dominio simple.
2. **Redacción del párrafo "Resumen"** del Excel de Juicios Vigentes — combina
   Demandante + Hechos + Cuantía + Conceptos demandados con concordancia de género y una
   plantilla fija (ver "Plantilla del Resumen" en `docs/2026-07-07-informe-juicios-email-design.md`).
   Los demás campos del cuadro (Rit, Tribunal, Demandante, Rut, Fecha audiencia, Demandada,
   Cuantía, Materia, Fecha de ingreso al Pjud) son líneas `Etiqueta: valor` de una sola
   línea — se extraen con regex, sin Claude.

## Sobre las rutas de archivo en los tests

Mismo criterio que el plan de `goteo`: las funciones de `registro.py` reciben `ruta` como
parámetro explícito (nunca se monkeypatchea `RUTA_REGISTRO_CAUSAS`, no tendría efecto —
ver la nota completa en `docs/superpowers/plans/2026-09-15-driver-python-goteo-piloto.md`).
`fases/smu.py` sigue el mismo patrón: `correr(contexto_corrida, *, ruta_registro_causas=...)`.

---

### Task 1: `gestion_causas/empresas.py` — normalización de empresa

**Files:**
- Create: `gestion_causas/empresas.py`
- Test: `tests/test_empresas.py`

- [ ] **Step 1: Escribe el test que falla**

Creá `tests/test_empresas.py`:

```python
from gestion_causas.empresas import EMPRESAS_VALIDAS, normalizar_empresa


class TestNormalizarEmpresa:
    def test_coincide_exacto(self):
        assert normalizar_empresa("Alvi") == "Alvi"

    def test_ignora_mayusculas_y_sufijo_sa(self):
        assert normalizar_empresa("RENDIC HERMANOS S.A.") == "Rendic Hermanos"
        assert normalizar_empresa("salcobrand s.a") == "Salcobrand"

    def test_ignora_tildes(self):
        assert normalizar_empresa("Servicios Logisticos Santiago") == "Servicios Logísticos Santiago"

    def test_empresa_no_valida_devuelve_none(self):
        assert normalizar_empresa("Falabella") is None

    def test_vacio_devuelve_none(self):
        assert normalizar_empresa("") is None
        assert normalizar_empresa(None) is None

    def test_las_6_empresas_estan_en_la_lista(self):
        assert len(EMPRESAS_VALIDAS) == 6
        assert "Preunic" in EMPRESAS_VALIDAS
        assert "Salcobrand" in EMPRESAS_VALIDAS
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_empresas.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.empresas'`

- [ ] **Step 3: Implementá el módulo**

Creá `gestion_causas/empresas.py`:

```python
"""Normalización de nombre de empresa contra la lista cerrada de las 6
empresas del proyecto (ver subagentes/smu.md paso 2d). Independiente de
`carpetas._ABREVIATURA_EMPRESA` (esa tabla da la abreviatura de carpeta, no
valida si el nombre es una de las 6)."""

from __future__ import annotations

import unicodedata

EMPRESAS_VALIDAS = (
    "Rendic Hermanos",
    "Alvi",
    "Super 10",
    "Servicios Logísticos Santiago",
    "Preunic",
    "Salcobrand",
)


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sin_tildes.lower().replace("s.a.", "").replace("s.a", "").strip()


def normalizar_empresa(nombre: str | None) -> str | None:
    """Devuelve el nombre canónico (una de `EMPRESAS_VALIDAS`) si `nombre`
    coincide con alguna (sin importar mayúsculas, tildes, o el sufijo
    "S.A."/"S.A"), o None si no coincide con ninguna."""
    if not nombre:
        return None
    objetivo = _normalizar(nombre)
    for empresa in EMPRESAS_VALIDAS:
        if _normalizar(empresa) == objetivo:
            return empresa
    return None
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_empresas.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/empresas.py" "Actualizador de informes/tests/test_empresas.py"
git commit -m "feat(gestion_causas): agregar empresas.py, normalizacion de las 6 empresas del proyecto

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

(Commit ese trailer verbatim, sin importar qué modelo lo ejecute.)

---

### Task 2: `gestion_causas/cuadro_resumen.py` — extracción de campos por regex

**Files:**
- Create: `gestion_causas/cuadro_resumen.py`
- Test: `tests/test_cuadro_resumen.py`

- [ ] **Step 1: Escribe el test que falla**

Creá `tests/test_cuadro_resumen.py`:

```python
from gestion_causas.cuadro_resumen import CAMPOS_OBLIGATORIOS, cuadro_completo, extraer_campos_cuadro

CUERPO_EJEMPLO = """\
Estimado Nico:

Le remitimos el cuadro resumen de la nueva causa.

Rit: M-6-2026
Tribunal: Juzgado de Letras del Trabajo de Temuco
Demandante: LUIS ALFREDO SOTO SANDOVAL
Rut: 12.345.678-9
Fecha audiencia: 15 de octubre de 2026
Demandada: Rendic Hermanos S.A.
Cuantía: $1.414.468.-
Materia: Despido injustificado
Fecha de ingreso al Pjud: 01 de agosto de 2026
Conceptos demandados: Recargo legal del 30% (art. 168), Devolución de AFC

Hechos:
- Despido el 08 de enero de 2026 por necesidades de la empresa.
- El trabajador se desempeñaba como reponedor.

Saludos,
Equipo Legal SMU
"""


class TestExtraerCamposCuadro:
    def test_extrae_los_campos_de_una_linea(self):
        campos = extraer_campos_cuadro(CUERPO_EJEMPLO)
        assert campos["rit"] == "M-6-2026"
        assert campos["tribunal"] == "Juzgado de Letras del Trabajo de Temuco"
        assert campos["demandante"] == "LUIS ALFREDO SOTO SANDOVAL"
        assert campos["rut"] == "12.345.678-9"
        assert campos["fecha_audiencia"] == "15 de octubre de 2026"
        assert campos["demandada"] == "Rendic Hermanos S.A."
        assert campos["cuantia"] == "$1.414.468.-"
        assert campos["materia"] == "Despido injustificado"
        assert campos["fecha_ingreso_pjud"] == "01 de agosto de 2026"

    def test_no_confunde_texto_libre_con_un_campo(self):
        campos = extraer_campos_cuadro(CUERPO_EJEMPLO)
        assert "hechos" not in campos
        assert "saludos" not in campos

    def test_cuadro_sin_rit_no_esta_completo(self):
        cuerpo_incompleto = "Tribunal: Juzgado de Temuco\nCuantía: $100.000\n"
        campos = extraer_campos_cuadro(cuerpo_incompleto)
        assert not cuadro_completo(campos)

    def test_cuadro_con_los_3_obligatorios_esta_completo(self):
        campos = extraer_campos_cuadro(CUERPO_EJEMPLO)
        assert cuadro_completo(campos)
        assert CAMPOS_OBLIGATORIOS == ("rit", "tribunal", "cuantia")

    def test_campo_faltante_simplemente_no_aparece(self):
        cuerpo_sin_rut = CUERPO_EJEMPLO.replace("Rut: 12.345.678-9\n", "")
        campos = extraer_campos_cuadro(cuerpo_sin_rut)
        assert "rut" not in campos
        assert campos["rit"] == "M-6-2026"
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_cuadro_resumen.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Implementá el módulo**

Creá `gestion_causas/cuadro_resumen.py`:

```python
"""Extracción de los campos de una sola línea del cuadro-resumen que llega
en el correo de una demanda nueva (ver subagentes/smu.md paso 2c y
docs/2026-07-07-informe-juicios-email-design.md). Solo extrae los campos que
son "Etiqueta: valor" en una línea — "Hechos" y "Conceptos demandados" son
texto libre/multilínea y se dejan para que los procese Claude directamente
sobre el cuerpo completo (ver `fases/smu.py::_generar_resumen_narrativo`),
en vez de intentar acotarlos con regex."""

from __future__ import annotations

import re
import unicodedata

CAMPOS_OBLIGATORIOS = ("rit", "tribunal", "cuantia")

# Clave interna -> variantes de etiqueta aceptadas (ya sin tildes, minúsculas).
_ETIQUETAS = {
    "rit": ("rit",),
    "tribunal": ("tribunal",),
    "demandante": ("demandante",),
    "rut": ("rut",),
    "fecha_audiencia": ("fecha audiencia", "fecha de audiencia"),
    "demandada": ("demandada",),
    "cuantia": ("cuantia",),
    "materia": ("materia",),
    "fecha_ingreso_pjud": ("fecha de ingreso al pjud", "fecha ingreso pjud", "fecha ingreso al pjud"),
}

_LINEA_ETIQUETA_VALOR = re.compile(r"^\s*([^:\n]{2,40}?)\s*:\s*(.+?)\s*$")


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()


def extraer_campos_cuadro(cuerpo_texto: str) -> dict:
    """Recorre `cuerpo_texto` línea por línea buscando "Etiqueta: valor".
    Devuelve un dict solo con las claves que encontró (nunca claves con
    valor vacío) — un campo ausente simplemente no aparece."""
    campos: dict = {}
    for linea in cuerpo_texto.splitlines():
        coincidencia = _LINEA_ETIQUETA_VALOR.match(linea)
        if not coincidencia:
            continue
        etiqueta_cruda = _sin_tildes(coincidencia.group(1).strip())
        valor = coincidencia.group(2).strip()
        if not valor:
            continue
        for clave, variantes in _ETIQUETAS.items():
            if clave in campos:
                continue
            if etiqueta_cruda in variantes:
                campos[clave] = valor
                break
    return campos


def cuadro_completo(campos: dict) -> bool:
    """True si `campos` trae los 3 campos sin los que no vale la pena seguir
    (ver docs/2026-07-07-informe-juicios-email-design.md, "Manejo de
    errores")."""
    return all(campos.get(clave) for clave in CAMPOS_OBLIGATORIOS)
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_cuadro_resumen.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/cuadro_resumen.py" "Actualizador de informes/tests/test_cuadro_resumen.py"
git commit -m "feat(gestion_causas): agregar cuadro_resumen.py, extraccion regex del cuadro del correo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `gmail_client.leer_hilo()` — función reutilizable

**Files:**
- Modify: `gestion_causas/gmail_client.py`
- Test: `tests/test_gmail_client.py`

**Contexto:** hoy la lógica de "traer un hilo y aplanar sus mensajes a
`{id, thread_id, subject, sender, to, cc, date, cuerpo_texto, adjuntos}`" está duplicada
en `cli.py` (`cmd_leer_hilo` y `_mensajes_de_hilo`, casi idénticas). El driver de `smu`
necesita esta misma lógica sin pasar por el CLI — en vez de duplicarla una tercera vez, se
agrega como función pública reusable en `gmail_client.py`. `cli.py` no se toca (fuera de
alcance de este plan tocar el CLI viejo).

- [ ] **Step 1: Escribe el test que falla**

Buscá en `tests/test_gmail_client.py` cómo están mockeados `servicio`/`construir_servicio`
en los tests existentes (fijate en algún test de `obtener_hilo` o `leer_mensaje` como
referencia de estilo) y agregá, siguiendo el mismo patrón de mocking:

```python
from gestion_causas.gmail_client import leer_hilo


class TestLeerHilo:
    def test_aplana_los_mensajes_del_hilo(self):
        class ServicioFalso:
            def users(self):
                return self

            def threads(self):
                return self

            def get(self, userId, id, format=None):
                return self

            def execute(self):
                return {
                    "messages": [
                        {
                            "id": "msg-1",
                            "threadId": "thread-1",
                            "payload": {
                                "headers": [
                                    {"name": "Subject", "value": "DEMANDA M-1-2026"},
                                    {"name": "From", "value": "alguien@smu.cl"},
                                    {"name": "To", "value": "nmunoz@gomezyriesco.cl"},
                                ],
                                "mimeType": "text/plain",
                                "body": {"data": ""},
                            },
                        },
                    ]
                }

        mensajes = leer_hilo("thread-1", servicio=ServicioFalso())

        assert len(mensajes) == 1
        assert mensajes[0]["id"] == "msg-1"
        assert mensajes[0]["thread_id"] == "thread-1"
        assert mensajes[0]["subject"] == "DEMANDA M-1-2026"
        assert mensajes[0]["sender"] == "alguien@smu.cl"
        assert mensajes[0]["to"] == "nmunoz@gomezyriesco.cl"
        assert mensajes[0]["cc"] == ""
        assert mensajes[0]["adjuntos"] == []
```

Si al correr el test ves que el mock de `ServicioFalso` no calza con cómo `obtener_hilo`
arma la llamada real (revisá `gmail_client.obtener_hilo`, debería ser
`servicio.users().threads().get(userId="me", id=thread_id, format="full").execute()`),
ajustá el mock para que calce — el objetivo del test es verificar el aplanado, no
redescubrir la forma exacta de la API.

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_gmail_client.py -k LeerHilo -v`
Expected: FAIL con `ImportError`

- [ ] **Step 3: Implementá la función**

Agregá a `gestion_causas/gmail_client.py`, después de `obtener_hilo` (busca dónde está
definida esa función y agregala justo después):

```python
def leer_hilo(thread_id: str, servicio=None) -> list[dict]:
    """Trae todos los mensajes de un hilo, aplanados a
    {"id", "thread_id", "subject", "sender", "to", "cc", "date",
    "cuerpo_texto", "adjuntos"} — mismo formato que usa `cli.cmd_leer_hilo`.
    Reusado por los drivers Python de las fases (`fases/smu.py`, etc.) para
    no repetir esta lógica."""
    if servicio is None:
        servicio = construir_servicio()
    hilo = obtener_hilo(thread_id, servicio=servicio)
    mensajes = []
    for mensaje_crudo in hilo.get("messages", []):
        headers = {h["name"].lower(): h["value"] for h in mensaje_crudo["payload"].get("headers", [])}
        mensajes.append({
            "id": mensaje_crudo["id"],
            "thread_id": mensaje_crudo["threadId"],
            "subject": headers.get("subject", ""),
            "sender": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "cuerpo_texto": _extraer_texto_plano(mensaje_crudo["payload"]),
            "adjuntos": _listar_adjuntos(mensaje_crudo["payload"]),
        })
    return mensajes
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_gmail_client.py -k LeerHilo -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/gmail_client.py" "Actualizador de informes/tests/test_gmail_client.py"
git commit -m "feat(gestion_causas): agregar gmail_client.leer_hilo, reusable sin pasar por el CLI

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Esqueleto de `gestion_causas/fases/smu.py`

**Files:**
- Create: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

- [ ] **Step 1: Escribe el test que falla**

Creá `tests/fases/test_smu.py`:

```python
from gestion_causas.fases import smu


class TestCorrerSinHilosNuevos:
    def test_devuelve_resumen_sin_novedades(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        contexto = {"fecha_hoy": "2026-09-16"}

        resumen = smu.correr(contexto, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["fase"] == "smu"
        assert resumen["titular"] == "Sin correos nuevos"
        assert resumen["items"] == []
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.fases.smu'`

- [ ] **Step 3: Creá el esqueleto**

Creá `gestion_causas/fases/smu.py`:

```python
"""Driver Python de la fase 'smu' (Fase 1-2, ingesta y registro — ver spec
en docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md
y, como referencia histórica de las reglas completas, subagentes/smu.md).

Alcance de este módulo (ver plan
docs/superpowers/plans/2026-09-16-driver-python-smu-ingesta.md): busca
correos nuevos de demandas de las 6 empresas del proyecto, extrae el
cuadro-resumen, filtra duplicados, crea la carpeta, guarda la demanda,
escribe la fila del Excel de Juicios Vigentes, registra la causa, etiqueta
el hilo y lo marca procesado. NO arma el borrador de documentos a solicitar
(ver Plan B, un plan separado) — no requiere que orquestador.py haya armado
ningún mapa previo, a diferencia de goteo."""

from __future__ import annotations

from pathlib import Path

from actualizar_informe_juicios import RUTA_EXCEL_JUICIOS, agregar_causa
from gestion_causas import bitacora as bitacora_mod
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import registro as registro_mod
from gestion_causas import reasoning
from gestion_causas.cuadro_resumen import cuadro_completo, extraer_campos_cuadro
from gestion_causas.empresas import normalizar_empresa
from gestion_causas.gmail_client import COLOR_POR_EMPRESA, EMPRESAS_SIN_EXCEL, ETIQUETA_PROCESADO
from gestion_causas.seguimiento import extraer_direccion

QUERY_CANDIDATOS = (
    'from:(smu.cl OR sb.cl OR gomezyriesco.cl) subject:DEMANDA '
    'after:2026/07/01 -label:"Procesado-GestionCausas"'
)


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
) -> dict:
    hilos = gmail_client.buscar_hilos(QUERY_CANDIDATOS, max_resultados=50)
    if not hilos:
        return {
            "fase": "smu",
            "titular": "Sin correos nuevos",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    return {
        "fase": "smu",
        "titular": f"{len(hilos)} hilos candidatos",
        "metricas": [],
        "items": [],
        "acciones": [],
        "notas": [],
    }
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): esqueleto del driver Python de la fase smu

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**Nota para el implementador:** verificá que `from actualizar_informe_juicios import
RUTA_EXCEL_JUICIOS, agregar_causa` funcione con el `cwd` de test (`Actualizador de
informes`, donde ya corren `tests/test_actualizar_informe_juicios.py` con el mismo
import) — si pytest se corre desde otro directorio esto puede fallar; `tests/conftest.py`
ya agrega el root del proyecto a `sys.path`, así que debería resolver igual que en los
tests existentes de ese script.

---

### Task 5: Origen de la cadena (dominio directo + reasoning para `@gomezyriesco.cl`)

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`:

```python
import json

from gestion_causas import registro as registro_mod


def _hilo_falso(mensajes):
    """Arma el dict que devuelve gmail_client.leer_hilo (ya aplanado)."""
    return mensajes


class TestOrigenDeLaCadena:
    def test_dominio_smu_cl_es_valido_sin_llamar_a_claude(self, tmp_path, monkeypatch):
        llamadas_reasoning = []
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda *a, **k: llamadas_reasoning.append(1))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: _hilo_falso([
            {"id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
             "cuerpo_texto": "cuadro incompleto a proposito", "adjuntos": []},
        ]))

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas_reasoning == []

    def test_dominio_gomezyriesco_ambiguo_llama_a_claude(self, tmp_path, monkeypatch):
        llamadas = []

        def preguntar_falso(tarea, contexto, schema):
            llamadas.append(contexto)
            return {"es_reenvio_de_cuadro": False, "justificacion": "Nico iniciando una conversación"}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: _hilo_falso([
            {"id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl", "subject": "Re: causa",
             "cuerpo_texto": "Román, ¿cómo contestamos esta?", "adjuntos": []},
        ]))

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert len(llamadas) == 1
        assert llamadas[0]["remitente"] == "nmunoz@gomezyriesco.cl"

    def test_otro_dominio_no_llama_a_claude_ni_se_procesa(self, tmp_path, monkeypatch):
        llamadas = []
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda *a, **k: llamadas.append(1))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: _hilo_falso([
            {"id": "msg-1", "thread_id": "thread-1", "sender": "alguien@gmail.com", "subject": "DEMANDA",
             "cuerpo_texto": "no es de las empresas", "adjuntos": []},
        ]))

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas == []
        assert resumen["items"] == []
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k OrigenDeLaCadena -v`
Expected: FAIL — `correr()` todavía no recorre los hilos individualmente.

- [ ] **Step 3: Implementá la determinación de origen**

En `gestion_causas/fases/smu.py`, agregá el schema y la función de reasoning cerca del
final del archivo:

```python
SCHEMA_ORIGEN_CADENA = {
    "type": "object",
    "properties": {
        "es_reenvio_de_cuadro": {"type": "boolean"},
        "justificacion": {"type": "string"},
    },
    "required": ["es_reenvio_de_cuadro", "justificacion"],
}


def _evaluar_origen_gomezyriesco(primer_mensaje: dict) -> dict:
    """El primer mensaje del hilo es de @gomezyriesco.cl — decide si es un
    reenvío/acuse de recibo que cita (texto citado, ej. con '>') un
    cuadro-resumen firmado por alguien de @smu.cl/@sb.cl (cadena VÁLIDA), o
    si es Nico/Román iniciando una conversación interna (cadena NO válida,
    la usa la fase 'agenda', no esta)."""
    contexto = {
        "remitente": primer_mensaje.get("sender", ""),
        "asunto": primer_mensaje.get("subject", ""),
        "cuerpo": primer_mensaje.get("cuerpo_texto", ""),
    }
    tarea = (
        "El primer mensaje de este hilo de correo lo envió alguien de dominio "
        "@gomezyriesco.cl. Decidí si es un reenvío o acuse de recibo corto que cita, "
        "dentro del cuerpo (texto citado, típicamente con '>' o similar), un "
        "cuadro-resumen completo de una causa laboral (campos como Rit, Tribunal, "
        "Demandante, etc.) firmado originalmente por alguien de dominio @smu.cl o "
        "@sb.cl — en ese caso es una cadena VÁLIDA. Si en cambio es alguien de "
        "gomezyriesco.cl iniciando una conversación (ej. preguntando sobre estrategia "
        "de una causa ya conocida), sin ningún cuadro-resumen citado, es una cadena "
        "INTERNA, no válida para esta tarea."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_ORIGEN_CADENA)


def _dominio(remitente: str) -> str:
    direccion = extraer_direccion(remitente)
    return direccion.rsplit("@", 1)[1].lower() if "@" in direccion else ""


def _origen_cadena(primer_mensaje: dict) -> dict:
    """Devuelve {"valida": True|False, "error": <str, opcional>}."""
    dominio = _dominio(primer_mensaje.get("sender", ""))
    if dominio in ("smu.cl", "sb.cl"):
        return {"valida": True}
    if dominio == "gomezyriesco.cl":
        deteccion = _evaluar_origen_gomezyriesco(primer_mensaje)
        if deteccion.get("error"):
            return {"valida": False, "error": deteccion["error"]}
        return {"valida": bool(deteccion.get("es_reenvio_de_cuadro"))}
    return {"valida": False}
```

Reemplazá el cuerpo de `correr()` (a partir de `if not hilos:`) para que recorra los
hilos y llame a `_origen_cadena`:

```python
    if not hilos:
        return {
            "fase": "smu",
            "titular": "Sin correos nuevos",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = []
    causas_nuevas = 0

    for hilo_resumen in hilos:
        thread_id = hilo_resumen["id"]
        mensajes = gmail_client.leer_hilo(thread_id)
        if not mensajes:
            continue
        primer_mensaje = mensajes[0]

        origen = _origen_cadena(primer_mensaje)
        if origen.get("error"):
            acciones.append({
                "rit": None,
                "que": f"No se pudo evaluar el origen de un hilo automáticamente: {origen['error']}",
                "urgencia": "media",
            })
            continue
        if not origen["valida"]:
            continue

    resumen = {
        "fase": "smu",
        "titular": _armar_titular(causas_nuevas),
        "metricas": [
            {"etiqueta": "Causas nuevas", "valor": causas_nuevas},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _armar_titular(causas_nuevas: int) -> str:
    if causas_nuevas == 0:
        return "Sin causas nuevas"
    return f"{causas_nuevas} causas nuevas registradas"
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu determina el origen de la cadena por hilo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Extraer cuadro, filtrar por empresa, evitar duplicados

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`:

```python
CUERPO_CUADRO_ALVI = """\
Rit: M-1-2026
Tribunal: Juzgado de Letras del Trabajo de Temuco
Demandante: JUAN PEREZ
Demandada: Alvi
Cuantía: $500.000
Materia: Despido injustificado
"""


class TestFiltroDeEmpresaYDuplicados:
    def test_empresa_no_valida_no_genera_item(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI.replace("Alvi", "Falabella"), "adjuntos": [],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["items"] == []

    def test_cuadro_incompleto_no_genera_item_y_lo_anota(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": "Demandada: Alvi\n", "adjuntos": [],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["items"] == []
        assert any("cuadro" in n["detalle"].lower() for n in resumen["notas"])

    def test_rit_ya_registrado_no_genera_item_nuevo(self, tmp_path, monkeypatch):
        ruta_registro = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("M-1-2026", {"empresa": "Alvi"}, ruta=ruta_registro)

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert resumen["items"] == []
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k FiltroDeEmpresaYDuplicados -v`
Expected: FAIL — el bucle todavía no extrae el cuadro ni filtra.

- [ ] **Step 3: Implementá el filtro**

En `gestion_causas/fases/smu.py`, dentro del `for hilo_resumen in hilos:`, después de
`if not origen["valida"]: continue`, agregá:

```python
        campos = extraer_campos_cuadro(primer_mensaje.get("cuerpo_texto", ""))
        if not cuadro_completo(campos):
            notas.append({
                "tipo": "cuadro_incompleto",
                "detalle": f"Hilo {thread_id}: cuadro incompleto o mal formado (falta Rit, Tribunal o Cuantía) — revisar a mano.",
            })
            continue

        empresa = normalizar_empresa(campos.get("demandada", ""))
        if empresa is None:
            continue

        rit = campos["rit"]
        if registro_mod.causa_ya_registrada(rit, ruta=ruta_registro_causas):
            continue
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (todos los tests hasta este Task)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu extrae el cuadro y filtra por empresa/duplicado

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Crear carpeta y guardar la demanda

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`:

```python
class TestCrearCarpetaYGuardarDemanda:
    def test_crea_carpeta_y_guarda_el_pdf_de_la_demanda(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda_original.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert (carpeta_causa / "demanda.pdf").exists()
        assert resumen["metricas"] == [{"etiqueta": "Causas nuevas", "valor": 1}]
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k CrearCarpetaYGuardarDemanda -v`
Expected: FAIL — todavía no se crea carpeta ni se guarda nada.

- [ ] **Step 3: Implementá la creación de carpeta y el guardado de la demanda**

En `gestion_causas/fases/smu.py`, después de `if registro_mod.causa_ya_registrada(...):
continue` (dentro del mismo `for`), agregá:

```python
        # "Apellido del demandante principal" (ver subagentes/smu.md paso 2g) — se toma
        # el último token del nombre extraído, ej. "JUAN PEREZ" -> "Perez",
        # "LUIS ALFREDO SOTO SANDOVAL" -> "Sandoval". No es perfecto para nombres
        # compuestos, pero es el mismo criterio simple que ya usaba el subagente.
        apellido = campos.get("demandante", "").split()[-1].title() if campos.get("demandante") else rit

        carpeta_existente = carpetas_mod.buscar_carpeta_existente_por_rit(rit)
        carpeta = carpeta_existente or carpetas_mod.crear_carpeta_causa(apellido, empresa, rit)

        demanda_guardada = False
        for adjunto in primer_mensaje.get("adjuntos", []):
            if not adjunto["filename"].lower().endswith(".pdf"):
                continue
            contenido = gmail_client.descargar_adjunto(primer_mensaje["id"], adjunto["attachment_id"])
            if carpetas_mod.es_adjunto_firma(adjunto["filename"], len(contenido)):
                continue
            resultado = carpetas_mod.guardar_adjunto(carpeta, "demanda.pdf", contenido)
            demanda_guardada = resultado["guardado"] or demanda_guardada
            break

        if not demanda_guardada:
            notas.append({
                "tipo": "sin_demanda",
                "detalle": f"{rit}: no se encontró un PDF de demanda en el correo — súbela a mano.",
            })

        causas_nuevas += 1
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (todos los tests hasta este Task)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu crea la carpeta y guarda la demanda

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Resumen narrativo (Claude) + fila del Excel de Juicios Vigentes

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`:

```python
class TestResumenYExcel:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path, empresa="Alvi"):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        cuerpo = CUERPO_CUADRO_ALVI.replace("Alvi", empresa) if empresa != "Alvi" else CUERPO_CUADRO_ALVI
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": cuerpo, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        return carpeta_causa

    def test_llama_a_reasoning_para_el_resumen_y_escribe_la_fila_del_excel(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)

        llamadas_agregar_causa = []

        def agregar_causa_falso(ruta_excel, datos):
            llamadas_agregar_causa.append(datos)
            return {"agregada": True, "fila": 10}

        monkeypatch.setattr(smu, "agregar_causa", agregar_causa_falso)
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema: {"resumen": "Texto de prueba del resumen."})

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert len(llamadas_agregar_causa) == 1
        datos = llamadas_agregar_causa[0]
        assert datos["causa"] == "M-1-2026"
        assert datos["resumen"] == "Texto de prueba del resumen."
        assert datos["juzgado"] == "Juzgado de Letras del Trabajo de Temuco"

    def test_preunic_y_salcobrand_no_escriben_fila_de_excel(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path, empresa="Preunic")

        llamadas_agregar_causa = []
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: llamadas_agregar_causa.append(datos))
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema: {"resumen": "Texto de prueba."})

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas_agregar_causa == []
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k ResumenYExcel -v`
Expected: FAIL — todavía no se llama a `reasoning.preguntar` ni a `agregar_causa`.

- [ ] **Step 3: Implementá el resumen narrativo y la fila del Excel**

En `gestion_causas/fases/smu.py`, agregá el schema y la función de reasoning junto a las
otras constantes/funciones de reasoning (cerca de `SCHEMA_ORIGEN_CADENA`):

```python
SCHEMA_RESUMEN = {
    "type": "object",
    "properties": {"resumen": {"type": "string"}},
    "required": ["resumen"],
}


def _generar_resumen_narrativo(campos: dict, cuerpo_texto_completo: str) -> dict:
    """Redacta el párrafo "Resumen" del Excel de Juicios Vigentes siguiendo
    la plantilla exacta de docs/2026-07-07-informe-juicios-email-design.md
    (sección "Plantilla del Resumen"). `cuerpo_texto_completo` se pasa
    entero (no solo los campos ya extraídos) porque el bloque "Hechos" y
    "Conceptos demandados" son texto libre, sin acotar con regex."""
    contexto = {"campos_extraidos": campos, "cuerpo_completo_del_correo": cuerpo_texto_completo}
    tarea = (
        'Redactá el párrafo "Resumen" de una fila del Excel de Juicios Vigentes, '
        "siguiendo EXACTAMENTE esta plantilla (reemplazando lo que va entre corchetes, "
        "sin agregar ni quitar nada de la estructura):\n\n"
        '"Demanda de despido injustificado y cobro de prestaciones laborales interpuesta '
        "por [Demandante(s), formato Nombre Propio] por haber sido "
        "[desvinculad[o/a/os/as]] el [fecha de despido] por [causal]. Solicita el pago "
        "total de [Cuantía formateada como $#.###.###] por [conceptos demandados, sin "
        'montos parciales]."\n\n'
        "Reglas: Demandante(s) en formato Nombre Propio (no mayúsculas sostenidas), "
        "varios demandantes separados por comas y 'y' antes del último. Concordancia de "
        "género según el nombre (singular) o plural coherente con el grupo. Fecha y "
        "causal de despido se sacan del bloque 'Hechos' del cuerpo del correo. Formato de "
        "fecha: día con dos dígitos, mes en palabras y minúsculas, año completo (ej. '08 "
        "de enero de 2026'). Conceptos demandados: solo las etiquetas de los conceptos, "
        "sin repetir montos parciales."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_RESUMEN)
```

Reemplazá el final del cuerpo del `for hilo_resumen in hilos:` (a partir de `if not
demanda_guardada:`) para que incluya el resumen narrativo y la escritura del Excel:

```python
        if not demanda_guardada:
            notas.append({
                "tipo": "sin_demanda",
                "detalle": f"{rit}: no se encontró un PDF de demanda en el correo — súbela a mano.",
            })

        # El resumen narrativo solo hace falta para la fila del Excel — Preunic y
        # Salcobrand nunca tienen fila (ver EMPRESAS_SIN_EXCEL), así que ni siquiera
        # vale la pena gastar el llamado a Claude para esos dos casos.
        if empresa not in EMPRESAS_SIN_EXCEL:
            deteccion_resumen = _generar_resumen_narrativo(campos, primer_mensaje.get("cuerpo_texto", ""))
            if deteccion_resumen.get("error"):
                acciones.append({
                    "rit": rit,
                    "que": f"No se pudo redactar el Resumen del Excel automáticamente: {deteccion_resumen['error']}",
                    "urgencia": "media",
                })
            else:
                datos_excel = {
                    "juzgado": campos.get("tribunal", ""),
                    "materia": campos.get("materia", ""),
                    "causa": rit,
                    "cuantia": campos.get("cuantia", ""),
                    "resumen": deteccion_resumen.get("resumen", ""),
                }
                try:
                    agregar_causa(RUTA_EXCEL_JUICIOS, datos_excel)
                except PermissionError:
                    acciones.append({
                        "rit": rit,
                        "que": "El Excel de Juicios Vigentes está abierto/bloqueado — no se pudo escribir la fila. Se reintenta en la próxima corrida.",
                        "urgencia": "alta",
                    })

        causas_nuevas += 1
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (todos los tests hasta este Task)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu redacta el resumen narrativo y escribe la fila del Excel

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Registrar la causa, etiquetar y marcar procesado

**Files:**
- Modify: `gestion_causas/fases/smu.py`
- Test: `tests/fases/test_smu.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/fases/test_smu.py`:

```python
class TestRegistrarEtiquetarYMarcarProcesado:
    def test_registra_la_causa_etiqueta_y_marca_procesado(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema: {"resumen": "Texto de prueba."})

        etiquetas_aplicadas = []
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: f"label-{nombre}")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: etiquetas_aplicadas.append((thread_id, label_id)))

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])

        ruta_registro = tmp_path / "registro_causas.json"
        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["empresa"] == "Alvi"
        assert entrada["carpeta"] == str(carpeta_causa)
        assert entrada["thread_id"] == "thread-1"
        assert entrada["tiene_demanda"] is True
        assert entrada["aplica_excel"] is True

        assert ("thread-1", "label-Alvi") in etiquetas_aplicadas
        assert ("thread-1", f"label-{smu.ETIQUETA_PROCESADO}") in etiquetas_aplicadas

        assert resumen["items"] == [{"rit": "M-1-2026", "titulo": "Alvi - Juan Perez"}]
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/fases/test_smu.py -k RegistrarEtiquetarYMarcarProcesado -v`
Expected: FAIL — todavía no se registra/etiqueta/marca nada.

- [ ] **Step 3: Implementá el registro, etiquetado y marcado**

En `gestion_causas/fases/smu.py`, reemplazá el final del `for hilo_resumen in hilos:`
(desde `causas_nuevas += 1` hasta el final del bloque del `for`) por:

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
            },
            ruta=ruta_registro_causas,
        )

        color = COLOR_POR_EMPRESA.get(empresa)
        label_empresa = gmail_client.obtener_o_crear_etiqueta(empresa, color=color)
        gmail_client.aplicar_etiqueta_a_hilo(thread_id, label_empresa)
        label_procesado = gmail_client.obtener_o_crear_etiqueta(ETIQUETA_PROCESADO)
        gmail_client.aplicar_etiqueta_a_hilo(thread_id, label_procesado)

        bitacora_mod.registrar(
            f"Causa nueva registrada ({empresa}), carpeta '{carpeta.name}'"
            + ("" if demanda_guardada else " — sin demanda adjunta, súbela a mano"),
            rit=rit,
        )

        items.append({"rit": rit, "titulo": f"{empresa} - {campos.get('demandante', '').title()}"})
        causas_nuevas += 1
```

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/fases/test_smu.py -v`
Expected: PASS (todos los tests del archivo)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/fases/smu.py" "Actualizador de informes/tests/fases/test_smu.py"
git commit -m "feat(gestion_causas): smu registra, etiqueta y marca procesado el hilo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Wire en `orquestador.py`

**Files:**
- Modify: `gestion_causas/orquestador.py`
- Test: `tests/test_orquestador.py`

- [ ] **Step 1: Escribe el test que falla**

Agregá a `tests/test_orquestador.py`:

```python
class TestOrquestadorDespachaSmu:
    def test_corre_smu_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-16"}), encoding="utf-8")

        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["smu"]["fase"] == "smu"
        assert resultado["fases"]["smu"]["titular"] == "Sin correos nuevos"
```

- [ ] **Step 2: Corré el test y confirmá que falla**

Run: `pytest tests/test_orquestador.py -k DespachaSmu -v`
Expected: FAIL — `orquestador.fases_smu` no existe todavía.

- [ ] **Step 3: Wireá la fase**

En `gestion_causas/orquestador.py`, agregá el import junto al de `fases_goteo`:

```python
from gestion_causas.fases import smu as fases_smu
```

Y en `correr()`, cambiá la tupla de fases de:
```python
    for nombre, funcion in (("goteo", fases_goteo.correr),):
```
a:
```python
    for nombre, funcion in (("smu", fases_smu.correr), ("goteo", fases_goteo.correr)):
```

(orden `smu` antes que `goteo`, igual que en el diseño original — `goteo` revisa las
causas que `smu` acaba de registrar en la misma corrida). Notá que `fases_smu.correr` no
acepta `ruta_registro_ceco` — ajustá la llamada dentro del `try` para pasarle solo los
kwargs que cada función acepta:

```python
    fases = {}
    for nombre, funcion, kwargs_extra in (
        ("smu", fases_smu.correr, {}),
        ("goteo", fases_goteo.correr, {"ruta_registro_ceco": ruta_registro_ceco}),
    ):
        try:
            fases[nombre] = funcion(
                contexto_corrida,
                ruta_registro_causas=ruta_registro_causas,
                **kwargs_extra,
            )
        except Exception as e:
            mensaje = f"{type(e).__name__}: {e}"
            bitacora_mod.registrar(f"Fase '{nombre}' falló: {mensaje}")
            fases[nombre] = {"fase": nombre, "error": mensaje}
```

(reemplazá el `for nombre, funcion in (...)` completo, incluida la firma del loop, por
este de 3 elementos).

- [ ] **Step 4: Corré el test y confirmá que pasa**

Run: `pytest tests/test_orquestador.py -v`
Expected: PASS (todos los tests del archivo)

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/orquestador.py" "Actualizador de informes/tests/test_orquestador.py"
git commit -m "feat(gestion_causas): orquestador despacha tambien la fase smu

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: Suite completa y verificación manual

**Files:** ninguno

- [ ] **Step 1: Corré toda la suite**

Run: `pytest -q`
Expected: PASS — todos los tests existentes más los nuevos de este plan, sin FAIL ni
ERROR (aparte de cualquier falla preexistente ya conocida y no relacionada).

- [ ] **Step 2: Si algo falla, arreglalo antes de seguir**

- [ ] **Step 3: Verificación manual — correr en paralelo con el subagente `smu.md`**

Mismo criterio que se usó para `goteo`: armar el contexto de corrida
(`python -m gestion_causas.cli contexto-corrida ...`), correr
`python -m gestion_causas.orquestador`, y compararlo contra lo que produce hoy el
subagente `smu.md` en la próxima corrida real — **antes** de avisarle a Nico, confirmar
con él que quiere que se corra contra Gmail real (mismo aviso que la primera vez con
`goteo`, porque esta fase además escribe en el Excel de Juicios Vigentes). No se
desactiva `subagentes/smu.md` todavía.
