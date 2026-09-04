# Cadencia de insistencia sin tope, atada a la fecha de audiencia — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el tope duro de `puede_insistir()` ("del 3er aviso en adelante, nunca") por una cadencia que se recalcula en cada llamada según cuánto falta para la `fecha_audiencia` de la causa asociada al hilo.

**Architecture:** Un solo cambio de lógica en una función pura ya existente (`gestion_causas/registro.py:puede_insistir`), sin componentes nuevos. Se agrega un parámetro `ruta_causas` inyectable (mismo patrón que `pedidos_abiertos`) para poder mirar `fecha_audiencia` de `registro_causas.json` a partir del `rit` que ya guarda cada entrada de `registro_seguimiento.json`. Se actualiza el texto de ayuda del CLI y del subagente que la invoca para que reflejen el nuevo comportamiento.

**Tech Stack:** Python 3, pytest, sin dependencias nuevas.

Spec de referencia: [docs/2026-09-04-cadencia-insistencia-por-audiencia-design.md](../../2026-09-04-cadencia-insistencia-por-audiencia-design.md)

---

## File Structure

- Modify: `gestion_causas/registro.py` — reemplazar el cuerpo de `puede_insistir` (líneas 325-366 actuales).
- Modify: `tests/test_registro.py` — actualizar `test_tercer_aviso_nunca_procede` (ya no aplica tal cual) y agregar los casos nuevos por tier, dentro de `class TestPuedeInsistir`.
- Modify: `gestion_causas/cli.py` — texto de `help=` del subparser `puede-insistir` (línea 1056).
- Modify: `gestion_causas/subagentes/seguimiento.md` — texto alrededor de la línea 166-170.

---

### Task 1: Actualizar los tests de `puede_insistir` para la nueva cadencia (deben fallar primero)

**Files:**
- Modify: `tests/test_registro.py`

- [ ] **Step 1: Reemplazar `test_tercer_aviso_nunca_procede`**

El test actual asume que el 3er aviso nunca procede sin importar nada. Con la nueva
lógica, sin `rit` en la entrada (como registra este test, sin pasar `rit=`) la causa no
se puede ubicar, así que el motivo cambia. Reemplazar el método completo (líneas 262-271
de `tests/test_registro.py`) por:

```python
    def test_tercer_aviso_sin_rit_reporta_causa_no_agendada(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)

        resultado = puede_insistir("t1", hoy=date(2026, 9, 1), ruta=ruta, ruta_feriados=ruta_feriados)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 3
        assert "no tiene audiencia agendada" in resultado["motivo"]
```

- [ ] **Step 2: Agregar test de rit con causa sin `fecha_audiencia`**

Agregar a continuación, dentro de `class TestPuedeInsistir`:

```python
    def test_tercer_aviso_con_rit_pero_sin_fecha_audiencia_reporta_causa_no_agendada(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_causa("O-1-2026", {}, ruta=ruta_causas)
        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)

        resultado = puede_insistir(
            "t1", hoy=date(2026, 9, 1), ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas
        )
        assert resultado["puede"] is False
        assert "no tiene audiencia agendada" in resultado["motivo"]
```

- [ ] **Step 3: Agregar test del ciclo 4/2 en bucle (tier lejano)**

```python
    def test_tier_lejano_repite_ciclo_4_y_2_dias_habiles_en_bucle(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_causa("O-1-2026", {"fecha_audiencia": "2026-12-01"}, ruta=ruta_causas)
        kwargs = dict(ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas)

        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)  # miércoles
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)  # viernes, 1er->2do: 2 hábiles

        # 3er aviso exige 4 dias habiles desde el 2do (2026-08-21 -> 2026-08-27)
        resultado = puede_insistir("t1", hoy=date(2026, 8, 26), **kwargs)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 3
        resultado = puede_insistir("t1", hoy=date(2026, 8, 27), **kwargs)
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 3
        registrar_aviso("t1", "documentos", "2026-08-27", ruta=ruta)

        # 4to aviso exige 2 dias habiles desde el 3ro (2026-08-27 -> 2026-08-31)
        resultado = puede_insistir("t1", hoy=date(2026, 8, 28), **kwargs)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 4
        resultado = puede_insistir("t1", hoy=date(2026, 8, 31), **kwargs)
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 4
        registrar_aviso("t1", "documentos", "2026-08-31", ruta=ruta)

        # 5to aviso vuelve a exigir 4 dias habiles (confirma el bucle, no solo 2 pasos)
        resultado = puede_insistir("t1", hoy=date(2026, 9, 3), **kwargs)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 5
        resultado = puede_insistir("t1", hoy=date(2026, 9, 4), **kwargs)
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 5
```

- [ ] **Step 4: Agregar test del tier medio (cada 2 días hábiles)**

```python
    def test_tier_medio_exige_2_dias_habiles_entre_avisos(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        # A 10 y 9 dias corridos de las fechas "hoy" usadas abajo: tier medio (8-14 dias)
        registrar_causa("O-1-2026", {"fecha_audiencia": "2026-09-03"}, ruta=ruta_causas)
        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)  # viernes
        kwargs = dict(ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas)

        # 3er aviso: solo 1 dia habil desde el 2do (2026-08-21 -> 2026-08-24, lunes);
        # faltan 10 dias corridos para la audiencia (tier medio, exige 2): no alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 24), **kwargs)
        assert resultado["puede"] is False
        assert "tier medio" in resultado["motivo"]

        # 2 dias habiles (2026-08-21 -> 2026-08-25, martes); faltan 9 dias corridos
        # (tier medio sigue): si alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 25), **kwargs)
        assert resultado["puede"] is True
        assert "tier medio" in resultado["motivo"]
```

- [ ] **Step 5: Agregar test del tier cercano (a diario)**

```python
    def test_tier_cercano_exige_1_dia_habil_entre_avisos(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        # 2026-08-21 (viernes) + 5 dias corridos = 2026-08-26: tier cercano (<=7 dias)
        registrar_causa("O-1-2026", {"fecha_audiencia": "2026-08-26"}, ruta=ruta_causas)
        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)  # viernes
        kwargs = dict(ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas)

        # mismo dia habil que el 2do aviso: no alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 21), **kwargs)
        assert resultado["puede"] is False
        assert "tier cercano" in resultado["motivo"]

        # 1 dia habil despues (lunes 2026-08-24): alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 24), **kwargs)
        assert resultado["puede"] is True
        assert "tier cercano" in resultado["motivo"]
```

- [ ] **Step 6: Agregar `registrar_causa` a los imports del test**

`tests/test_registro.py` ya importa `registrar_causa` (línea 21 del archivo actual, dentro
del bloque `from gestion_causas.registro import (...)`) — confirmar que sigue ahí; no hace
falta agregar nada si ya está.

- [ ] **Step 7: Correr los tests nuevos y confirmar que fallan**

Run: `python -m pytest tests/test_registro.py -k TestPuedeInsistir -v`

Expected: FAIL en los tests nuevos (los que esperan "no tiene audiencia agendada", "tier
lejano/medio/cercano" en el motivo) porque `puede_insistir` todavía no acepta
`ruta_causas` ni calcula tiers — error tipo `TypeError: puede_insistir() got an unexpected
keyword argument 'ruta_causas'`. El test reemplazado (`test_tercer_aviso_sin_rit_...`)
también debe fallar porque hoy el motivo dice "gestion manual", no "no tiene audiencia
agendada".

- [ ] **Step 8: Commit**

```bash
git add tests/test_registro.py
git commit -m "test(gestion_causas): cubrir cadencia de insistencia por tier de audiencia"
```

---

### Task 2: Implementar la nueva cadencia en `puede_insistir`

**Files:**
- Modify: `gestion_causas/registro.py:325-366`

- [ ] **Step 1: Reemplazar el cuerpo de `puede_insistir`**

Reemplazar la función completa (líneas 325-366 actuales) por:

```python
def puede_insistir(
    thread_id: str,
    hoy=None,
    ruta: Path = RUTA_REGISTRO_SEGUIMIENTO,
    ruta_feriados=None,
    ruta_causas: Path = RUTA_REGISTRO_CAUSAS,
) -> dict:
    """Aplica la cadencia acordada con el usuario: el 1er aviso siempre
    procede; el 2do solo si pasaron al menos 2 dias habiles desde el 1ro.

    Del 3er aviso en adelante ya no hay tope: la cadencia se recalcula en
    cada llamada segun cuanto falta (en dias corridos) para la
    `fecha_audiencia` de la causa asociada (via el `rit` guardado en la
    entrada de seguimiento):
    - Sin `rit`, o el `rit` no tiene `fecha_audiencia` registrada en
      `registro_causas.json`: no hay como elegir cadencia, se reporta motivo
      distinto ("causa no tiene audiencia agendada") para no confundirlo con
      un simple "todavia no toca".
    - Faltan mas de 14 dias corridos: tier "lejano" — repite en bucle 4 dias
      habiles / 2 dias habiles desde el aviso anterior (3er aviso exige 4,
      4to exige 2, 5to vuelve a exigir 4, etc.).
    - Faltan entre 8 y 14 dias corridos: tier "medio" — exige 2 dias habiles
      desde el aviso anterior.
    - Faltan 7 dias corridos o menos (incluida audiencia ya pasada): tier
      "cercano" — exige 1 dia habil desde el aviso anterior.

    Devuelve {"puede": bool, "n_aviso": int, "motivo": str}, donde
    `n_aviso` es el numero de aviso que correspondaria crear a continuacion.
    """
    from . import agenda as agenda_mod

    if hoy is None:
        hoy = date.today()
    else:
        hoy = _parsear_fecha(hoy)

    entrada = obtener_seguimiento(thread_id, ruta)
    avisos = entrada["avisos"] if entrada else []
    kwargs_feriados = {} if ruta_feriados is None else {"ruta_feriados": ruta_feriados}

    if len(avisos) == 0:
        return {"puede": True, "n_aviso": 1, "motivo": "sin avisos previos"}

    if len(avisos) == 1:
        transcurridos = agenda_mod.dias_habiles_entre(avisos[0]["fecha"], hoy, **kwargs_feriados)
        if transcurridos >= 2:
            return {"puede": True, "n_aviso": 2, "motivo": f"pasaron {transcurridos} dias habiles desde el 1er aviso"}
        return {
            "puede": False, "n_aviso": 2,
            "motivo": f"solo pasaron {transcurridos} dias habiles desde el 1er aviso (se requieren 2)",
        }

    n_aviso = len(avisos) + 1
    rit = entrada.get("rit") if entrada else None
    causa = obtener_causa(rit, ruta_causas) if rit else None
    fecha_audiencia = causa.get("fecha_audiencia") if causa else None
    if not fecha_audiencia:
        return {
            "puede": False, "n_aviso": n_aviso,
            "motivo": "causa no tiene audiencia agendada, requiere revision manual",
        }

    dias_hasta_audiencia = (_parsear_fecha(fecha_audiencia) - hoy).days
    if dias_hasta_audiencia > 14:
        tier = "lejano"
        posicion = (len(avisos) - 2) % 2
        umbral = 4 if posicion == 0 else 2
    elif dias_hasta_audiencia >= 8:
        tier = "medio"
        umbral = 2
    else:
        tier = "cercano"
        umbral = 1

    transcurridos = agenda_mod.dias_habiles_entre(avisos[-1]["fecha"], hoy, **kwargs_feriados)
    if transcurridos >= umbral:
        return {
            "puede": True, "n_aviso": n_aviso,
            "motivo": f"pasaron {transcurridos} dias habiles desde el ultimo aviso (tier {tier}, exige {umbral})",
        }
    return {
        "puede": False, "n_aviso": n_aviso,
        "motivo": f"solo pasaron {transcurridos} dias habiles desde el ultimo aviso (tier {tier}, se requieren {umbral})",
    }
```

Nota: `obtener_causa` ya está definida más arriba en el mismo módulo (línea 141) — no
hace falta importarla.

- [ ] **Step 2: Correr los tests de `puede_insistir` y confirmar que pasan**

Run: `python -m pytest tests/test_registro.py -k TestPuedeInsistir -v`

Expected: PASS en los 8 tests de `TestPuedeInsistir` (los 3 originales sin cambios más los
5 nuevos/reemplazados del Task 1).

- [ ] **Step 3: Correr toda la suite de tests del paquete**

Run: `python -m pytest tests/ -q`

Expected: PASS sin regresiones (en particular `tests/test_cli.py` y
`tests/test_seguimiento.py`, que no deberían verse afectados).

- [ ] **Step 4: Commit**

```bash
git add gestion_causas/registro.py
git commit -m "feat(gestion_causas): cadencia de insistencia sin tope, atada a la fecha de audiencia"
```

---

### Task 3: Actualizar el texto de ayuda del CLI

**Files:**
- Modify: `gestion_causas/cli.py:1056`

- [ ] **Step 1: Reemplazar el `help=` del subparser `puede-insistir`**

Reemplazar la línea:

```python
    p = sub.add_parser("puede-insistir", help="Fase 5/6: aplica la cadencia de insistencia (1er aviso siempre, 2do a los 2 dias habiles, despues nunca)")
```

por:

```python
    p = sub.add_parser("puede-insistir", help="Fase 5/6: aplica la cadencia de insistencia (1er aviso siempre, 2do a los 2 dias habiles; del 3ro en adelante segun cercania a la audiencia: ciclo 4/2 dias habiles si faltan +2 semanas, cada 2 dias si faltan -2 semanas, a diario si falta -1 semana)")
```

- [ ] **Step 2: Confirmar que el CLI sigue arrancando**

Run: `python -m gestion_causas.cli puede-insistir --help`

Expected: se imprime el nuevo texto de ayuda sin errores.

- [ ] **Step 3: Commit**

```bash
git add gestion_causas/cli.py
git commit -m "docs(gestion_causas): actualizar ayuda de puede-insistir con la nueva cadencia"
```

---

### Task 4: Actualizar el subagente `seguimiento.md`

**Files:**
- Modify: `gestion_causas/subagentes/seguimiento.md:166-171`

- [ ] **Step 1: Reemplazar el bloque de interpretación del resultado de `puede-insistir`**

Reemplazar las líneas actuales:

```
   - `puede` false por 2 avisos agotados → no crear borrador; el pedido pasa a
     `gestion_manual` (paso 3f) y se destaca en el resumen final (punto 5) — es lo más
     importante de todo el resumen.
   - `puede` false por no cumplirse aún los 2 días hábiles desde el 1er aviso → saltar
     este pedido en esta corrida, sin mencionarlo en el resumen.
   - `puede` true → continúa.
```

por:

```
   - `puede` false con motivo "no tiene audiencia agendada" → no crear borrador; el
     pedido pasa a `gestion_manual` (paso 3f) y se destaca en el resumen final (punto 5)
     — es lo más importante de todo el resumen.
   - `puede` false por no cumplirse aún el umbral de días hábiles desde el último aviso
     (ya sea el 2do aviso o uno posterior, cuyo umbral cambia solo según cuán cerca esté
     la audiencia) → saltar este pedido en esta corrida, sin mencionarlo en el resumen.
   - `puede` true → continúa. Ya no hay tope de avisos: mientras la causa tenga
     `fecha_audiencia` registrada, la cadencia se ajusta sola (más espaciada si falta
     mucho para la audiencia, diaria si está encima) en vez de detenerse a los 2 avisos.
```

- [ ] **Step 2: Commit**

```bash
git add gestion_causas/subagentes/seguimiento.md
git commit -m "docs(gestion_causas): documentar cadencia sin tope en el subagente de seguimiento"
```

---

## Verificación final

- [ ] **Correr toda la suite una última vez**

Run: `python -m pytest tests/ -q`

Expected: todos los tests pasan, sin warnings nuevos.
