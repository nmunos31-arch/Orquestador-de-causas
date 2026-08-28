# Goteo incremental + seguimiento de acuerdo/pago Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que el subagente goteo (Fase 3 del orquestador `gestion-causas-orquestador`)
solo re-escanee correos de causas con novedades desde la última revisión (con un rescan
completo de respaldo los lunes), y que registre formalmente cuándo una causa llegó a un
acuerdo pendiente de pago y cuándo llegó el comprobante, sin cerrar la causa sola.

**Architecture:** Dos cambios de datos/lógica en `gestion_causas` (`registro.py`,
`panel.py`, cubiertos con tests) más un cambio de instrucciones en el prompt del
subagente (`subagentes/goteo.md`, sin tests automatizados — es un documento que lee un
agente, no código). Ver el diseño completo en
`Actualizador de informes/docs/2026-08-28-goteo-incremental-y-acuerdo-pago-design.md`.

**Tech Stack:** Python 3, pytest. Directorio de trabajo para todos los comandos:
`Actualizador de informes`.

---

### Task 1: `causas_para_goteo` sigue revisando causas con acuerdo pendiente de pago

**Files:**
- Modify: `gestion_causas/registro.py:118-149`
- Test: `tests/test_registro.py` (clase `TestCausasParaGoteo`, después de la línea 176)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar estos dos métodos a la clase `TestCausasParaGoteo` en
`tests/test_registro.py`, justo después de `test_excluye_causa_con_audiencia_muy_antigua`
(línea 176) y antes de `test_excluye_causa_cerrada_aunque_no_tenga_fecha_audiencia`:

```python
    def test_incluye_causa_con_acuerdo_pendiente_pago_aunque_audiencia_muy_antigua(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa(
            "M-1-2026",
            {"fecha_audiencia": "2026-01-01", "estado_acuerdo": "pendiente_pago"},
            ruta,
        )  # audiencia muy pasada, pero con acuerdo pendiente de pago

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 1
        assert activas[0]["rit"] == "M-1-2026"

    def test_incluye_causa_con_pago_recibido_pendiente_confirmar_aunque_audiencia_muy_antigua(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa(
            "M-2-2026",
            {"fecha_audiencia": "2026-01-01", "estado_acuerdo": "pago_recibido_pendiente_confirmar"},
            ruta,
        )

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 1
        assert activas[0]["rit"] == "M-2-2026"
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run (desde `Actualizador de informes`):
```bash
python -m pytest tests/test_registro.py -k acuerdo_pendiente_pago -v
```
Expected: 2 tests FAIL (la causa no aparece en `activas` porque su audiencia está fuera
de la ventana de 60 días).

- [ ] **Step 3: Implementar el cambio mínimo**

En `gestion_causas/registro.py`, reemplazar la función `causas_para_goteo` completa
(líneas 118-149) por:

```python
def causas_para_goteo(
    hoy=None, dias_ventana_post_audiencia: int = 60, ruta: Path = RUTA_REGISTRO_CAUSAS
) -> list:
    """Causas que conviene seguir revisando por documentos nuevos (Fase 3):
    las que todavía no tienen fecha de audiencia registrada, o cuya audiencia
    fue hace `dias_ventana_post_audiencia` días o menos (la prueba puede
    seguir llegando un tiempo después, ej. por una reprogramación), o cuyo
    `estado_acuerdo` es "pendiente_pago" o "pago_recibido_pendiente_confirmar"
    (el pago de un acuerdo puede demorar meses, más allá de la ventana normal
    post-audiencia). Acota el barrido para que no crezca sin límite a medida
    que se acumulan causas viejas ya cerradas. Las causas con
    `causa_cerrada: true` se excluyen siempre, sin importar lo anterior.

    `hoy` es inyectable para tests; por defecto usa la fecha actual.
    Devuelve una lista de entradas del registro (dicts), cada una con su
    "rit" y "thread_id".
    """
    if hoy is None:
        hoy = date.today()
    else:
        hoy = _parsear_fecha(hoy)

    resultado = []
    for entrada in cargar_registro_causas(ruta).values():
        if entrada.get("causa_cerrada"):
            continue
        if entrada.get("estado_acuerdo") in ("pendiente_pago", "pago_recibido_pendiente_confirmar"):
            resultado.append(entrada)
            continue
        fecha_audiencia = entrada.get("fecha_audiencia")
        if not fecha_audiencia:
            resultado.append(entrada)
            continue
        dias_desde_audiencia = (hoy - _parsear_fecha(fecha_audiencia)).days
        if dias_desde_audiencia <= dias_ventana_post_audiencia:
            resultado.append(entrada)
    return resultado
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

Run:
```bash
python -m pytest tests/test_registro.py -v
```
Expected: PASS (todos, incluidos los 2 nuevos y los preexistentes de
`TestCausasParaGoteo`).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/registro.py" "Actualizador de informes/tests/test_registro.py"
git commit -m "$(cat <<'EOF'
feat(gestion_causas): mantener en goteo las causas con acuerdo pendiente de pago

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Badges de "Acuerdo pendiente de pago" y "Pago recibido" en el panel

**Files:**
- Modify: `gestion_causas/panel.py:25-37` (`_fase_actual`)
- Modify: `gestion_causas/panel.py:103-110` (`_COLOR_FASE_CAUSA`)
- Test: `tests/test_panel.py` (clase `TestEstadoCausas`, después de `test_causa_con_minuta`)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar estos dos métodos a la clase `TestEstadoCausas` en `tests/test_panel.py`, justo
después de `test_causa_con_minuta` (línea 59) y antes de
`test_sin_ultima_actualizacion_da_none`:

```python
    def test_causa_con_acuerdo_pendiente_pago(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-5-2026": {
                "rit": "M-5-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "estado_acuerdo": "pendiente_pago",
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Acuerdo pendiente de pago"

    def test_causa_con_pago_recibido_pendiente_confirmar(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-6-2026": {
                "rit": "M-6-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "estado_acuerdo": "pago_recibido_pendiente_confirmar",
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Pago recibido, pendiente confirmar cierre"
```

Nota: esta clase ya tiene un método `test_causa_cerrada` (línea 69) y un
`test_alerta_por_dias_sin_actualizar` que usan RIT `M-5-2026`/`M-6-2026` — revisar antes
de pegar que no choquen los nombres de RIT dentro del mismo diccionario de
`_escribir_registro` (cada test usa su propio `tmp_path`, así que no hay conflicto real
entre tests, pero sí conviene no repetir el mismo RIT dentro del mismo `_escribir_registro`
de un test).

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run:
```bash
python -m pytest tests/test_panel.py -k "acuerdo_pendiente_pago or pago_recibido_pendiente_confirmar" -v
```
Expected: 2 tests FAIL (`fase` da "Demanda guardada, en curso" en vez del badge nuevo,
porque `_fase_actual` todavía no conoce `estado_acuerdo`).

- [ ] **Step 3: Implementar el cambio mínimo**

En `gestion_causas/panel.py`, reemplazar `_fase_actual` (líneas 25-37) por:

```python
def _fase_actual(causa: dict) -> str:
    """Infiere una etiqueta de fase legible a partir de los campos que ya
    guardan calendario/smu/goteo/agenda en el registro — no es un campo
    propio, se recalcula siempre desde cero."""
    if causa.get("causa_cerrada"):
        return "Cerrada"
    if causa.get("estado_acuerdo") == "pago_recibido_pendiente_confirmar":
        return "Pago recibido, pendiente confirmar cierre"
    if causa.get("estado_acuerdo") == "pendiente_pago":
        return "Acuerdo pendiente de pago"
    if causa.get("minuta_ejecutada"):
        return "Minuta generada"
    if causa.get("oferta_borrador_creado"):
        return "Ofrecimiento enviado a Roman"
    if causa.get("tiene_demanda"):
        return "Demanda guardada, en curso"
    return "Recien registrada"
```

Y reemplazar `_COLOR_FASE_CAUSA` (líneas 103-110) por:

```python
_COLOR_FASE_CAUSA = {
    "Recien registrada": ("#92400e", "#fef3c7"),
    "Demanda guardada, en curso": ("#075985", "#e0f2fe"),
    "Ofrecimiento enviado a Roman": ("#6d28d9", "#ede9fe"),
    "Acuerdo pendiente de pago": ("#9a3412", "#ffedd5"),
    "Pago recibido, pendiente confirmar cierre": ("#0f766e", "#ccfbf1"),
    "Minuta generada": ("#065f46", "#d1fae5"),
    "Cerrada": ("#4b5563", "#f3f4f6"),
}
_COLOR_FASE_CAUSA_DEFAULT = ("#4b5563", "#f3f4f6")
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

Run:
```bash
python -m pytest tests/test_panel.py -v
```
Expected: PASS (todos, incluidos los 2 nuevos y los preexistentes).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/panel.py" "Actualizador de informes/tests/test_panel.py"
git commit -m "$(cat <<'EOF'
feat(gestion_causas): mostrar badges de acuerdo pendiente de pago en el panel

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Reescribir `subagentes/goteo.md` — filtro incremental + detección de acuerdo/pago

**Files:**
- Modify: `subagentes/goteo.md`

Este archivo es un prompt (instrucciones en lenguaje natural para el subagente LLM que
ejecuta el orquestador), no código — no tiene test automatizado. La verificación es una
lectura cuidadosa del texto final contra el spec, más observar la próxima corrida real.

- [ ] **Step 1: Actualizar el encabezado/nota de razón de ser (línea 1-20)**

Agregar, después del párrafo que empieza en la línea 12 ("Razón de que sea una tarea
separada..."), un párrafo nuevo:

```markdown
**Filtro incremental (2026-08-28):** para no re-escanear correos de causas sin
novedades en cada una de las 3 corridas diarias, el paso 2b usa `goteo_ultima_revision`
(fecha `AAAA-MM-DD` guardada en el registro de cada causa) para acotar la búsqueda a
mail nuevo desde la corrida anterior — ver el paso 2b y 2h más abajo. Los lunes se hace
igual el escaneo completo de siempre (sin el filtro), como red de seguridad semanal.
```

- [ ] **Step 2: Reescribir el paso 2b (líneas 150-163) con el filtro incremental**

Reemplazar el paso `b. **Busca todos los hilos relacionados con el RIT**...` completo
(desde `b. **Busca todos los hilos relacionados con el RIT**` hasta el final de esa
viñeta, justo antes de `c. Para cada hilo relevante`) por:

```markdown
b. **Busca todos los hilos relacionados con el RIT**, no solo el `thread_id` original que
   guardó Fase 1 (los documentos reales suelen llegar en una cadena "RV:" aparte, abierta
   por RR.HH./legal de la empresa — ver nota de dominios más arriba).

   **Si hoy es lunes, o la causa no tiene `goteo_ultima_revision` en su registro**
   (revísalo con `obtener-causa --rit "<rit>"` — primera vez que el goteo la revisa):
   escaneo completo, igual que siempre:
   ```
   python -m gestion_causas.cli buscar-hilos --query "<rit>"
   ```
   Incluye también el `thread_id` guardado en el registro de la causa aunque no aparezca
   en esta búsqueda (por si acaso).

   **Cualquier otro día**, con `goteo_ultima_revision` ya registrada: acota la búsqueda a
   mail nuevo desde la corrida anterior, restando 1 día a `goteo_ultima_revision` como
   colchón (el operador `after:` de Gmail filtra por día completo, no por hora, así que
   sin el colchón se podría perder algo llegado el mismo día después de que goteo ya
   pasó):
   ```
   python -m gestion_causas.cli buscar-hilos --query "<rit> after:<goteo_ultima_revision menos 1 día, formato AAAA/MM/DD>"
   ```
   No hace falta forzar además la inclusión del `thread_id` original en este caso — si
   llegó mail nuevo ahí, el mismo filtro `after:` ya lo encuentra (el RIT queda en el
   asunto de todos los mensajes de esa cadena, incluidas las réplicas).

   En ambos casos: si un hilo encontrado claramente no tiene que ver con la causa
   (coincidencia de texto casual), descártalo — usa criterio, no proceses todo a ciegas.
   Esto incluye los hilos "Provisiones demanda laborales [mes]", "Informe de provisión
   [mes]" / "INFORME PROVISIÓN [mes]" y "Risgo causas estado sentencias" / "Riesgo causas
   estado sentencias" (quitando primero cualquier prefijo "RE:"/"RV:"/"FWD:"/"ENV:" del
   subject — ver nota de filtro de asunto más arriba) y cualquier otro reporte/consolidado
   interno que solo mencione el RIT de pasada.
```

- [ ] **Step 3: Agregar el nuevo sub-paso de detección de acuerdo/pago, entre el paso 2c
  (leer hilos) y el paso 2d (listar carpeta) actuales**

Insertar como nuevo paso `c2` (entre el `c.` que lee los hilos y el `d.` que lista la
carpeta):

```markdown
c2. **Detecta acuerdo alcanzado y pago recibido**, con el mismo contenido que ya
    trajiste en el paso c (no es una lectura adicional, es criterio sobre lo que ya
    leíste):

    - Si la causa **no** tiene todavía `estado_acuerdo` en su registro (revísalo con
      `obtener-causa --rit "<rit>"`) y el contenido de algún hilo confirma que se
      **alcanzó y aprobó** un avenimiento/conciliación/acuerdo — no una negociación en
      curso ni una oferta, hace falta confirmación de que el acuerdo ya se cerró (ej.
      "acta de conciliación", "avenimiento aprobado", "se aprobó el acuerdo por $X",
      "conciliación total"):
      ```
      python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"estado_acuerdo\": \"pendiente_pago\"}>"
      ```
      Anota en la bitácora ("Acuerdo alcanzado, pendiente de pago") y menciónalo en el
      resumen final.

    - Si la causa **ya** tiene `estado_acuerdo: "pendiente_pago"` y algún hilo (el mismo
      u otro) trae un comprobante de pago/transferencia asociado a ese acuerdo:
      guárdalo como cualquier adjunto de este paso (mismas reglas de dominio confiable y
      de-dupe del paso e más abajo — no hace falta un mecanismo nuevo), y luego:
      ```
      python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"estado_acuerdo\": \"pago_recibido_pendiente_confirmar\"}>"
      ```
      Anota en la bitácora ("Comprobante de pago recibido, pendiente que Nico confirme
      el cierre") y destácalo en el resumen final — **no** marques `causa_cerrada`, eso
      lo decide Nico a mano.
```

- [ ] **Step 4: Agregar el paso 2h — guardar `goteo_ultima_revision`**

Insertar como nuevo paso `h.`, después del paso `g.` actual (el que anota en la
bitácora si se guardó algo nuevo) y antes de la sección `## 3. Resumen final`:

```markdown
h. **Guarda la fecha de esta revisión**, siempre (haya habido novedades o no) — es lo
   que permite que la próxima corrida use el filtro incremental del paso 2b:
   ```
   python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"goteo_ultima_revision\": \"<fecha de hoy AAAA-MM-DD>\"}>"
   ```
```

- [ ] **Step 5: Actualizar la sección "3. Resumen final"**

Reemplazar el párrafo de la sección `## 3. Resumen final` por:

```markdown
Tu **último mensaje** de esta ejecución es el resumen que el orquestador va a copiar tal
cual a la sección "Fase goteo" del panel de estado. Entrega un resumen breve: cuántas
causas se revisaron (y si hoy fue rescan completo de lunes o revisión incremental),
cuántas tenían documentos nuevos (con el RIT y los nombres de los documentos, indicando
cuáles se guardaron en la subcarpeta "Exhibición de documentos" por tener audiencia de
juicio próxima), cuántos de esos documentos se identificaron como EERR y quedaron
disponibles para reuso futuro, cuántas causas pasaron a "acuerdo pendiente de pago" y
cuántas a "pago recibido, pendiente confirmar cierre" (con su RIT, para que Nico las
revise). Si no hubo novedades en ninguna causa, dilo en una sola línea.
```

- [ ] **Step 6: Releer el archivo completo**

Usar el visor de archivos (o `cat`) para releer `subagentes/goteo.md` de punta a punta
y confirmar que: (a) no quedó ningún texto de placeholder tipo "менос" del Step 2, (b)
la numeración de sub-pasos del punto 2 queda coherente (a, b, c, c2, d, e, f, g, h), y
(c) las referencias cruzadas ("ver paso 2b", "ver paso e más abajo") siguen apuntando al
contenido correcto tras la inserción de c2 y h.

- [ ] **Step 7: Commit**

```bash
git add "Actualizador de informes/gestion_causas/subagentes/goteo.md"
git commit -m "$(cat <<'EOF'
docs(gestion_causas): filtro incremental y deteccion de acuerdo/pago en goteo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Verificación final

- [ ] Correr toda la suite para confirmar que no se rompió nada fuera de lo tocado:
  ```bash
  python -m pytest -v
  ```
  Expected: PASS en todos los tests (incluidos los de `test_registro.py` y
  `test_panel.py` de las Tasks 1 y 2).
