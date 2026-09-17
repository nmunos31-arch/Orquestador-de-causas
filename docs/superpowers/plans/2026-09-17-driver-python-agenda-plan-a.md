# Driver Python — fase `agenda` Plan A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar los pasos 1, 2, 3 y 5 de `gestion_causas/subagentes/agenda.md` (traer causas activas, resolver su audiencia, generar el borrador de ofrecimiento en el hito de 14 días corridos, y armar el resumen final) a un módulo Python puro `gestion_causas/fases/agenda.py`, siguiendo el mismo patrón ya validado en `fases/goteo.py` y `fases/smu.py`. El paso 4 (invocación de la skill `/minuta-laboral`) queda fuera de este plan — es Agenda Plan B.

**Architecture:** Una función `correr(contexto_corrida, *, ruta_registro_causas=...) -> dict` que itera las causas activas (reusando `registro_mod.causas_para_goteo`), resuelve la audiencia de cada una desde el mapa que el orquestador ya armó (extraído a un módulo compartido `gestion_causas/mapas.py` para que `goteo` y `agenda` nunca diverjan en el criterio), y en el hito de 14 días corridos antes de una audiencia Única o de Juicio genera un borrador de ofrecimiento: un único llamado a Claude lee la demanda (con `reasoning.preguntar(..., ruta_archivo=...)`, mismo patrón que `smu.py`) para extraer los montos de Recargo 30%/AFC por demandante y detectar discrepancias contra el cuadro original, y Python arma el cuerpo del correo con una plantilla fija (sin que Claude redacte el texto) y lo deja como borrador (respondiendo la cadena interna existente, o como correo nuevo de respaldo), con deduplicación.

**Tech Stack:** Python 3.14, pytest, `gestion_causas.reasoning` (wrapper de `claude -p`), `gestion_causas.gmail_client` (API de Gmail).

**Spec:** `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md` — ver también `gestion_causas/subagentes/agenda.md` (pasos 1, 2, 3, 5) y la memoria `gestion_causas_borrador_ofrecimiento_formato` (plantilla vigente, corregida el 18.08.2026 — **no** la plantilla literal desactualizada de `agenda.md` paso 3e).

## Global Constraints

- TDD estricto: cada función nueva tiene su test escrito y confirmado en rojo antes de implementarla.
- **Nunca tocar** `gestion_causas/cli.py`, `gestion_causas/panel.py`, `tests/test_cli.py`, `tests/test_panel.py`, `gestion_causas/subagentes/seguimiento.md` — pertenecen a otra sesión en curso en paralelo. Verificar `git status --short` antes de cada `git add` y agregar solo los archivos de la tarea.
- Cada commit termina con el trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`, sin importar qué modelo ejecutó el trabajo.
- Formato de moneda: pesos chilenos con punto como separador de miles (ej. `$1.234.567`), nunca coma.
- La plantilla del correo de ofrecimiento es literal — no se genera con Claude, ni se le agrega contexto de negociación, escenarios ni menciones a reuniones (memoria `gestion_causas_borrador_ofrecimiento_formato`).
- El driver nunca envía correos (solo deja borradores) ni toca el calendario — mismas restricciones que `goteo`/`smu`.
- Un demandante puede tener más de uno (causas RIT O-/T- con varios demandantes) — Claude resuelve el desglose por persona leyendo la demanda; no hay ningún campo estructurado de "demandantes" en el registro hoy.

---

## Task 1: Extraer `mapas.leer_mapa_audiencias` a un módulo compartido

**Files:**
- Create: `gestion_causas/mapas.py`
- Modify: `gestion_causas/fases/goteo.py` (elimina `_leer_mapa_audiencias`, usa el módulo nuevo)
- Test: `tests/test_mapas.py`

**Interfaces:**
- Produces: `mapas.leer_mapa_audiencias(contexto_corrida: dict) -> dict` — devuelve `{"rit_a_audiencia": {...}}`, `{"rit_a_audiencia": {}}` si el contexto no trae la ruta o el archivo no existe.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapas.py
import json

from gestion_causas import mapas


class TestLeerMapaAudiencias:
    def test_lee_el_mapa_desde_la_ruta_del_contexto(self, tmp_path):
        ruta = tmp_path / "mapa_audiencias.json"
        ruta.write_text(json.dumps({
            "rit_a_audiencia": {"M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"}},
        }), encoding="utf-8")

        contexto = {"mapa_audiencias": {"ruta": str(ruta)}}

        resultado = mapas.leer_mapa_audiencias(contexto)

        assert resultado["rit_a_audiencia"]["M-1-2026"]["tipo"] == "Única"

    def test_devuelve_mapa_vacio_si_no_hay_ruta_en_el_contexto(self):
        assert mapas.leer_mapa_audiencias({}) == {"rit_a_audiencia": {}}

    def test_devuelve_mapa_vacio_si_el_archivo_no_existe(self, tmp_path):
        contexto = {"mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")}}
        assert mapas.leer_mapa_audiencias(contexto) == {"rit_a_audiencia": {}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mapas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gestion_causas.mapas'`

- [ ] **Step 3: Write minimal implementation**

```python
# gestion_causas/mapas.py
"""Lectura de los mapas que el orquestador arma una sola vez por corrida
(ver orquestador.py) y que varias fases reusan, para que nunca diverjan en
cómo resuelven la misma pregunta — ej. `goteo` y `agenda` deciden el tipo de
audiencia (Única/Preparatoria/Juicio/Ambiguo) de un RIT con el mismo
criterio, leyendo el mismo archivo."""

from __future__ import annotations

import json
from pathlib import Path


def leer_mapa_audiencias(contexto_corrida: dict) -> dict:
    """Lee el mapa RIT -> audiencia ({"fecha", "resumen", "tipo"}) que el
    orquestador ya resolvió para toda la corrida (paso 0 de agenda.md / paso
    3a de goteo.md). Si el contexto no trae la ruta, o el archivo no existe
    (ej. corriendo la fase suelta sin orquestador), devuelve un mapa vacío
    en vez de fallar."""
    info = contexto_corrida.get("mapa_audiencias") or {}
    ruta = info.get("ruta")
    if not ruta or not Path(ruta).exists():
        return {"rit_a_audiencia": {}}
    return json.loads(Path(ruta).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mapas.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Update `goteo.py` to use the shared module and remove the duplicate**

In `gestion_causas/fases/goteo.py`:
- Add `from gestion_causas import mapas as mapas_mod` to the imports.
- Replace the call site `mapa_audiencias = _leer_mapa_audiencias(contexto_corrida)` with `mapa_audiencias = mapas_mod.leer_mapa_audiencias(contexto_corrida)`.
- Delete the `_leer_mapa_audiencias` function definition entirely (lines currently at the end of the file, right after `_leer_mapa_hilos`).

- [ ] **Step 6: Run the full goteo test suite to confirm nothing broke**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: PASS (all tests, same count as before — no test referenced `_leer_mapa_audiencias` directly)

- [ ] **Step 7: Commit**

```bash
git add gestion_causas/mapas.py gestion_causas/fases/goteo.py tests/test_mapas.py
git commit -m "$(cat <<'EOF'
refactor(gestion_causas): extrae leer_mapa_audiencias a un modulo compartido

goteo y la nueva fase agenda necesitan resolver el tipo de audiencia de un
RIT con exactamente el mismo criterio, leyendo el mismo mapa que el
orquestador ya armo para toda la corrida -- moverlo a mapas.py evita
duplicar la lectura entre las dos fases.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Esqueleto de `fases/agenda.py` (pasos 1, 2, 5) + wiring en `orquestador.py`

**Files:**
- Create: `gestion_causas/fases/agenda.py`
- Modify: `gestion_causas/orquestador.py`
- Test: `tests/fases/test_agenda.py`
- Test: `tests/test_orquestador.py`

**Interfaces:**
- Consumes: `registro_mod.causas_para_goteo(hoy, dias_ventana_post_audiencia, ruta) -> list[dict]` (ya existe, `gestion_causas/registro.py:186`); `mapas.leer_mapa_audiencias(contexto_corrida) -> dict` (Task 1).
- Produces: `agenda.correr(contexto_corrida, *, ruta_registro_causas=registro_mod.RUTA_REGISTRO_CAUSAS) -> dict` — resumen con la misma forma que `goteo.correr`/`smu.correr` (`fase`, `titular`, `metricas`, `items`, `acciones`, `notas`). En esta tarea el paso 3 (borrador de ofrecimiento) todavía no está implementado — las causas activas se recorren, se resuelve su audiencia, se cuentan las que no tienen evento todavía y se anotan las de tipo Ambiguo, pero no se genera ningún borrador (eso llega en Task 6).

- [ ] **Step 1: Write the failing tests**

```python
# tests/fases/test_agenda.py
import json

from gestion_causas import registro as registro_mod
from gestion_causas.fases import agenda


def _registrar_causa_activa(tmp_path, rit="M-1-2026", **extra):
    ruta_registro = tmp_path / "registro_causas.json"
    datos = {
        "empresa": "Alvi", "demandante": "Perez", "carpeta": str(tmp_path / "Perez con Alvi"),
        "thread_id": "thread-original-1", **extra,
    }
    registro_mod.registrar_causa(rit, datos, ruta=ruta_registro)
    return ruta_registro


def _mapa_audiencias(tmp_path, rit_a_audiencia):
    ruta = tmp_path / "mapa_audiencias.json"
    ruta.write_text(json.dumps({"rit_a_audiencia": rit_a_audiencia}), encoding="utf-8")
    return ruta


def _correr_agenda(contexto, tmp_path, **kwargs):
    kwargs.setdefault("ruta_registro_causas", tmp_path / "registro_causas.json")
    return agenda.correr(contexto, **kwargs)


class TestCorrerSinCausasActivas:
    def test_devuelve_resumen_sin_novedades(self, tmp_path):
        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")}}
        resumen = _correr_agenda(contexto, tmp_path)

        assert resumen == {
            "fase": "agenda",
            "titular": "Sin causas activas para revisar agenda",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }


class TestResolucionDeAudiencia:
    def test_causa_sin_evento_en_el_mapa_se_cuenta_como_sin_evento(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        metrica = next(m for m in resumen["metricas"] if m["etiqueta"] == "Sin evento de calendario todavía")
        assert metrica["valor"] == 1
        assert resumen["items"] == []
        assert resumen["acciones"] == []

    def test_causa_con_tipo_ambiguo_se_anota_en_notas_y_no_genera_nada(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Reunión rara", "tipo": "Ambiguo"},
        })

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        assert len(resumen["notas"]) == 1
        assert "M-1-2026" in resumen["notas"][0]["detalle"]
        assert resumen["items"] == []

    def test_metricas_incluyen_causas_revisadas_y_borradores_creados(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        etiquetas = [m["etiqueta"] for m in resumen["metricas"]]
        assert etiquetas == ["Causas revisadas", "Borradores de ofrecimiento creados", "Sin evento de calendario todavía"]
```

```python
# tests/test_orquestador.py — agregar al final del archivo
class TestOrquestadorDespachaAgenda:
    def test_corre_agenda_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-17"}), encoding="utf-8")

        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["agenda"]["fase"] == "agenda"
        assert resultado["fases"]["agenda"]["titular"] == "Sin causas activas para revisar agenda"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/fases/test_agenda.py tests/test_orquestador.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gestion_causas.fases.agenda'` (and `KeyError: 'agenda'` for the orquestador test once the module exists but isn't wired in)

- [ ] **Step 3: Write minimal implementation**

```python
# gestion_causas/fases/agenda.py
"""Driver Python de la fase 'agenda' — Plan A (ver plan de implementación
docs/superpowers/plans/2026-09-17-driver-python-agenda-plan-a.md): pasos 1,
2, 3 y 5 de subagentes/agenda.md. El paso 4 (invocación de la skill
/minuta-laboral) es Agenda Plan B, todavía no migrado.

Revisa las causas activas, resuelve su próxima audiencia desde el mapa que
el orquestador ya armó para toda la corrida, y en el hito de 14 días
corridos antes de una audiencia Única o de Juicio deja un borrador de
ofrecimiento a Román. Nunca envía correos (solo deja borradores) ni toca el
calendario."""

from __future__ import annotations

from pathlib import Path

from gestion_causas import mapas as mapas_mod
from gestion_causas import registro as registro_mod

TIPOS_CON_OFRECIMIENTO = {"Única", "Juicio"}


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
) -> dict:
    causas = registro_mod.causas_para_goteo(
        hoy=contexto_corrida["fecha_hoy"], dias_ventana_post_audiencia=0, ruta=ruta_registro_causas
    )
    if not causas:
        return {
            "fase": "agenda",
            "titular": "Sin causas activas para revisar agenda",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    mapa_audiencias = mapas_mod.leer_mapa_audiencias(contexto_corrida)

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = []
    ofrecimientos_creados = 0
    sin_evento = 0

    for causa in causas:
        rit = causa["rit"]
        audiencia = mapa_audiencias.get("rit_a_audiencia", {}).get(rit)
        if not audiencia:
            sin_evento += 1
            continue
        if audiencia.get("tipo") == "Ambiguo":
            notas.append({
                "tipo": "audiencia_ambigua",
                "detalle": (
                    f"{rit}: no se pudo determinar el tipo de audiencia "
                    f"({audiencia.get('resumen', '')}) — revisar a mano."
                ),
            })
            continue

        # Paso 3 (hito de 14 días — borrador de ofrecimiento) se agrega en
        # una tarea siguiente de este plan.

    resumen = {
        "fase": "agenda",
        "titular": _armar_titular(ofrecimientos_creados),
        "metricas": [
            {"etiqueta": "Causas revisadas", "valor": len(causas)},
            {"etiqueta": "Borradores de ofrecimiento creados", "valor": ofrecimientos_creados},
            {"etiqueta": "Sin evento de calendario todavía", "valor": sin_evento},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _armar_titular(ofrecimientos_creados: int) -> str:
    if ofrecimientos_creados == 0:
        return "Sin novedades"
    plural = "es" if ofrecimientos_creados != 1 else ""
    return f"{ofrecimientos_creados} borrador{plural} de ofrecimiento creado{plural}"
```

Modify `gestion_causas/orquestador.py`:
- Add `from gestion_causas.fases import agenda as fases_agenda` to the imports.
- Add `("agenda", fases_agenda.correr, {})` to the `fases` dispatch tuple in `correr()`, alongside the existing `"smu"` and `"goteo"` entries.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/fases/test_agenda.py tests/test_orquestador.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add gestion_causas/fases/agenda.py gestion_causas/orquestador.py tests/fases/test_agenda.py tests/test_orquestador.py
git commit -m "$(cat <<'EOF'
feat(gestion_causas): esqueleto de la fase agenda (pasos 1, 2 y 5) en Python

Trae las causas activas y resuelve su audiencia desde el mismo mapa que ya
usa goteo, contando las que no tienen evento todavia y anotando las de tipo
Ambiguo. El paso 3 (borrador de ofrecimiento) se agrega en tareas
siguientes de este plan; el paso 4 (/minuta-laboral) queda para Agenda
Plan B.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Hito de 14 días corridos — condición pura `_debe_generar_ofrecimiento`

**Files:**
- Modify: `gestion_causas/fases/agenda.py`
- Test: `tests/fases/test_agenda.py`

**Interfaces:**
- Consumes: `gestion_causas.agenda.dias_corridos_antes(fecha_objetivo, n) -> date` (ya existe, módulo top-level `gestion_causas/agenda.py:61` — **no confundir con el nuevo `gestion_causas/fases/agenda.py`**; importar como `from gestion_causas import agenda as dias_mod` dentro de `fases/agenda.py` para evitar la ambigüedad de nombres).
- Produces: `_debe_generar_ofrecimiento(causa: dict, audiencia: dict, fecha_hoy: str) -> bool` — usado por Task 6.

- [ ] **Step 1: Write the failing tests**

```python
# tests/fases/test_agenda.py — agregar al final del archivo
from gestion_causas.fases import agenda as agenda_fase


class TestDebeGenerarOfrecimiento:
    AUDIENCIA_UNICA = {"fecha": "2026-10-15", "resumen": "Audiencia única", "tipo": "Única"}
    AUDIENCIA_JUICIO = {"fecha": "2026-10-15", "resumen": "Audiencia de juicio", "tipo": "Juicio"}
    AUDIENCIA_PREPARATORIA = {"fecha": "2026-10-15", "resumen": "Audiencia preparatoria", "tipo": "Preparatoria"}

    def test_true_cuando_tipo_unica_y_hito_ya_paso(self):
        assert agenda_fase._debe_generar_ofrecimiento({}, self.AUDIENCIA_UNICA, "2026-10-02") is True

    def test_true_cuando_tipo_juicio_y_hoy_es_exactamente_el_hito(self):
        assert agenda_fase._debe_generar_ofrecimiento({}, self.AUDIENCIA_JUICIO, "2026-10-01") is True

    def test_false_cuando_tipo_preparatoria(self):
        assert agenda_fase._debe_generar_ofrecimiento({}, self.AUDIENCIA_PREPARATORIA, "2026-10-15") is False

    def test_false_cuando_todavia_no_llega_el_hito(self):
        assert agenda_fase._debe_generar_ofrecimiento({}, self.AUDIENCIA_UNICA, "2026-09-30") is False

    def test_false_cuando_causa_marca_aplica_ofrecimiento_false(self):
        causa = {"aplica_ofrecimiento": False}
        assert agenda_fase._debe_generar_ofrecimiento(causa, self.AUDIENCIA_UNICA, "2026-10-02") is False

    def test_false_cuando_ya_tiene_oferta_borrador_creado(self):
        causa = {"oferta_borrador_creado": True}
        assert agenda_fase._debe_generar_ofrecimiento(causa, self.AUDIENCIA_UNICA, "2026-10-02") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/fases/test_agenda.py -k DebeGenerarOfrecimiento -v`
Expected: FAIL — `AttributeError: module 'gestion_causas.fases.agenda' has no attribute '_debe_generar_ofrecimiento'`

- [ ] **Step 3: Write minimal implementation**

In `gestion_causas/fases/agenda.py`, add near the top:

```python
from datetime import date

from gestion_causas import agenda as dias_mod
```

Add the function (after `TIPOS_CON_OFRECIMIENTO`):

```python
def _debe_generar_ofrecimiento(causa: dict, audiencia: dict, fecha_hoy: str) -> bool:
    """True si corresponde generar hoy el borrador de ofrecimiento (paso 3
    de agenda.md): el tipo de audiencia es Única o Juicio, la causa no
    marcó `aplica_ofrecimiento: false` (causas que no son una demanda
    laboral estándar contra la empresa), no se generó ya
    (`oferta_borrador_creado`), y ya se cumplió — hoy o antes — el hito de
    14 días corridos antes de la audiencia."""
    if audiencia.get("tipo") not in TIPOS_CON_OFRECIMIENTO:
        return False
    if causa.get("aplica_ofrecimiento") is False:
        return False
    if causa.get("oferta_borrador_creado"):
        return False
    fecha_audiencia = audiencia.get("fecha")
    if not fecha_audiencia:
        return False
    hito = dias_mod.dias_corridos_antes(fecha_audiencia, 14)
    return date.fromisoformat(fecha_hoy) >= hito
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/fases/test_agenda.py -k DebeGenerarOfrecimiento -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add gestion_causas/fases/agenda.py tests/fases/test_agenda.py
git commit -m "$(cat <<'EOF'
feat(gestion_causas): condicion del hito de 14 dias para el ofrecimiento

Funcion pura que decide si toca generar el borrador de ofrecimiento hoy:
tipo de audiencia Unica/Juicio, la causa no opto por saltarselo, no se
genero ya, y el hito de 14 dias corridos antes de la audiencia ya se
cumplio.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Evaluación de montos con Claude (`_evaluar_montos_ofrecimiento`)

**Files:**
- Modify: `gestion_causas/fases/agenda.py`
- Test: `tests/fases/test_agenda.py`

**Interfaces:**
- Consumes: `reasoning.preguntar(tarea, contexto, schema, *, ruta_archivo=None) -> dict` (ya existe, `gestion_causas/reasoning.py`).
- Produces: `SCHEMA_OFRECIMIENTO` (dict), `_evaluar_montos_ofrecimiento(texto_cuadro_original: str, ruta_demanda: Path) -> dict` — devuelve `{"demandantes": [{"apellido", "monto_recargo_30", "monto_afc"}], "hay_discrepancia": bool, "detalle_discrepancia": str}`, o `{"error": "..."}` si `reasoning.preguntar` no pudo resolverlo (mismo contrato que el resto de las fases). Usado por Task 6.

- [ ] **Step 1: Write the failing test**

```python
# tests/fases/test_agenda.py — agregar al final del archivo
from pathlib import Path


class TestEvaluarMontosOfrecimiento:
    def test_pasa_ruta_archivo_y_texto_del_cuadro_a_reasoning(self, tmp_path, monkeypatch):
        ruta_demanda = tmp_path / "demanda.pdf"
        llamadas = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None):
            llamadas.append((tarea, contexto, schema, ruta_archivo))
            return {
                "demandantes": [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}],
                "hay_discrepancia": False,
                "detalle_discrepancia": "",
            }

        monkeypatch.setattr(agenda_fase.reasoning, "preguntar", preguntar_falso)

        resultado = agenda_fase._evaluar_montos_ofrecimiento("Conceptos demandados: Recargo 30%, AFC", ruta_demanda)

        assert resultado["demandantes"][0]["apellido"] == "Pérez"
        tarea, contexto, schema, ruta_archivo = llamadas[0]
        assert contexto == {"texto_cuadro_original": "Conceptos demandados: Recargo 30%, AFC"}
        assert schema == agenda_fase.SCHEMA_OFRECIMIENTO
        assert ruta_archivo == ruta_demanda

    def test_propaga_el_error_de_reasoning_sin_modificarlo(self, tmp_path, monkeypatch):
        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None):
            return {"error": "Claude no devolvió JSON válido"}

        monkeypatch.setattr(agenda_fase.reasoning, "preguntar", preguntar_falso)

        resultado = agenda_fase._evaluar_montos_ofrecimiento("texto", tmp_path / "demanda.pdf")

        assert resultado == {"error": "Claude no devolvió JSON válido"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fases/test_agenda.py -k EvaluarMontosOfrecimiento -v`
Expected: FAIL — `AttributeError: module 'gestion_causas.fases.agenda' has no attribute '_evaluar_montos_ofrecimiento'`

- [ ] **Step 3: Write minimal implementation**

In `gestion_causas/fases/agenda.py`, add near the top:

```python
from gestion_causas import reasoning
```

Add after `TIPOS_CON_OFRECIMIENTO`:

```python
SCHEMA_OFRECIMIENTO = {
    "type": "object",
    "properties": {
        "demandantes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "apellido": {"type": "string"},
                    "monto_recargo_30": {"type": "integer"},
                    "monto_afc": {"type": "integer"},
                },
                "required": ["apellido", "monto_recargo_30", "monto_afc"],
            },
        },
        "hay_discrepancia": {"type": "boolean"},
        "detalle_discrepancia": {"type": "string"},
    },
    "required": ["demandantes", "hay_discrepancia", "detalle_discrepancia"],
}


def _evaluar_montos_ofrecimiento(texto_cuadro_original: str, ruta_demanda: Path) -> dict:
    """Lee el PDF de la demanda (Claude la lee con su propia herramienta
    Read, en modo visión si es un escaneo sin capa de texto) para extraer,
    por cada demandante de la causa (puede ser uno o varios — no hay ningún
    campo estructurado con la lista de demandantes hoy), los montos exactos
    de Recargo legal 30% y Devolución de AFC. Coteja contra
    `texto_cuadro_original` (el cuerpo del correo con el cuadro resumen
    original, que trae "Conceptos demandados" como texto libre) y avisa si
    hay una discrepancia entre ambos, en vez de ocultarla — la demanda es
    la fuente legal (ver agenda.md paso 3c)."""
    contexto = {"texto_cuadro_original": texto_cuadro_original}
    tarea = (
        "Leé el archivo de la demanda indicado más abajo con tu herramienta Read (si es "
        "un PDF escaneado sin capa de texto, se lee en modo visión). Andá a la sección de "
        "Petitorio/Por tanto (normalmente al final) y extraé, por CADA demandante que "
        "aparezca en la causa: su apellido (tal como aparece en la identificación de las "
        "partes; si hay dos demandantes con el mismo apellido, agregá la inicial del "
        "nombre para distinguirlos), el monto exacto del Recargo legal 30% (recargo por "
        "término injustificado, art. 168 del Código del Trabajo), y el monto exacto de la "
        "Devolución de AFC (aporte al seguro de cesantía). Si la causa tiene un solo "
        "demandante, la lista trae un único elemento.\n\n"
        "Además, compará estos montos contra 'texto_cuadro_original' de más abajo (el "
        "cuerpo del correo con el cuadro resumen original de la demanda): si hay una "
        "diferencia entre lo que dice la demanda y lo que traía el cuadro, marcá "
        "hay_discrepancia=true y describila brevemente en detalle_discrepancia (si no hay "
        "diferencia — o el cuadro no menciona montos —, hay_discrepancia=false y "
        "detalle_discrepancia vacío)."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_OFRECIMIENTO, ruta_archivo=ruta_demanda)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/fases/test_agenda.py -k EvaluarMontosOfrecimiento -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add gestion_causas/fases/agenda.py tests/fases/test_agenda.py
git commit -m "$(cat <<'EOF'
feat(gestion_causas): agenda lee la demanda con Claude para el ofrecimiento

Mismo patron que smu (reasoning.preguntar con ruta_archivo): extrae por
demandante los montos exactos de Recargo 30% y AFC desde la demanda (la
fuente legal), y compara contra el cuadro resumen original para avisar
discrepancias en vez de ocultarlas.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Plantilla del correo de ofrecimiento (`_armar_cuerpo_ofrecimiento` / `_armar_asunto_ofrecimiento`)

**Files:**
- Modify: `gestion_causas/fases/agenda.py`
- Test: `tests/fases/test_agenda.py`

**Interfaces:**
- Produces: `_armar_cuerpo_ofrecimiento(demandantes: list[dict], tipo_audiencia: str, fecha_audiencia: str, dias_hasta_audiencia: int) -> str`; `_armar_asunto_ofrecimiento(causa: dict, rit: str) -> str`. Usados por Task 6.

**Nota de diseño (documentada, no preguntada de nuevo):** la plantilla vigente (memoria `gestion_causas_borrador_ofrecimiento_formato`) no incluye la hora de la audiencia de forma confiable — el mapa de audiencias solo trae `{"fecha", "resumen", "tipo"}`, sin un campo de hora estructurado — así que Plan A omite la hora del texto (la plantilla original de `agenda.md` ya marcaba la hora como opcional: "hora si se conoce"). El monto ofrecido es siempre 60% de (Recargo 30% + AFC) por persona, redondeado a un peso entero.

- [ ] **Step 1: Write the failing tests**

```python
# tests/fases/test_agenda.py — agregar al final del archivo
class TestArmarCuerpoOfrecimiento:
    def test_un_solo_demandante_audiencia_unica(self):
        demandantes = [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}]

        cuerpo = agenda_fase._armar_cuerpo_ofrecimiento(demandantes, "Única", "2026-10-15", 14)

        assert cuerpo == (
            "Estimado Román:\n\n"
            "En esta causa, con audiencia única fijada para el 15 de octubre de 2026 "
            "(en 14 días), se demanda lo siguiente:\n\n"
            "Pérez:\n"
            "Recargo 30%: $500.000\n"
            "Devolución AFC: $200.000\n"
            "Total: $700.000\n\n"
            "Por lo anterior, consulto si hago un ofrecimiento por $420.000 para don/doña "
            "Pérez, equivalente al 60% del total\n\n\n"
            "Atentamente,"
        )

    def test_dos_demandantes_audiencia_de_juicio(self):
        demandantes = [
            {"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000},
            {"apellido": "González", "monto_recargo_30": 300000, "monto_afc": 100000},
        ]

        cuerpo = agenda_fase._armar_cuerpo_ofrecimiento(demandantes, "Juicio", "2026-10-15", 14)

        assert cuerpo == (
            "Estimado Román:\n\n"
            "En esta causa, con audiencia de juicio fijada para el 15 de octubre de 2026 "
            "(en 14 días), se demanda lo siguiente:\n\n"
            "Pérez:\n"
            "Recargo 30%: $500.000\n"
            "Devolución AFC: $200.000\n"
            "Total: $700.000\n\n"
            "González:\n"
            "Recargo 30%: $300.000\n"
            "Devolución AFC: $100.000\n"
            "Total: $400.000\n\n"
            "Total demandado (todos): $1.100.000\n\n"
            "Por lo anterior, consulto si hago un ofrecimiento por $420.000 para don/doña "
            "Pérez y $240.000 para don/doña González, equivalente al 60% del total\n\n\n"
            "Atentamente,"
        )


class TestArmarAsuntoOfrecimiento:
    def test_arma_el_asunto_con_apellido_empresa_y_rit(self):
        causa = {"demandante": "Pérez", "empresa": "Alvi"}

        asunto = agenda_fase._armar_asunto_ofrecimiento(causa, "M-1-2026")

        assert asunto == 'Demanda laboral "Pérez con Alvi" Rit M-1-2026'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/fases/test_agenda.py -k "ArmarCuerpoOfrecimiento or ArmarAsuntoOfrecimiento" -v`
Expected: FAIL — `AttributeError: module 'gestion_causas.fases.agenda' has no attribute '_armar_cuerpo_ofrecimiento'`

- [ ] **Step 3: Write minimal implementation**

In `gestion_causas/fases/agenda.py`, add near the top:

```python
_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _formatear_pesos(monto: int) -> str:
    return f"${monto:,}".replace(",", ".")


def _formatear_fecha_larga(fecha_iso: str) -> str:
    fecha = date.fromisoformat(fecha_iso)
    return f"{fecha.day} de {_MESES_ES[fecha.month]} de {fecha.year}"


def _armar_cuerpo_ofrecimiento(
    demandantes: list[dict], tipo_audiencia: str, fecha_audiencia: str, dias_hasta_audiencia: int
) -> str:
    """Arma el cuerpo del borrador de ofrecimiento EXACTAMENTE con la
    plantilla vigente (memoria gestion_causas_borrador_ofrecimiento_formato,
    corregida el 18.08.2026 — no la plantilla desactualizada de
    agenda.md paso 3e): desglose de Recargo 30%/AFC/Total por cada
    demandante, sin agregar contexto de negociación ni escenarios
    alternativos. La pregunta final ofrece el 60% de (Recargo 30% + AFC)
    por persona, redondeado a un peso entero."""
    fecha_legible = _formatear_fecha_larga(fecha_audiencia)
    tipo_legible = "de juicio" if tipo_audiencia == "Juicio" else "única"

    bloques = []
    ofertas = []
    total_general = 0
    for demandante in demandantes:
        recargo = demandante["monto_recargo_30"]
        afc = demandante["monto_afc"]
        total_persona = recargo + afc
        total_general += total_persona
        apellido = demandante["apellido"]
        bloques.append(
            f"{apellido}:\n"
            f"Recargo 30%: {_formatear_pesos(recargo)}\n"
            f"Devolución AFC: {_formatear_pesos(afc)}\n"
            f"Total: {_formatear_pesos(total_persona)}"
        )
        ofertas.append((apellido, round(total_persona * 0.6)))

    cuerpo = (
        "Estimado Román:\n\n"
        f"En esta causa, con audiencia {tipo_legible} fijada para el {fecha_legible} "
        f"(en {dias_hasta_audiencia} días), se demanda lo siguiente:\n\n"
        + "\n\n".join(bloques) + "\n\n"
    )
    if len(demandantes) > 1:
        cuerpo += f"Total demandado (todos): {_formatear_pesos(total_general)}\n\n"

    if len(ofertas) == 1:
        apellido, oferta = ofertas[0]
        pregunta = (
            f"Por lo anterior, consulto si hago un ofrecimiento por {_formatear_pesos(oferta)} "
            f"para don/doña {apellido}, equivalente al 60% del total"
        )
    else:
        partes = [f"{_formatear_pesos(oferta)} para don/doña {apellido}" for apellido, oferta in ofertas]
        pregunta = (
            "Por lo anterior, consulto si hago un ofrecimiento por "
            + ", ".join(partes[:-1]) + " y " + partes[-1] + ", equivalente al 60% del total"
        )

    return cuerpo + pregunta + "\n\n\nAtentamente,"


def _armar_asunto_ofrecimiento(causa: dict, rit: str) -> str:
    apellido = causa.get("demandante", "")
    empresa = causa.get("empresa", "")
    return f'Demanda laboral "{apellido} con {empresa}" Rit {rit}'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/fases/test_agenda.py -k "ArmarCuerpoOfrecimiento or ArmarAsuntoOfrecimiento" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add gestion_causas/fases/agenda.py tests/fases/test_agenda.py
git commit -m "$(cat <<'EOF'
feat(gestion_causas): plantilla literal del correo de ofrecimiento

Sigue la plantilla vigente de la memoria gestion_causas_borrador_ofrecimiento_formato
(corregida el 18.08.2026), no el texto desactualizado de agenda.md: desglose
de Recargo 30%/AFC/Total por demandante, sin contexto de negociacion, con
soporte para mas de un demandante (causas RIT O-/T-).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Cadena interna, deduplicación y creación del borrador — wiring completo del paso 3

**Files:**
- Modify: `gestion_causas/fases/agenda.py`
- Test: `tests/fases/test_agenda.py`

**Interfaces:**
- Consumes: `gmail_client.buscar_hilos(query) -> list[dict]`, `gmail_client.leer_hilo(thread_id) -> list[dict]`, `gmail_client.listar_borradores_de_hilo(thread_id) -> list[dict]`, `gmail_client.buscar_borrador_por_asunto(fragmento) -> list[dict]`, `gmail_client.crear_borrador(destinatario, asunto, cuerpo, thread_id=None, html=False) -> dict` (todas ya existen en `gestion_causas/gmail_client.py`); `seguimiento.extraer_direccion(remitente) -> str` (ya existe, `gestion_causas/seguimiento.py:21`); `_debe_generar_ofrecimiento`, `_evaluar_montos_ofrecimiento`, `_armar_cuerpo_ofrecimiento`, `_armar_asunto_ofrecimiento` (Tasks 3-5).
- Produces: `_procesar_ofrecimiento(causa, audiencia, fecha_hoy, ruta_registro_causas, acciones) -> bool` — llamado desde `correr()`, reemplaza el comentario placeholder de Task 2.

- [ ] **Step 1: Write the failing tests**

```python
# tests/fases/test_agenda.py — agregar al final del archivo
class TestProcesarOfrecimientoIntegracion:
    """Prueba _procesar_ofrecimiento (y por lo tanto correr()) de punta a
    punta, mockeando solo gmail_client y reasoning.preguntar — nunca la red
    real."""

    def _causa_lista_para_ofrecimiento(self, tmp_path, **extra):
        carpeta = tmp_path / "Perez con Alvi"
        carpeta.mkdir()
        (carpeta / "demanda.pdf").write_bytes(b"%PDF-1.4 contenido falso")
        return _registrar_causa_activa(tmp_path, carpeta=str(carpeta), **extra)

    def _mock_evaluacion(self, monkeypatch, **overrides):
        resultado = {
            "demandantes": [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}],
            "hay_discrepancia": False,
            "detalle_discrepancia": "",
        }
        resultado.update(overrides)
        monkeypatch.setattr(agenda_fase.reasoning, "preguntar", lambda *a, **k: resultado)

    def test_responde_dentro_de_la_cadena_interna_si_existe(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)

        monkeypatch.setattr(
            agenda_fase.gmail_client, "buscar_hilos",
            lambda query, **k: [{"id": "thread-interno"}] if "gomezyriesco.cl" in query else [],
        )
        monkeypatch.setattr(
            agenda_fase.gmail_client, "leer_hilo",
            lambda thread_id, **k: [
                {"sender": "Cristina Gil <cgil@gomezyriesco.cl>", "cuerpo_texto": "Cuadro original", "subject": "Demanda laboral \"Perez con Alvi\" M-1-2026"},
                {"sender": "Nico Muñoz <nmunoz@gomezyriesco.cl>", "cuerpo_texto": "ok", "subject": "Re: ..."},
            ],
        )
        monkeypatch.setattr(agenda_fase.gmail_client, "listar_borradores_de_hilo", lambda thread_id, **k: [])

        llamadas_crear = []
        monkeypatch.setattr(
            agenda_fase.gmail_client, "crear_borrador",
            lambda destinatario, asunto, cuerpo, **k: llamadas_crear.append((destinatario, asunto, cuerpo, k)) or {"id": "draft-1"},
        )

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(llamadas_crear) == 1
        destinatario, asunto, cuerpo, kwargs = llamadas_crear[0]
        assert destinatario == "cgil@gomezyriesco.cl"
        assert kwargs["thread_id"] == "thread-interno"
        assert asunto.startswith("Re: ")

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["oferta_borrador_creado"] is True
        assert resumen["metricas"][1] == {"etiqueta": "Borradores de ofrecimiento creados", "valor": 1}
        assert resumen["items"] == [{"rit": "M-1-2026", "titulo": "Perez con Alvi", "detalle": "Borrador de ofrecimiento creado"}]

    def test_crea_correo_nuevo_si_no_encuentra_la_cadena_interna(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)

        monkeypatch.setattr(agenda_fase.gmail_client, "buscar_hilos", lambda query, **k: [])
        monkeypatch.setattr(agenda_fase.gmail_client, "buscar_borrador_por_asunto", lambda fragmento, **k: [])

        llamadas_crear = []
        monkeypatch.setattr(
            agenda_fase.gmail_client, "crear_borrador",
            lambda destinatario, asunto, cuerpo, **k: llamadas_crear.append((destinatario, asunto, cuerpo, k)) or {"id": "draft-2"},
        )

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(llamadas_crear) == 1
        destinatario, asunto, cuerpo, kwargs = llamadas_crear[0]
        assert destinatario == "rgomez@gomezyriesco.cl"
        assert kwargs.get("thread_id") is None
        assert asunto == 'Demanda laboral "Perez con Alvi" Rit M-1-2026'

    def test_no_duplica_si_ya_existe_un_borrador_en_la_cadena(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)

        monkeypatch.setattr(agenda_fase.gmail_client, "buscar_hilos", lambda query, **k: [{"id": "thread-interno"}])
        monkeypatch.setattr(
            agenda_fase.gmail_client, "leer_hilo",
            lambda thread_id, **k: [{"sender": "cgil@gomezyriesco.cl", "cuerpo_texto": "x", "subject": "x"}],
        )
        monkeypatch.setattr(agenda_fase.gmail_client, "listar_borradores_de_hilo", lambda thread_id, **k: [{"id": "draft-existente"}])

        llamadas_crear = []
        monkeypatch.setattr(agenda_fase.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert llamadas_crear == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["oferta_borrador_creado"] is True

    def test_anota_accion_si_no_hay_demanda_pdf_en_la_carpeta(self, tmp_path, monkeypatch):
        carpeta = tmp_path / "Perez con Alvi"
        carpeta.mkdir()
        ruta_registro = _registrar_causa_activa(tmp_path, carpeta=str(carpeta))
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(resumen["acciones"]) == 1
        assert "demanda.pdf" in resumen["acciones"][0]["que"]
        assert resumen["acciones"][0]["urgencia"] == "media"

    def test_anota_accion_de_urgencia_alta_si_hay_discrepancia(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch, hay_discrepancia=True, detalle_discrepancia="Demanda dice $500.000, cuadro decía $400.000")

        monkeypatch.setattr(agenda_fase.gmail_client, "buscar_hilos", lambda query, **k: [])
        monkeypatch.setattr(agenda_fase.gmail_client, "buscar_borrador_por_asunto", lambda fragmento, **k: [])
        monkeypatch.setattr(agenda_fase.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-3"})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        accion_discrepancia = next(a for a in resumen["acciones"] if "Discrepancia" in a["que"])
        assert accion_discrepancia["urgencia"] == "alta"
        assert "500.000" in accion_discrepancia["que"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/fases/test_agenda.py -k ProcesarOfrecimientoIntegracion -v`
Expected: FAIL — draft creation never happens because `correr()` doesn't call any paso-3 logic yet (assertions on `llamadas_crear`/`resumen["items"]` fail)

- [ ] **Step 3: Write minimal implementation**

In `gestion_causas/fases/agenda.py`, add near the top:

```python
from gestion_causas import bitacora as bitacora_mod
from gestion_causas import gmail_client
from gestion_causas.seguimiento import extraer_direccion

CUENTA_TRABAJO = "nmunoz@gomezyriesco.cl"
```

Add the following functions (after `_armar_asunto_ofrecimiento`):

```python
def _buscar_cadena_interna(rit: str) -> str | None:
    """Busca la cadena interna que Nico abre con Román al llegar la demanda
    (asunto 'Demanda laboral ... [RIT]', primer mensaje de
    @gomezyriesco.cl — la misma que gestion-causas-smu detecta como interna
    y deja sin tocar). Devuelve su thread_id, o None si todavía no existe
    (causa nueva, ver agenda.md paso 3g). Si la búsqueda acotada por asunto
    no encuentra nada, reintenta sin restringir el asunto (causas RIT
    T-/O-, cuyo primer mensaje no necesariamente sigue el patrón "Demanda
    laboral...")."""
    hilos = gmail_client.buscar_hilos(f'from:gomezyriesco.cl subject:"{rit}"')
    if not hilos:
        hilos = gmail_client.buscar_hilos(f"from:gomezyriesco.cl {rit}")
    for hilo in hilos:
        mensajes = gmail_client.leer_hilo(hilo["id"])
        if mensajes and extraer_direccion(mensajes[0].get("sender", "")).endswith("@gomezyriesco.cl"):
            return hilo["id"]
    return None


def _destinatarios_respuesta(thread_id: str) -> str:
    """Todos los participantes internos (@gomezyriesco.cl) de la cadena,
    salvo el propio Nico — el borrador de ofrecimiento debe ir a todos, no
    solo a Román (memoria gestion_causas_borrador_ofrecimiento_formato,
    corrección del 18.08.2026)."""
    mensajes = gmail_client.leer_hilo(thread_id)
    direcciones: list[str] = []
    for mensaje in mensajes:
        direccion = extraer_direccion(mensaje.get("sender", ""))
        if direccion.endswith("@gomezyriesco.cl") and direccion != CUENTA_TRABAJO and direccion not in direcciones:
            direcciones.append(direccion)
    return ", ".join(direcciones) if direcciones else "rgomez@gomezyriesco.cl"


def _crear_borrador_ofrecimiento(rit: str, cuerpo: str, asunto: str) -> str:
    """Crea el borrador de ofrecimiento: responde dentro de la cadena
    interna si ya existe, o crea un correo nuevo como respaldo si Nico
    todavía no la abrió (agenda.md paso 3g). Nunca duplica un borrador ya
    existente — devuelve su id en vez de crear uno nuevo."""
    cuerpo_html = cuerpo.replace("\n", "<br>\n")
    thread_id = _buscar_cadena_interna(rit)
    if thread_id:
        existentes = gmail_client.listar_borradores_de_hilo(thread_id)
        if existentes:
            return existentes[0]["id"]
        destinatarios = _destinatarios_respuesta(thread_id)
        borrador = gmail_client.crear_borrador(
            destinatarios, f"Re: {asunto}", cuerpo_html, thread_id=thread_id, html=True
        )
    else:
        existentes = gmail_client.buscar_borrador_por_asunto(asunto)
        if existentes:
            return existentes[0]["id"]
        borrador = gmail_client.crear_borrador("rgomez@gomezyriesco.cl", asunto, cuerpo_html, html=True)
    return borrador["id"]


def _procesar_ofrecimiento(
    causa: dict, audiencia: dict, fecha_hoy: str, ruta_registro_causas: Path, acciones: list[dict]
) -> bool:
    """Ejecuta el paso 3 completo para una causa (si corresponde): evalúa
    los montos con Claude, arma el correo con la plantilla fija, y lo deja
    como borrador. Devuelve True si se creó (o reusó) un borrador."""
    rit = causa["rit"]
    if not _debe_generar_ofrecimiento(causa, audiencia, fecha_hoy):
        return False

    carpeta = causa.get("carpeta")
    ruta_demanda = Path(carpeta) / "demanda.pdf" if carpeta else None
    if not ruta_demanda or not ruta_demanda.exists():
        acciones.append({
            "rit": rit,
            "que": (
                "Tocó el hito de 14 días para el ofrecimiento, pero no se encontró "
                "demanda.pdf en la carpeta de la causa — revisar a mano."
            ),
            "urgencia": "media",
        })
        return False

    texto_cuadro = ""
    thread_id_origen = causa.get("thread_id")
    if thread_id_origen:
        mensajes_origen = gmail_client.leer_hilo(thread_id_origen)
        if mensajes_origen:
            texto_cuadro = mensajes_origen[0].get("cuerpo_texto", "")

    evaluacion = _evaluar_montos_ofrecimiento(texto_cuadro, ruta_demanda)
    if evaluacion.get("error"):
        acciones.append({
            "rit": rit,
            "que": f"No se pudo calcular el ofrecimiento automáticamente: {evaluacion['error']}",
            "urgencia": "media",
        })
        return False

    if evaluacion.get("hay_discrepancia"):
        acciones.append({
            "rit": rit,
            "que": f"Discrepancia: {evaluacion.get('detalle_discrepancia', '')}",
            "urgencia": "alta",
        })

    fecha_audiencia = audiencia["fecha"]
    dias_hasta_audiencia = (date.fromisoformat(fecha_audiencia) - date.fromisoformat(fecha_hoy)).days
    cuerpo = _armar_cuerpo_ofrecimiento(
        evaluacion["demandantes"], audiencia["tipo"], fecha_audiencia, dias_hasta_audiencia
    )
    asunto = _armar_asunto_ofrecimiento(causa, rit)
    draft_id = _crear_borrador_ofrecimiento(rit, cuerpo, asunto)

    registro_mod.registrar_causa(rit, {"oferta_borrador_creado": True}, ruta=ruta_registro_causas)
    bitacora_mod.registrar(f"Borrador de ofrecimiento creado (draft {draft_id})", rit=rit)
    return True
```

Then, in `correr()`, replace the placeholder comment:

```python
        # Paso 3 (hito de 14 días — borrador de ofrecimiento) se agrega en
        # una tarea siguiente de este plan.
```

with:

```python
        if _procesar_ofrecimiento(causa, audiencia, contexto_corrida["fecha_hoy"], ruta_registro_causas, acciones):
            ofrecimientos_creados += 1
            items.append({
                "rit": rit,
                "titulo": f"{causa.get('demandante', '')} con {causa.get('empresa', '')}",
                "detalle": "Borrador de ofrecimiento creado",
            })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/fases/test_agenda.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add gestion_causas/fases/agenda.py tests/fases/test_agenda.py
git commit -m "$(cat <<'EOF'
feat(gestion_causas): agenda crea el borrador de ofrecimiento (paso 3 completo)

Busca la cadena interna existente (respondiendo a todos los participantes
@gomezyriesco.cl, no solo a Roman) o crea un correo nuevo de respaldo, con
deduplicacion en ambos casos. Completa el wiring del paso 3 en correr(),
dejado como placeholder en la Task 2 de este plan.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Revisión final, suite completa y nota de verificación manual

**Files:**
- Modify: none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass, no warnings

- [ ] **Step 2: Verify protected files were never touched**

Run: `git log --oneline --name-only docs/superpowers/plans/2026-09-17-driver-python-agenda-plan-a.md..HEAD 2>/dev/null; git diff --stat main -- gestion_causas/cli.py gestion_causas/panel.py tests/test_cli.py tests/test_panel.py gestion_causas/subagentes/seguimiento.md`

Expected: no changes from this plan's commits touch those files (they may still show as modified by the OTHER concurrent session — that's expected and not ours to touch).

- [ ] **Step 3: Leave a note for the manual verification step**

This plan does not include a live Gmail verification run — unlike `smu` Plan B, creating a real draft against the live inbox has a side effect a human should review before it's routine. Before relying on this in production, run `agenda.correr()` once against a real `_contexto_corrida.json` for a single already-audienced causa (same pattern used for `smu`/`goteo` live verification), and manually check the resulting draft's wording and recipients before trusting it unattended.

No commit for this task — it's verification only.
