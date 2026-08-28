# Cache de calendario por corrida Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar hasta ~54 llamadas repetidas a la API de Google Calendar por corrida
(una por causa, por subagente, todas trayendo el mismo rango de 200 días) por **una sola**
llamada al principio de la corrida de `goteo`, reusada por `agenda` a través de un archivo
en disco, sin cambiar ningún criterio de negocio ni el formato de salida existente.

**Architecture:** Dos funciones nuevas en `calendar_client.py` (traer y guardar el
calendario completo una vez; filtrar por RIT desde ese archivo en vez de la API), un
comando CLI nuevo (`cache-eventos-calendario`) y un flag nuevo en el comando existente
(`buscar-audiencia-por-rit --desde-cache`), y dos ediciones de prompt (`goteo.md` genera
el cache al principio de la corrida; `agenda.md` lo reusa, con fallback a la llamada en
vivo si el archivo no existe). Ver el diseño completo en
`Actualizador de informes/docs/2026-08-28-cache-calendario-por-corrida-design.md`.

**Tech Stack:** Python 3, pytest. Directorio de trabajo para todos los comandos:
`Actualizador de informes`.

---

### Task 1: `calendar_client.py` — guardar y filtrar eventos desde un cache en disco

**Files:**
- Modify: `gestion_causas/calendar_client.py` (imports en la parte superior; nuevas
  funciones después de `listar_eventos`, que termina en la línea 163)
- Test: `tests/test_calendar_client.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar `import json` a los imports de `tests/test_calendar_client.py` (arriba del
archivo, junto a `import inspect` y `from datetime import date`):

```python
import inspect
import json
from datetime import date
```

Agregar esta clase nueva a `tests/test_calendar_client.py`, después de la clase
`TestBuscarAudienciaPorRit` (termina en la línea 106) y antes de `class TestDetectarEmpresa:`:

```python
class TestCacheEventos:
    def test_guardar_cache_eventos_escribe_archivo_con_total_correcto(self, tmp_path):
        servicio = _ServicioCalendarFalso([
            {"items": [
                _evento("Audiencia Unica M-643-2026 Iturriaga con Rendic", date_time="2026-08-21T10:40:00-04:00"),
                _evento("Reunion equipo semanal", date_time="2026-08-25T09:00:00-04:00"),
            ]},
        ])
        ruta = tmp_path / "cache.json"

        resultado = calendar_client.guardar_cache_eventos(ruta=ruta, servicio=servicio)

        assert resultado == {"total": 2, "ruta": str(ruta)}
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        assert len(contenido["eventos"]) == 2
        assert contenido["eventos"][0] == {
            "fecha": "2026-08-21", "resumen": "Audiencia Unica M-643-2026 Iturriaga con Rendic",
        }
        assert "generado_en" in contenido

    def test_buscar_audiencia_por_rit_desde_cache_filtra_por_rit(self, tmp_path):
        ruta = tmp_path / "cache.json"
        ruta.write_text(json.dumps({
            "generado_en": "2026-08-28T09:00:00",
            "eventos": [
                {"fecha": "2026-08-21", "resumen": "Audiencia Unica M-643-2026 Iturriaga con Rendic"},
                {"fecha": "2026-08-25", "resumen": "Reunion equipo semanal"},
            ],
        }), encoding="utf-8")

        encontrados = calendar_client.buscar_audiencia_por_rit_desde_cache("M-643-2026", ruta=ruta)

        assert len(encontrados) == 1
        assert encontrados[0]["fecha"] == date(2026, 8, 21)

    def test_buscar_audiencia_por_rit_desde_cache_falla_si_no_existe_el_archivo(self, tmp_path):
        import pytest

        ruta = tmp_path / "no-existe.json"
        with pytest.raises(FileNotFoundError):
            calendar_client.buscar_audiencia_por_rit_desde_cache("M-1-2026", ruta=ruta)
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run (desde `Actualizador de informes`):
```bash
python -m pytest tests/test_calendar_client.py -k CacheEventos -v
```
Expected: 3 tests FAIL con `AttributeError: module 'gestion_causas.calendar_client' has
no attribute 'guardar_cache_eventos'` (o equivalente para `buscar_audiencia_por_rit_desde_cache`).

- [ ] **Step 3: Implementar el cambio mínimo**

En `gestion_causas/calendar_client.py`, agregar `import json` a los imports del archivo
(al principio, junto a `import sys` y `import unicodedata`):

```python
import json
import sys
import unicodedata
```

Agregar, después de la constante `SCOPES = [...]` (línea 67) y antes de `def log(msg):`
(línea 70), la ruta por defecto del cache:

```python
RUTA_CACHE_EVENTOS_CALENDARIO = Path(__file__).parent / "cache_eventos_calendario.json"
```

Agregar, después de `listar_eventos` (termina en la línea 163, justo antes de
`def buscar_audiencia_por_rit`), estas dos funciones nuevas:

```python
def guardar_cache_eventos(
    ruta: Path = RUTA_CACHE_EVENTOS_CALENDARIO, dias_adelante: int = 200, servicio=None
) -> dict:
    """Trae TODOS los eventos del calendario primario en el rango de
    `dias_adelante` días desde hoy (misma consulta que hace
    `buscar_audiencia_por_rit` por cada RIT) y los guarda en `ruta` como JSON.
    Existe para que una corrida que consulta muchas causas seguidas (goteo,
    agenda) traiga el calendario una sola vez en vez de una vez por causa —
    ver `buscar_audiencia_por_rit_desde_cache`. Devuelve {"total", "ruta"}."""
    hoy = date.today()
    eventos = listar_eventos(hoy, hoy + timedelta(days=dias_adelante), servicio=servicio)
    contenido = {
        "generado_en": datetime.now().isoformat(),
        "eventos": [{"fecha": str(e["fecha"]), "resumen": e["resumen"]} for e in eventos],
    }
    ruta = Path(ruta)
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"total": len(eventos), "ruta": str(ruta)}


def buscar_audiencia_por_rit_desde_cache(rit: str, ruta: Path = RUTA_CACHE_EVENTOS_CALENDARIO) -> list[dict]:
    """Igual que `buscar_audiencia_por_rit` pero filtrando eventos ya
    guardados en `ruta` (ver `guardar_cache_eventos`) en vez de llamar a la
    API — para no repetir la misma consulta de 200 días por cada causa
    dentro de una misma corrida. Lanza FileNotFoundError si `ruta` no
    existe (el llamador decide si cae de vuelta a `buscar_audiencia_por_rit`
    en ese caso)."""
    contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
    eventos = [
        {"fecha": datetime.strptime(e["fecha"], "%Y-%m-%d").date(), "resumen": e["resumen"]}
        for e in contenido["eventos"]
    ]
    return buscar_eventos_por_rit(eventos, rit)
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

Run:
```bash
python -m pytest tests/test_calendar_client.py -v
```
Expected: PASS (todos, incluidos los 3 nuevos).

- [ ] **Step 5: Commit**

```bash
git add gestion_causas/calendar_client.py tests/test_calendar_client.py
git commit -m "$(cat <<'EOF'
feat(gestion_causas): agregar cache de eventos de calendario en disco

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: CLI — `cache-eventos-calendario` y `buscar-audiencia-por-rit --desde-cache`

**Files:**
- Modify: `gestion_causas/cli.py` (nueva función `cmd_cache_eventos_calendario`; modificar
  `cmd_buscar_audiencia_por_rit`, líneas 467-473; nuevos/modificados subparsers, líneas
  681-688)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_cli.py`, agregar `"cache-eventos-calendario"` al set `esperados` de
`test_todos_los_subcomandos_esperados_existen` (después de `"eventos-calendario"`):

```python
            "buscar-audiencia-por-rit", "diagnostico-calendario", "eventos-calendario",
            "cache-eventos-calendario",
```

Agregar estos dos métodos a la clase `TestSubcomandosSinRed`, después de
`test_bitacora_dry_run_no_escribe_en_disco` (línea 56) y antes de
`test_comando_desconocido_falla_argparse`:

```python
    def test_cache_eventos_calendario_dry_run_no_llama_a_la_api(self, capsys):
        codigo = main(["--dry-run", "cache-eventos-calendario"])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True

    def test_buscar_audiencia_por_rit_desde_cache_no_llama_a_la_api(self, tmp_path, capsys):
        ruta = tmp_path / "cache.json"
        ruta.write_text(json.dumps({
            "generado_en": "2026-08-28T09:00:00",
            "eventos": [{"fecha": "2026-08-21", "resumen": "Audiencia Unica M-643-2026 Iturriaga"}],
        }), encoding="utf-8")

        codigo = main(["buscar-audiencia-por-rit", "--rit", "M-643-2026", "--desde-cache", str(ruta)])

        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["total"] == 1
        assert salida["eventos"][0]["fecha"] == "2026-08-21"
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run:
```bash
python -m pytest tests/test_cli.py -v
```
Expected: `test_todos_los_subcomandos_esperados_existen` FAILS (falta
`cache-eventos-calendario` en los subcomandos), `test_cache_eventos_calendario_dry_run_no_llama_a_la_api`
FAILS con `SystemExit`/argparse error (subcomando no existe todavía), y
`test_buscar_audiencia_por_rit_desde_cache_no_llama_a_la_api` FAILS (`--desde-cache` no es
un argumento reconocido todavía).

- [ ] **Step 3: Implementar el cambio mínimo**

En `gestion_causas/cli.py`, reemplazar `cmd_buscar_audiencia_por_rit` (líneas 467-473) por:

```python
def cmd_cache_eventos_calendario(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "cache-eventos-calendario", "ruta": args.ruta})
        return 0
    resultado = calendar_client.guardar_cache_eventos(ruta=args.ruta, dias_adelante=args.dias_adelante)
    _imprimir_json(resultado)
    return 0


def cmd_buscar_audiencia_por_rit(args) -> int:
    if args.ics:
        eventos = ics_mod.buscar_audiencia_por_rit(args.ics, args.rit)
    elif args.desde_cache:
        eventos = calendar_client.buscar_audiencia_por_rit_desde_cache(args.rit, args.desde_cache)
    else:
        eventos = calendar_client.buscar_audiencia_por_rit(args.rit, dias_adelante=args.dias_adelante)
    _imprimir_json({"rit": args.rit, "eventos": eventos, "total": len(eventos)})
    return 0
```

Reemplazar el bloque del subparser `buscar-audiencia-por-rit` (líneas 681-688) por:

```python
    p = sub.add_parser(
        "cache-eventos-calendario",
        help="Trae TODOS los eventos del calendario (rango de 200 dias) UNA vez y los guarda en un archivo, para que buscar-audiencia-por-rit --desde-cache no repita la llamada a la API por cada causa",
    )
    p.add_argument("--ruta", default=str(calendar_client.RUTA_CACHE_EVENTOS_CALENDARIO))
    p.add_argument("--dias-adelante", type=int, default=200)
    p.set_defaults(func=cmd_cache_eventos_calendario)

    p = sub.add_parser(
        "buscar-audiencia-por-rit",
        help="Fase 4: busca eventos que mencionan este RIT en el calendario de nmunoz@gomezyriesco.cl (API directa; --desde-cache usa un archivo generado por cache-eventos-calendario; --ics fuerza el modo antiguo por archivo exportado)",
    )
    p.add_argument("--rit", required=True)
    p.add_argument("--dias-adelante", type=int, default=200, help="Ventana de búsqueda hacia adelante desde hoy (API)")
    p.add_argument("--ics", default=None, help="Ruta a un .ics exportado a mano; si se indica, se usa en vez de la API")
    p.add_argument("--desde-cache", default=None, help="Ruta a un cache generado por cache-eventos-calendario; si se indica, filtra ese archivo en vez de llamar a la API")
    p.set_defaults(func=cmd_buscar_audiencia_por_rit)
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

Run:
```bash
python -m pytest tests/test_cli.py -v
```
Expected: PASS (todos, incluidos los 2 nuevos y el set de `esperados` actualizado).

Después, correr la suite completa para confirmar que nada más se rompió:
```bash
python -m pytest -q --ignore=tests/test_actualizar_informe_juicios.py
```
Expected: PASS en todos.

- [ ] **Step 5: Agregar el cache a `.gitignore`**

En `.gitignore` (raíz del repo, `C:\Users\usuario\Documents\Temporal 2\.gitignore`),
agregar al final del archivo:

```
# Cache efímero de gestion_causas (se regenera en cada corrida, no es dato a versionar)
Actualizador de informes/gestion_causas/cache_eventos_calendario.json
```

- [ ] **Step 6: Commit**

```bash
git add gestion_causas/cli.py tests/test_cli.py "../.gitignore"
git commit -m "$(cat <<'EOF'
feat(gestion_causas): agregar comando cache-eventos-calendario y flag --desde-cache

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
(el path de `.gitignore` de arriba es relativo a `Actualizador de informes` como cwd —
ajusta si tu shell está parado en otro directorio; lo importante es que termine
apuntando al `.gitignore` de la raíz del repo, `Temporal 2/.gitignore`)

---

### Task 3: `subagentes/goteo.md` — generar el cache una vez por corrida

**Files:**
- Modify: `gestion_causas/subagentes/goteo.md`

Archivo de prompt, sin tests automatizados — verificación por lectura cuidadosa (igual
criterio que la Task 3 del plan hermano, `2026-08-28-goteo-incremental-y-acuerdo-pago.md`).

- [ ] **Step 1: Releer el archivo actual primero**

Usar el Read tool sobre `gestion_causas/subagentes/goteo.md` completo antes de editar —
las líneas de abajo son de una lectura reciente y deberían calzar, pero confirma contra
el contenido real antes de aplicar los cambios (por si algo más lo tocó mientras tanto).

- [ ] **Step 2: Agregar el paso de generar el cache, al final de la sección "## 1. Trae
  las causas activas"**

Ubicar el párrafo que termina en (dentro de la sección `## 1. Trae las causas activas`):
```markdown
Esto devuelve las causas sin fecha de audiencia registrada, o con audiencia en el futuro,
o cuya audiencia fue hace 60 días o menos (la prueba puede seguir llegando un tiempo
después de la audiencia, ej. por reprogramación). Si `total` es 0, termina con un resumen
de "sin causas activas para revisar".
```
Agregar inmediatamente después (todavía dentro de la sección `## 1`, antes del
`## 2. Por cada causa activa`):

```markdown

Después, trae el calendario **una sola vez** para toda la corrida (en vez de que cada
causa dispare su propia llamada a la API en el paso 2a):
```
python -m gestion_causas.cli cache-eventos-calendario
```
Guarda la `ruta` que devuelve — la vas a pasar como `--desde-cache <ruta>` en el paso 2a
de **todas** las causas de esta corrida (por defecto ya es
`gestion_causas/cache_eventos_calendario.json`, así que si no le pasaste `--ruta` propia,
podés usar esa ruta fija directamente sin necesidad de leerla de la respuesta).
```

- [ ] **Step 3: Cambiar el paso 2a para usar el cache**

Ubicar, dentro del paso `a.` de la sección `## 2. Por cada causa activa`:

```markdown
a. **Determina la carpeta destino de los documentos**, según el tipo de la próxima
   audiencia (mismo mecanismo que usa `gestion-causas-agenda` paso 2 — calendario de
   `nmunoz@gomezyriesco.cl` en solo lectura):
   ```
   python -m gestion_causas.cli buscar-audiencia-por-rit --rit "<rit>"
   ```
```

Reemplazar por:

```markdown
a. **Determina la carpeta destino de los documentos**, según el tipo de la próxima
   audiencia (mismo mecanismo que usa `gestion-causas-agenda` paso 2 — calendario de
   `nmunoz@gomezyriesco.cl` en solo lectura), usando el cache que ya trajiste en el paso 1
   (no vuelvas a llamar a la API por cada causa):
   ```
   python -m gestion_causas.cli buscar-audiencia-por-rit --rit "<rit>" --desde-cache "<ruta del cache del paso 1>"
   ```
```

El resto del paso `a.` (desde "Quédate con el primer evento futuro o de hoy..." hasta el
final) no cambia.

- [ ] **Step 4: Releer el archivo completo**

Confirmar que: (a) el nuevo párrafo de la sección 1 quedó antes del `## 2. Por cada causa
activa` y después del párrafo de `causas-activas`, (b) el paso `a.` referencia
correctamente "el cache que ya trajiste en el paso 1", y (c) ningún otro paso (b, c, c2,
d, e, f, g, h) quedó afectado por este cambio — el cache de calendario es independiente
del filtro incremental de Gmail del paso 2b (son dos optimizaciones separadas sobre APIs
distintas).

- [ ] **Step 5: Commit**

```bash
git add gestion_causas/subagentes/goteo.md
git commit -m "$(cat <<'EOF'
docs(gestion_causas): goteo trae el calendario una sola vez por corrida

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `subagentes/agenda.md` — reusar el cache de goteo, con fallback

**Files:**
- Modify: `gestion_causas/subagentes/agenda.md`

Igual que la Task 3: archivo de prompt, sin tests automatizados.

- [ ] **Step 1: Releer el archivo actual primero**

Usar el Read tool sobre `gestion_causas/subagentes/agenda.md` completo antes de editar.

- [ ] **Step 2: Modificar el paso 2 para intentar el cache primero, con fallback**

Ubicar, en la sección `## 2. Por cada causa activa, busca su audiencia en el calendario`:

```markdown
```
python -m gestion_causas.cli buscar-audiencia-por-rit --rit "<rit>"
```
Busca en el calendario de `nmunoz@gomezyriesco.cl` (vía API, ventana de 200 días hacia
adelante desde hoy por defecto — usa `--dias-adelante` si necesitas más rango) los
eventos que mencionan ese RIT, y devuelve fecha + resumen del título, ordenados por fecha
ascendente. Quédate con el **primero futuro o de hoy** (si todos son pasados, no hay
audiencia próxima — sáltala). **Usa esta fecha como fuente de verdad**, no el campo
`fecha_audiencia` guardado en el registro (que viene del cuadro del correo y puede quedar
desactualizado si se reprogramó). Si `total` es 0, sáltala y anótalo en el resumen — nada
que agendar todavía para esa causa.
```

Reemplazar por:

```markdown
Antes de procesar la primera causa, revisa si existe
`gestion_causas/cache_eventos_calendario.json` — lo genera el subagente `goteo`, que
corre justo antes que vos en el orden fijo del orquestador, así que en una corrida normal
ya está fresco. Si existe, vas a usarlo con `--desde-cache` en vez de golpear la API por
cada causa; si no existe (ej. goteo falló antes de llegar a ese paso, o estás corriendo
agenda de forma suelta fuera del orquestador), vas a usar la llamada en vivo de siempre,
sin `--desde-cache` — el resultado es idéntico en ambos casos, solo cambia si se repite la
llamada a la API por cada causa o no.

```
python -m gestion_causas.cli buscar-audiencia-por-rit --rit "<rit>" --desde-cache "gestion_causas/cache_eventos_calendario.json"
```
(si el archivo no existe, omití `--desde-cache` y corré el comando tal cual, sin ese
flag — cae de vuelta al comportamiento de siempre)

Busca en el calendario de `nmunoz@gomezyriesco.cl` (vía API, ventana de 200 días hacia
adelante desde hoy por defecto — usa `--dias-adelante` si necesitas más rango) los
eventos que mencionan ese RIT, y devuelve fecha + resumen del título, ordenados por fecha
ascendente. Quédate con el **primero futuro o de hoy** (si todos son pasados, no hay
audiencia próxima — sáltala). **Usa esta fecha como fuente de verdad**, no el campo
`fecha_audiencia` guardado en el registro (que viene del cuadro del correo y puede quedar
desactualizado si se reprogramó). Si `total` es 0, sáltala y anótalo en el resumen — nada
que agendar todavía para esa causa.
```

- [ ] **Step 3: Releer el archivo completo**

Confirmar que el resto de la sección `## 2` (determinación del tipo de audiencia, el
manejo de causas que no son demanda laboral estándar) sigue exactamente igual después del
bloque reemplazado, y que las secciones `## 3` y `## 4` no quedaron afectadas.

- [ ] **Step 4: Commit**

```bash
git add gestion_causas/subagentes/agenda.md
git commit -m "$(cat <<'EOF'
docs(gestion_causas): agenda reusa el cache de calendario de goteo, con fallback

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Verificación final

- [ ] Correr toda la suite para confirmar que no se rompió nada fuera de lo tocado:
  ```bash
  python -m pytest -q --ignore=tests/test_actualizar_informe_juicios.py
  ```
  Expected: PASS en todos los tests.
