# Optimización del uso de tokens del orquestador — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bajar el gasto de tokens de Claude por corrida del orquestador, cortando el flujo viejo de 6 subagentes al driver Python ya migrado y acotando lo que consumen las ~24 llamadas de razonamiento que quedan.

**Architecture:** Cinco cambios independientes, en orden de dependencia. Primero **instrumentar** (`reasoning.py` pasa a `claude -p --output-format json` y registra el `usage` de cada llamada en un JSONL), porque sin medición el resto son estimaciones. Después el **corte del scheduler**: `orquestador.py` ya reemplaza los 5 subagentes y los pasos 3-6 del `SKILL.md`, pero exige que `_contexto_corrida.json` ya exista — se le agrega que lo arme solo si falta, para que la tarea programada sea un único comando, y `SKILL.md` se reduce a ese comando. Encima de esa línea base nueva van tres recortes sobre las llamadas que quedan: **caché entre corridas** (mismo hilo sin cambios, 3 corridas/día, hoy se re-pregunta cada vez), **contexto acotado** en `goteo` (hoy el tope es 400k caracteres ≈ 100k tokens por causa por corrida, y trunca cortando mensajes al medio) y **selección de modelo** por llamada (hoy todas corren el modelo por defecto del CLI, incluidas dos clasificaciones acotadas que no lo necesitan).

**Tech Stack:** Python 3.11+, pytest, `gestion_causas.reasoning`, `gestion_causas.registro` (para su `_lock`), `claude -p` (CLI 2.1.x).

**Spec:** `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md` (diseño general del driver). El diagnóstico específico que motiva este plan está en la sección "Diagnóstico" de abajo — no hay spec aparte: los cinco cambios son acotados sobre código que ya existe.

## Diagnóstico

Medido sobre el repo al commit `5cae317`:

1. **El scheduler todavía corre el flujo viejo.** El `README.md` lo dice: "La tarea programada real (`gestion-causas-orquestador`) todavía corre el flujo viejo de subagentes — el corte a este driver es una decisión pendiente." Ese flujo son 6 agentes (1 orquestador + 5 subagentes), cada subagente leyendo un `.md` de 205-425 líneas (1.592 líneas en total en `gestion_causas/subagentes/`) y corriendo un loop agéntico completo con decenas de llamadas Bash a `cli.py`. `orquestador.py::correr_y_enviar_panel()` ya hace lo mismo en un solo proceso Python con las 5 fases migradas.
2. **No hay caché entre corridas.** `cli._generar_mapa_hilos_por_rit` guarda en `hilos[thread_id]` *todos* los mensajes de cada hilo activo, no solo los nuevos. `goteo._detectar_acuerdo_y_pago` y `seguimiento._clasificar_pedido` reciben ese mismo contenido en cada una de las 3 corridas diarias, así que el prompt es idéntico byte por byte mientras el hilo no cambie.
3. **`goteo.LIMITE_CONTEXTO_CHARS = 400_000`** (`gestion_causas/fases/goteo.py:34`) ≈ 100k tokens en una sola llamada, por causa, por corrida. Además `_acotar_mensajes_por_tamano` recorta con `mensaje["cuerpo"][recorte:]`, o sea que parte un mensaje al medio y deja un fragmento sin su encabezado.
4. **Ninguna llamada elige modelo.** No hay `--model` en `reasoning.py`; todo corre el modelo por defecto del CLI, incluidas `_detectar_acuerdo_y_pago` (2 booleanos + justificación) y `_clasificar_pedido` (3 campos contra una lista corta).
5. **No se mide nada.** `_ejecutar_claude` corre `claude -p` en texto plano y descarta el `usage`.

**Fuera de alcance de este plan (plan aparte):** migrar las llamadas texto→JSON al SDK `anthropic` directo para eliminar el ~25% de overhead fijo por proceso que documenta el docstring de `_ejecutar_claude`. Es un rediseño de `reasoning.py`, no un recorte, y la decisión depende de los números que produzca la Task 1.

## Global Constraints

- Python 3.11+ (`README.md`).
- `reasoning.preguntar` nunca lanza una excepción hacia afuera: un fallo de la llamada externa devuelve `{"error": "<detalle>"}` y el llamador sigue con la causa siguiente. Todo cambio en este plan mantiene esa propiedad.
- Nunca se usa `--dangerously-skip-permissions`.
- El parámetro `ejecutar` de `preguntar`/`invocar_skill` sigue siendo inyectable para tests y sigue recibiendo el prompt armado y devolviendo **el texto de la respuesta del modelo** (no el envoltorio JSON del CLI) — el envoltorio se parsea dentro de `_ejecutar_claude`.
- Ningún archivo de estado en tiempo de ejecución entra a git: todo archivo nuevo de estado se agrega a `gestion_causas/.gitignore`.
- Las escrituras a archivos de estado compartido usan `registro._lock` (las fases `goteo`/`agenda`/`seguimiento` pueden correr en paralelo en el flujo viejo).
- No se tocan `panel.py`, `gmail_client.py`, `calendar_client.py` ni las reglas de negocio de ninguna fase. Este plan no cambia ninguna decisión que tome el sistema — solo cuánto cuesta tomarla.

## Review Focus

Casos que el diagnóstico implica y que ninguna tarea ejercita si no se agrega el test a propósito. Cada línea tiene su test asignado a la tarea que es dueña del código:

1. **`claude -p --output-format json` puede devolver `is_error: true` con exit code 0** — un fallo del modelo (rechazo, límite de contexto) no siempre es exit code distinto de cero. `_ejecutar_claude` tiene que tratarlo como fallo, no devolver el texto de error como si fuera la respuesta. → Task 1, Step 7.
2. **El JSONL de uso no puede tumbar una corrida** — disco lleno, permisos, ruta inexistente. Registrar el uso es telemetría: si falla, la llamada de razonamiento ya se pagó y su resultado tiene que llegar igual. → Task 1, Step 2.
3. **Un `{"error": ...}` nunca debe entrar al caché** — si se cachea un fallo, la causa queda envenenada hasta que expire el TTL y deja de evaluarse en cada corrida. → Task 3, Step 5.
4. **Un archivo de caché corrupto o ilegible degrada a "sin caché"** — un JSON truncado por una corrida interrumpida no puede hacer fallar la fase entera. → Task 3, Step 2.
5. **Un hilo cuyo único mensaje ya supera el límite** — el truncado por mensaje entero no puede devolver una lista vacía y preguntarle a Claude sobre la nada; tiene que mandar ese mensaje recortado. → Task 4, Step 1.

---

## Task 1: Instrumentación del `usage` de cada llamada

Sin esto, las tasks 3-5 no se pueden validar: no hay forma de decir si bajó el gasto.

**Files:**
- Create: `gestion_causas/uso_tokens.py`
- Create: `tests/test_uso_tokens.py`
- Modify: `gestion_causas/reasoning.py` (`_ejecutar_claude`, `_ejecutar_claude_skill`)
- Modify: `gestion_causas/.gitignore`
- Test: `tests/test_reasoning.py`

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces:
  - `uso_tokens.registrar(evento: dict, ruta: Path = RUTA_USO_TOKENS) -> None`
  - `uso_tokens.resumen(ruta: Path = RUTA_USO_TOKENS, desde: str | None = None) -> dict`
  - `uso_tokens.RUTA_USO_TOKENS: Path`

- [x] **Step 1: Confirmar empíricamente la forma del envoltorio JSON**

No asumas los nombres de los campos. Corré esto en una máquina con `claude` en el PATH:

```bash
echo 'Responde solo con {"ok": true}' | claude -p --output-format json --disable-slash-commands --setting-sources "" --tools "" --strict-mcp-config
```

Anotá los nombres exactos que devuelve. Al momento de escribir este plan (CLI 2.1.278) el envoltorio es:

```json
{"type": "result", "subtype": "success", "is_error": false, "duration_ms": 0,
 "num_turns": 1, "result": "{\"ok\": true}", "session_id": "...",
 "total_cost_usd": 0.0,
 "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0,
           "cache_read_input_tokens": 0, "output_tokens": 0}}
```

Si los nombres difieren, usá los reales en los steps siguientes y corregí este bloque en el plan.

- [x] **Step 2: Escribir el test que falla de `uso_tokens.registrar`**

```python
# tests/test_uso_tokens.py
import json

from gestion_causas import uso_tokens


class TestRegistrar:
    def test_agrega_una_linea_json_por_evento(self, tmp_path):
        ruta = tmp_path / "uso.jsonl"

        uso_tokens.registrar({"llamada": "goteo", "input_tokens": 10}, ruta=ruta)
        uso_tokens.registrar({"llamada": "seguimiento", "input_tokens": 20}, ruta=ruta)

        lineas = ruta.read_text(encoding="utf-8").strip().split("\n")
        assert len(lineas) == 2
        assert json.loads(lineas[0])["llamada"] == "goteo"
        assert json.loads(lineas[1])["input_tokens"] == 20

    def test_agrega_timestamp_si_el_evento_no_lo_trae(self, tmp_path):
        ruta = tmp_path / "uso.jsonl"

        uso_tokens.registrar({"llamada": "goteo"}, ruta=ruta)

        evento = json.loads(ruta.read_text(encoding="utf-8").strip())
        assert "momento" in evento

    def test_no_lanza_si_no_se_puede_escribir(self, tmp_path):
        """Telemetría: para cuando se llama acá, la llamada de razonamiento
        ya se pagó. Un disco lleno o una ruta inexistente no puede hacer
        que se pierda su resultado."""
        ruta_imposible = tmp_path / "no" / "existe" / "uso.jsonl"

        uso_tokens.registrar({"llamada": "goteo"}, ruta=ruta_imposible)

        assert not ruta_imposible.exists()
```

- [x] **Step 3: Correr el test para verificar que falla**

Run: `pytest tests/test_uso_tokens.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.uso_tokens'`

- [x] **Step 4: Escribir `uso_tokens.py`**

```python
"""Telemetría de consumo de tokens de las llamadas a Claude.

Una línea JSON por llamada en un JSONL acumulativo — mismo criterio que
`bitacora.py` (append-only, auditable a mano), pero estructurado para poder
sumarlo. Es telemetría: `registrar` nunca lanza (ver `resumen` para leerlo).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

RUTA_USO_TOKENS = Path(__file__).parent / "uso_tokens.jsonl"


def registrar(evento: dict, ruta: Path = RUTA_USO_TOKENS) -> None:
    """Agrega `evento` como una línea JSON. Nunca lanza: si no se puede
    escribir (disco lleno, permisos, ruta inexistente), se descarta en
    silencio — para cuando se llama acá la llamada de razonamiento ya se
    pagó y su resultado tiene que llegar al llamador igual."""
    entrada = {"momento": datetime.now().isoformat(), **evento}
    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - telemetría nunca tumba una corrida
        pass


def resumen(ruta: Path = RUTA_USO_TOKENS, desde: str | None = None) -> dict:
    """Suma el JSONL. `desde` (AAAA-MM-DD) acota a los eventos de esa fecha
    en adelante. Una línea ilegible se saltea en vez de hacer fallar el
    resumen entero."""
    totales = {
        "llamadas": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "costo_usd": 0.0, "por_llamada": {},
    }
    if not Path(ruta).exists():
        return totales

    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        if desde and str(evento.get("momento", "")) < desde:
            continue
        totales["llamadas"] += 1
        for campo in ("input_tokens", "output_tokens",
                      "cache_creation_input_tokens", "cache_read_input_tokens"):
            totales[campo] += evento.get(campo) or 0
        totales["costo_usd"] += evento.get("costo_usd") or 0.0
        nombre = evento.get("llamada") or "desconocida"
        totales["por_llamada"][nombre] = totales["por_llamada"].get(nombre, 0) + 1

    return totales
```

- [x] **Step 5: Correr el test para verificar que pasa**

Run: `pytest tests/test_uso_tokens.py -v`
Expected: PASS

- [x] **Step 6: Escribir el test que falla del parseo del envoltorio en `reasoning`**

`_ejecutar_claude` es la única función que cambia de contrato: ahora corre `claude -p --output-format json`, parsea el envoltorio, registra el `usage` y devuelve **solo** el texto de `result`. Se testea mockeando `subprocess.run`.

```python
# tests/test_reasoning.py — agregar
import json
from types import SimpleNamespace

from gestion_causas import reasoning


class TestEjecutarClaude:
    def _correr_falso(self, salida_stdout, returncode=0):
        def correr(argv, **kwargs):
            self.argv = argv
            return SimpleNamespace(returncode=returncode, stdout=salida_stdout, stderr="")
        return correr

    def test_devuelve_solo_el_texto_de_result(self, monkeypatch, tmp_path):
        envoltorio = json.dumps({
            "type": "result", "is_error": False, "result": '{"ok": true}',
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 100, "output_tokens": 5,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        })
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso(envoltorio))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        assert reasoning._ejecutar_claude("prompt") == '{"ok": true}'
        assert "--output-format" in self.argv
        assert "json" in self.argv

    def test_registra_el_usage_de_la_llamada(self, monkeypatch, tmp_path):
        ruta_uso = tmp_path / "uso.jsonl"
        envoltorio = json.dumps({
            "type": "result", "is_error": False, "result": "{}",
            "total_cost_usd": 0.02,
            "usage": {"input_tokens": 1234, "output_tokens": 7,
                      "cache_creation_input_tokens": 88, "cache_read_input_tokens": 99},
        })
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso(envoltorio))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", ruta_uso)

        reasoning._ejecutar_claude("prompt")

        evento = json.loads(ruta_uso.read_text(encoding="utf-8").strip())
        assert evento["input_tokens"] == 1234
        assert evento["cache_creation_input_tokens"] == 88
        assert evento["cache_read_input_tokens"] == 99
        assert evento["costo_usd"] == 0.02

    def test_stdout_que_no_es_json_se_devuelve_tal_cual(self, monkeypatch, tmp_path):
        """Red de seguridad: si una versión del CLI deja de envolver la
        salida, no se pierde la respuesta — se devuelve el stdout crudo y
        `preguntar` la parsea como siempre."""
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso('{"ok": true}'))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        assert reasoning._ejecutar_claude("prompt") == '{"ok": true}'
```

- [x] **Step 7: Escribir el test de `is_error: true` con exit code 0 (Review Focus 1)**

```python
# tests/test_reasoning.py — dentro de TestEjecutarClaude
    def test_is_error_true_con_exit_code_cero_es_un_fallo(self, monkeypatch, tmp_path):
        envoltorio = json.dumps({
            "type": "result", "subtype": "error_max_turns", "is_error": True,
            "result": "Prompt is too long",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso(envoltorio))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        with pytest.raises(RuntimeError, match="Prompt is too long"):
            reasoning._ejecutar_claude("prompt")
```

- [x] **Step 8: Correr los tests para verificar que fallan**

Run: `pytest tests/test_reasoning.py::TestEjecutarClaude -v`
Expected: FAIL — `_ejecutar_claude` todavía no pasa `--output-format json` ni parsea el envoltorio.

- [x] **Step 9: Implementar el parseo del envoltorio en `reasoning.py`**

Agregá el import y la constante arriba del módulo:

```python
from gestion_causas import uso_tokens

_FLAGS_MINIMOS = [
    "--disable-slash-commands", "--setting-sources", "",
    # `--output-format json` devuelve un envoltorio con el `usage` real de
    # la llamada (ver uso_tokens.py). Sin esto no hay forma de saber qué
    # cuesta cada punto de razonamiento — y todo lo que se optimice encima
    # es una estimación a ciegas.
    "--output-format", "json",
]
```

Y reemplazá el tramo final de `_ejecutar_claude` (desde `resultado = subprocess.run(...)`) por:

```python
    resultado = subprocess.run(
        argv,
        input=prompt,
        capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SEGUNDOS, check=False,
    )
    if resultado.returncode != 0:
        detalle = resultado.stderr[:500] or resultado.stdout[:500]
        raise RuntimeError(f"claude -p terminó con código {resultado.returncode}: {detalle}")
    return _desenvolver_salida(resultado.stdout, etiqueta=etiqueta)


def _desenvolver_salida(stdout: str, *, etiqueta: str | None = None) -> str:
    """Parsea el envoltorio de `--output-format json`: registra el `usage` y
    devuelve el texto de `result`.

    Dos casos que NO son "la respuesta del modelo":
    - `is_error: true` con exit code 0 — un rechazo o un prompt demasiado
      largo no siempre sale con código distinto de cero, y sin esto el texto
      del error se devolvería como si fuera la respuesta (y después fallaría
      como "JSON inválido", gatillando el reintento, que lo paga de nuevo).
    - stdout que no es JSON — si una versión del CLI deja de envolver la
      salida, se devuelve el stdout crudo en vez de perder la respuesta.
    """
    try:
        envoltorio = json.loads(stdout)
    except ValueError:
        return stdout
    if not isinstance(envoltorio, dict) or "result" not in envoltorio:
        return stdout

    uso = envoltorio.get("usage") or {}
    uso_tokens.registrar(
        {
            "llamada": etiqueta or "desconocida",
            "input_tokens": uso.get("input_tokens"),
            "output_tokens": uso.get("output_tokens"),
            "cache_creation_input_tokens": uso.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": uso.get("cache_read_input_tokens"),
            "costo_usd": envoltorio.get("total_cost_usd"),
            "modelo": envoltorio.get("model"),
        },
        ruta=uso_tokens.RUTA_USO_TOKENS,
    )

    if envoltorio.get("is_error"):
        raise RuntimeError(f"claude -p devolvió is_error: {str(envoltorio.get('result'))[:500]}")
    return envoltorio["result"]
```

Cambiá la firma a `def _ejecutar_claude(prompt: str, ruta_archivo=None, etiqueta: str | None = None) -> str:` y, en `preguntar`, pasá la etiqueta al ejecutar por defecto solamente (para no romper los `ejecutar_falso(prompt)` de los tests existentes, que reciben un solo argumento):

```python
    ejecutar = ejecutar or functools.partial(_ejecutar_claude, etiqueta=etiqueta)
```

con `etiqueta: str | None = None` como nuevo parámetro keyword-only de `preguntar` e `import functools` arriba. `uso_tokens.registrar` ya no lanza nunca (Review Focus 2), así que no hace falta envolver la llamada acá.

Hacé el mismo cambio en `_ejecutar_claude_skill`: agregá `"--output-format", "json"` a su `argv` y devolvé `_desenvolver_salida(resultado.stdout, etiqueta="minuta-laboral")`. Es la llamada más cara de todas (una skill entera con `Read,Write,Bash` y timeout de 1800s) y hoy no se mide.

- [x] **Step 10: Correr todos los tests**

Run: `pytest -q`
Expected: PASS. Los tests viejos de `TestPreguntar` no se ven afectados: inyectan `ejecutar`, así que nunca pasan por `_ejecutar_claude`.

- [x] **Step 11: Pasar la etiqueta en los 5 call sites**

En cada llamada, agregá `etiqueta=` con el nombre del punto de razonamiento, para que `uso_tokens.resumen()["por_llamada"]` diga dónde se va el gasto:

| Archivo | Función | `etiqueta` |
|---|---|---|
| `fases/smu.py:361` | `_generar_resumen_narrativo` | `"smu.resumen_narrativo"` |
| `fases/smu.py:402` | `_evaluar_ajustes_demanda` | `"smu.ajustes_demanda"` |
| `fases/goteo.py:119` | `_detectar_acuerdo_y_pago` | `"goteo.acuerdo_y_pago"` |
| `fases/agenda.py:88` | `_evaluar_montos_ofrecimiento` | `"agenda.montos_ofrecimiento"` |
| `fases/seguimiento.py:95` | `_clasificar_pedido` | `"seguimiento.clasificar_pedido"` |

Ejemplo:

```python
    return reasoning.preguntar(tarea, contexto, SCHEMA_ACUERDO, etiqueta="goteo.acuerdo_y_pago")
```

- [x] **Step 12: Agregar el JSONL a `.gitignore`**

En `gestion_causas/.gitignore`, bajo "Estado en tiempo de ejecución", agregá:

```
uso_tokens.jsonl
```

- [x] **Step 13: Correr todos los tests y commitear**

Run: `pytest -q`
Expected: PASS

```bash
git add gestion_causas/uso_tokens.py gestion_causas/reasoning.py gestion_causas/.gitignore \
        gestion_causas/fases/smu.py gestion_causas/fases/goteo.py \
        gestion_causas/fases/agenda.py gestion_causas/fases/seguimiento.py \
        tests/test_uso_tokens.py tests/test_reasoning.py
git commit -m "perf(gestion_causas): instrumenta el usage de cada llamada a Claude en un JSONL"
```

---

## Task 2: Corte del scheduler al driver Python

El cambio con más ahorro del plan, y el que menos código nuevo necesita: `orquestador.py` ya hace todo. Lo único que falta es que arme su propio contexto cuando no existe, para que la tarea programada sea un solo comando.

**Files:**
- Modify: `gestion_causas/orquestador.py` (`main`, y una función nueva `_asegurar_contexto`)
- Modify: `gestion_causas/orquestador/SKILL.md` (reescritura completa)
- Modify: `README.md` (tabla de estado de la migración)
- Test: `tests/test_orquestador.py`

**Interfaces:**
- Consumes: `uso_tokens.resumen` (Task 1).
- Produces: `orquestador._asegurar_contexto(ruta_contexto: Path) -> bool` — devuelve `True` si el contexto quedó listo (`contexto["listo"]`), `False` si no.

- [x] **Step 1: Escribir el test que falla de `_asegurar_contexto`**

```python
# tests/test_orquestador.py — agregar
import json

from gestion_causas import orquestador


class TestAsegurarContexto:
    def test_no_hace_nada_si_el_contexto_ya_existe(self, tmp_path, monkeypatch):
        ruta = tmp_path / "_contexto_corrida.json"
        ruta.write_text(json.dumps({"listo": True, "fecha_hoy": "2026-09-20"}), encoding="utf-8")

        llamadas = []
        monkeypatch.setattr(orquestador.cli_mod, "main", lambda argv: llamadas.append(argv) or 0)

        assert orquestador._asegurar_contexto(ruta) is True
        assert llamadas == []

    def test_arma_el_contexto_si_falta(self, tmp_path, monkeypatch):
        ruta = tmp_path / "_contexto_corrida.json"
        llamadas = []

        def main_falso(argv):
            llamadas.append(argv)
            ruta.write_text(json.dumps({"listo": True}), encoding="utf-8")
            return 0

        monkeypatch.setattr(orquestador.cli_mod, "main", main_falso)

        assert orquestador._asegurar_contexto(ruta) is True
        assert llamadas == [["contexto-corrida", "--salida", str(ruta)]]

    def test_devuelve_false_si_contexto_corrida_sale_con_codigo_1(self, tmp_path, monkeypatch):
        ruta = tmp_path / "_contexto_corrida.json"

        def main_falso(argv):
            ruta.write_text(json.dumps({"listo": False}), encoding="utf-8")
            return 1

        monkeypatch.setattr(orquestador.cli_mod, "main", main_falso)

        assert orquestador._asegurar_contexto(ruta) is False
```

- [x] **Step 2: Correr el test para verificar que falla**

Run: `pytest tests/test_orquestador.py::TestAsegurarContexto -v`
Expected: FAIL con `AttributeError: module 'gestion_causas.orquestador' has no attribute '_asegurar_contexto'`

- [x] **Step 3: Implementar `_asegurar_contexto` y reescribir `main`**

En `gestion_causas/orquestador.py`:

```python
def _asegurar_contexto(ruta_contexto: Path = RUTA_CONTEXTO_DEFAULT) -> bool:
    """Arma `_contexto_corrida.json` si no existe (paso 1 del SKILL.md
    viejo), reusando `cli.main` en vez de duplicar `cmd_contexto_corrida`.
    Devuelve si el contexto quedó utilizable (`listo`).

    Con esto la tarea programada es un único comando
    (`python -m gestion_causas.orquestador`) en vez de dos pasos
    encadenados a mano por un agente — que era la última razón por la que
    el SKILL.md seguía necesitando un modelo para orquestar."""
    ruta = Path(ruta_contexto)
    if not ruta.exists():
        cli_mod.main(["contexto-corrida", "--salida", str(ruta)])
    if not ruta.exists():
        return False
    try:
        return bool(json.loads(ruta.read_text(encoding="utf-8")).get("listo"))
    except ValueError:
        return False


def main(argv=None) -> int:
    """Punto de entrada de la tarea programada. Arma el contexto si falta,
    corre las 5 fases, arma y envía el panel, y anota en la bitácora cuántos
    tokens costó la corrida (ver uso_tokens.py).

    Un contexto no listo (Gmail de trabajo o Calendar caídos) NO aborta: es
    exactamente el caso que el paso 1 del SKILL.md viejo mandaba igual, para
    que Nico se entere por el panel de que hay un token que reautorizar.
    `correr()` va a fallar cada fase por su cuenta y el panel las va a
    mostrar en error."""
    if not _asegurar_contexto():
        bitacora_mod.registrar(
            "Orquestador: contexto de corrida no listo (token caído) — se corre igual "
            "para que el panel avise"
        )

    antes = uso_tokens.resumen()
    resultado = correr_y_enviar_panel()
    despues = uso_tokens.resumen()

    resultado["uso_tokens"] = {
        "llamadas": despues["llamadas"] - antes["llamadas"],
        "input_tokens": despues["input_tokens"] - antes["input_tokens"],
        "output_tokens": despues["output_tokens"] - antes["output_tokens"],
        "cache_creation_input_tokens": (
            despues["cache_creation_input_tokens"] - antes["cache_creation_input_tokens"]
        ),
        "cache_read_input_tokens": (
            despues["cache_read_input_tokens"] - antes["cache_read_input_tokens"]
        ),
        "costo_usd": round(despues["costo_usd"] - antes["costo_usd"], 4),
    }
    uso = resultado["uso_tokens"]
    bitacora_mod.registrar(
        f"Orquestador: corrida terminada — {uso['llamadas']} llamadas a Claude, "
        f"{uso['input_tokens']} tokens de entrada, {uso['output_tokens']} de salida, "
        f"USD {uso['costo_usd']}"
    )

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0
```

Agregá `from gestion_causas import uso_tokens` a los imports.

- [x] **Step 4: Correr los tests**

Run: `pytest tests/test_orquestador.py -v`
Expected: PASS

- [x] **Step 5: Reescribir `gestion_causas/orquestador/SKILL.md`**

Reemplazá el archivo entero (hoy 191 líneas que documentan el despacho de 5 subagentes, arquitectura que `orquestador.py` ya reemplazó) por:

```markdown
---
name: gestion-causas-orquestador
description: Corre el ciclo completo de gestión de causas (contexto de la corrida, las 5 fases, panel de estado por correo) invocando el driver Python
---

Tarea programada desatendida (sin usuario presente). Es un único comando:

```
python -m gestion_causas.orquestador
```

con `Actualizador de informes` como directorio de trabajo.

Eso arma el contexto de la corrida si falta (fecha, estado de los 3 tokens sin
login interactivo, cache de calendario, mapa de hilos, mapa de audiencias),
corre las 5 fases (`calendario`, `smu`, `goteo`, `agenda`, `seguimiento` — las
dos primeras solo en la corrida de la mañana según el campo `corrida`), arma el
panel de estado y lo envía a nmunoz@gomezyriesco.cl desde la cuenta personal.
Imprime el resumen de la corrida como JSON, incluido lo que costó en tokens.

**No despaches subagentes.** Las 5 fases están migradas a Python puro
(`gestion_causas/fases/*.py`) y Claude se invoca solo desde `reasoning.py`, en
los ~5 puntos que de verdad requieren razonamiento sobre texto libre. El flujo
viejo de 6 agentes (1 orquestador + 5 subagentes leyendo
`gestion_causas/subagentes/*.md`) costaba entre 10 y 20 veces más tokens por
corrida y ya no se usa. Esos `.md` se conservan solo como referencia histórica
de las reglas de negocio.

Si el comando sale con código distinto de 0, o imprime fases en error, no
reintentes: el panel ya se envió (o ya quedó anotado en la bitácora por qué no)
y la corrida siguiente vuelve a intentar lo que quedó pendiente.

Diseño: `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md`.
Historial de la migración: `docs/superpowers/plans/`.
```

Borrá también la nota de "Copia versionada" que abría el archivo viejo: ya no hay dos copias que sincronizar a mano, porque el contenido dejó de ser un procedimiento y pasó a ser un comando.

- [x] **Step 6: Actualizar la tabla del `README.md`**

Reemplazá el párrafo que dice "Las 5 fases están migradas. La tarea programada real (`gestion-causas-orquestador`) todavía corre el flujo viejo de subagentes — el corte a este driver es una decisión pendiente." por:

```markdown
Las 5 fases están migradas y la tarea programada corre este driver
(`python -m gestion_causas.orquestador`, ver `gestion_causas/orquestador/SKILL.md`).
`gestion_causas/subagentes/*.md` se conservan como referencia histórica de las
reglas de negocio de cada fase — ya no los ejecuta nadie.
```

- [x] **Step 7: Correr todos los tests y commitear**

Run: `pytest -q`
Expected: PASS

```bash
git add gestion_causas/orquestador.py gestion_causas/orquestador/SKILL.md README.md tests/test_orquestador.py
git commit -m "perf(gestion_causas): la tarea programada corre el driver Python en vez de 6 subagentes"
```

- [ ] **Step 8: Paso manual para Nico (fuera del repo)**

El `SKILL.md` que lee el planificador vive en `C:\Users\usuario\.claude\scheduled-tasks\gestion-causas-orquestador\SKILL.md`, fuera de este repo. Hay que copiar ahí la versión nueva:

```powershell
Copy-Item "Actualizador de informes\gestion_causas\orquestador\SKILL.md" `
          "$env:USERPROFILE\.claude\scheduled-tasks\gestion-causas-orquestador\SKILL.md" -Force
```

Antes de la primera corrida programada, probá el comando a mano una vez y comparalo con una corrida del flujo viejo:

```powershell
python -m gestion_causas.orquestador
```

Revisá que el panel llegue por correo y que el JSON impreso traiga las 5 fases con `titular` (no con `error`). El campo `uso_tokens` del JSON es la medición contra la cual se comparan las tasks 3-5.

---

## Task 3: Caché de razonamiento entre corridas

Con 3 corridas diarias y `mapa_hilos` trayendo el hilo completo cada vez, el mismo prompt se paga 3 veces por día mientras el hilo no cambie.

**Files:**
- Create: `gestion_causas/cache_razonamiento.py`
- Create: `tests/test_cache_razonamiento.py`
- Modify: `gestion_causas/reasoning.py` (`preguntar`)
- Modify: `gestion_causas/fases/goteo.py` (`_detectar_acuerdo_y_pago`)
- Modify: `gestion_causas/fases/seguimiento.py` (`_clasificar_pedido`)
- Modify: `gestion_causas/.gitignore`
- Test: `tests/test_reasoning.py`

**Interfaces:**
- Consumes: `uso_tokens` (Task 1), `reasoning.preguntar(..., etiqueta=...)` (Task 1).
- Produces:
  - `cache_razonamiento.clave(tarea: str, contexto: dict) -> str` (sha256 hex)
  - `cache_razonamiento.obtener(clave: str, ruta: Path = RUTA_CACHE) -> dict | None`
  - `cache_razonamiento.guardar(clave: str, resultado: dict, ruta: Path = RUTA_CACHE) -> None`
  - `cache_razonamiento.RUTA_CACHE: Path`, `cache_razonamiento.DIAS_VIGENCIA: int`
  - `reasoning.preguntar(..., cachear: bool = False)`

- [x] **Step 1: Escribir los tests que fallan del módulo de caché**

```python
# tests/test_cache_razonamiento.py
import json
from datetime import datetime, timedelta

from gestion_causas import cache_razonamiento as cache


class TestClave:
    def test_el_mismo_contexto_da_la_misma_clave(self):
        a = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}]})
        b = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}]})
        assert a == b

    def test_el_orden_de_las_claves_del_dict_no_cambia_la_clave(self):
        a = cache.clave("tarea", {"x": 1, "y": 2})
        b = cache.clave("tarea", {"y": 2, "x": 1})
        assert a == b

    def test_un_mensaje_nuevo_cambia_la_clave(self):
        a = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}]})
        b = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}, {"cuerpo": "chau"}]})
        assert a != b

    def test_una_tarea_distinta_cambia_la_clave(self):
        assert cache.clave("tarea A", {"x": 1}) != cache.clave("tarea B", {"x": 1})


class TestObtenerYGuardar:
    def test_devuelve_lo_guardado(self, tmp_path):
        ruta = tmp_path / "cache.json"
        cache.guardar("abc", {"acuerdo_cerrado": True}, ruta=ruta)
        assert cache.obtener("abc", ruta=ruta) == {"acuerdo_cerrado": True}

    def test_devuelve_none_si_la_clave_no_esta(self, tmp_path):
        assert cache.obtener("no-existe", ruta=tmp_path / "cache.json") is None

    def test_una_entrada_vencida_no_se_devuelve(self, tmp_path):
        ruta = tmp_path / "cache.json"
        viejo = (datetime.now() - timedelta(days=cache.DIAS_VIGENCIA + 1)).isoformat()
        ruta.write_text(
            json.dumps({"abc": {"guardado_en": viejo, "resultado": {"x": 1}}}),
            encoding="utf-8",
        )
        assert cache.obtener("abc", ruta=ruta) is None

    def test_guardar_poda_las_entradas_vencidas(self, tmp_path):
        ruta = tmp_path / "cache.json"
        viejo = (datetime.now() - timedelta(days=cache.DIAS_VIGENCIA + 1)).isoformat()
        ruta.write_text(
            json.dumps({"vieja": {"guardado_en": viejo, "resultado": {"x": 1}}}),
            encoding="utf-8",
        )

        cache.guardar("nueva", {"y": 2}, ruta=ruta)

        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        assert "vieja" not in contenido
        assert "nueva" in contenido
```

- [x] **Step 2: Escribir el test de archivo corrupto (Review Focus 4)**

```python
# tests/test_cache_razonamiento.py — agregar
class TestArchivoCorrupto:
    def test_obtener_degrada_a_none_si_el_json_esta_roto(self, tmp_path):
        ruta = tmp_path / "cache.json"
        ruta.write_text('{"abc": {"guardado_en"', encoding="utf-8")
        assert cache.obtener("abc", ruta=ruta) is None

    def test_guardar_reescribe_el_archivo_si_el_json_esta_roto(self, tmp_path):
        ruta = tmp_path / "cache.json"
        ruta.write_text('{"abc": {"guardado_en"', encoding="utf-8")

        cache.guardar("nueva", {"y": 2}, ruta=ruta)

        assert json.loads(ruta.read_text(encoding="utf-8"))["nueva"]["resultado"] == {"y": 2}
```

- [x] **Step 3: Correr los tests para verificar que fallan**

Run: `pytest tests/test_cache_razonamiento.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.cache_razonamiento'`

- [x] **Step 4: Escribir `cache_razonamiento.py`**

```python
"""Caché de respuestas de razonamiento entre corridas.

El orquestador corre 3 veces al día y `cli._generar_mapa_hilos_por_rit`
guarda TODOS los mensajes de cada hilo activo (no solo los nuevos), así que
una causa cuyo hilo no cambió produce un prompt idéntico byte por byte en
las 3 corridas. Este módulo cachea el resultado por hash del par
(tarea, contexto): si el prompt es el mismo, la respuesta también, y no hay
que volver a pagarla.

La clave se calcula sobre el contenido real que se le manda al modelo, no
sobre un identificador externo (thread_id, RIT): así un mensaje nuevo en el
hilo, un cambio en el texto de la tarea o un ítem agregado al pedido
invalidan la entrada solos, sin que ningún llamador tenga que acordarse de
invalidarla a mano.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from gestion_causas.registro import _lock

RUTA_CACHE = Path(__file__).parent / "cache_razonamiento.json"

# Una respuesta sobre un hilo que no cambió sigue siendo válida
# indefinidamente (la clave ya depende del contenido), pero el archivo no
# puede crecer para siempre: 30 días cubre de sobra el ciclo de vida de una
# causa activa en goteo/seguimiento.
DIAS_VIGENCIA = 30


def clave(tarea: str, contexto: dict) -> str:
    """sha256 del par (tarea, contexto). `sort_keys=True` para que el orden
    en que un llamador arme el dict no produzca claves distintas para el
    mismo contenido."""
    material = json.dumps(
        {"tarea": tarea, "contexto": contexto},
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cargar(ruta: Path) -> dict:
    """Un caché ilegible (JSON truncado por una corrida interrumpida) se
    trata como caché vacío: se pierde el ahorro de esa corrida, nunca la
    corrida."""
    try:
        contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return contenido if isinstance(contenido, dict) else {}


def _vigente(entrada: dict) -> bool:
    try:
        guardado = datetime.fromisoformat(entrada["guardado_en"])
    except (KeyError, TypeError, ValueError):
        return False
    return datetime.now() - guardado <= timedelta(days=DIAS_VIGENCIA)


def obtener(clave_buscada: str, ruta: Path = RUTA_CACHE) -> dict | None:
    """La respuesta cacheada, o None si no está, venció o el archivo no se
    puede leer."""
    entrada = _cargar(ruta).get(clave_buscada)
    if not isinstance(entrada, dict) or not _vigente(entrada):
        return None
    resultado = entrada.get("resultado")
    return resultado if isinstance(resultado, dict) else None


def guardar(clave_nueva: str, resultado: dict, ruta: Path = RUTA_CACHE) -> None:
    """Guarda `resultado` y poda de paso las entradas vencidas. Nunca lanza:
    no poder cachear es perder el ahorro de la próxima corrida, no un motivo
    para tumbar esta."""
    try:
        with _lock(Path(ruta)):
            contenido = {
                k: v for k, v in _cargar(ruta).items()
                if isinstance(v, dict) and _vigente(v)
            }
            contenido[clave_nueva] = {
                "guardado_en": datetime.now().isoformat(),
                "resultado": resultado,
            }
            Path(ruta).write_text(
                json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception:  # noqa: BLE001 - el caché nunca tumba una corrida
        pass
```

- [x] **Step 5: Escribir los tests que fallan del `cachear=True` en `preguntar` (Review Focus 3)**

```python
# tests/test_reasoning.py — agregar
from gestion_causas import cache_razonamiento


class TestPreguntarConCache:
    def test_la_segunda_llamada_identica_no_invoca_a_claude(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cache_razonamiento, "RUTA_CACHE", tmp_path / "cache.json")
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        primera = preguntar("tarea", {"x": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso, cachear=True)
        segunda = preguntar("tarea", {"x": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso, cachear=True)

        assert primera == segunda == {"ok": True}
        assert len(llamadas) == 1

    def test_un_contexto_distinto_si_invoca_a_claude(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cache_razonamiento, "RUTA_CACHE", tmp_path / "cache.json")
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        preguntar("tarea", {"x": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso, cachear=True)
        preguntar("tarea", {"x": 2}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso, cachear=True)

        assert len(llamadas) == 2

    def test_sin_cachear_no_se_consulta_ni_se_guarda_el_cache(self, monkeypatch, tmp_path):
        ruta = tmp_path / "cache.json"
        monkeypatch.setattr(cache_razonamiento, "RUTA_CACHE", ruta)
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        preguntar("tarea", {"x": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)
        preguntar("tarea", {"x": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert len(llamadas) == 2
        assert not ruta.exists()

    def test_un_error_nunca_entra_al_cache(self, monkeypatch, tmp_path):
        """Si se cacheara un fallo, la causa quedaría envenenada por
        DIAS_VIGENCIA y dejaría de evaluarse en cada corrida."""
        monkeypatch.setattr(cache_razonamiento, "RUTA_CACHE", tmp_path / "cache.json")
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return "esto no es JSON"

        primera = preguntar("tarea", {"x": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso, cachear=True)
        assert "error" in primera

        llamadas.clear()

        def ejecutar_bueno(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        segunda = preguntar("tarea", {"x": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_bueno, cachear=True)
        assert segunda == {"ok": True}
        assert len(llamadas) == 1
```

- [x] **Step 6: Correr los tests para verificar que fallan**

Run: `pytest tests/test_reasoning.py::TestPreguntarConCache -v`
Expected: FAIL con `TypeError: preguntar() got an unexpected keyword argument 'cachear'`

- [x] **Step 7: Implementar `cachear` en `preguntar`**

En `gestion_causas/reasoning.py`, agregá `from gestion_causas import cache_razonamiento` y cambiá la firma y el cuerpo de `preguntar`:

```python
def preguntar(
    tarea: str, contexto: dict, schema: dict, *, ejecutar=None, ruta_archivo=None,
    etiqueta: str | None = None, cachear: bool = False,
) -> dict:
```

Justo después de `ejecutar = ejecutar or functools.partial(_ejecutar_claude, etiqueta=etiqueta)`:

```python
    # El caché se consulta ANTES de armar el prompt: la clave depende de
    # (tarea, contexto), no del prompt final, para que agregar un campo al
    # formato del prompt (ej. la línea de `ruta_archivo`) no invalide todo
    # el caché de golpe.
    clave_cache = cache_razonamiento.clave(tarea, contexto) if cachear else None
    if clave_cache is not None:
        cacheado = cache_razonamiento.obtener(clave_cache, ruta=cache_razonamiento.RUTA_CACHE)
        if cacheado is not None:
            return cacheado
```

Y en el `return resultado` del loop (cuando `_parsear_json` devolvió algo):

```python
        resultado = _parsear_json(salida)
        if resultado is not None:
            # Nunca se cachea un `{"error": ...}`: una entrada así
            # envenenaría la causa por DIAS_VIGENCIA. Solo llegan acá
            # respuestas que parsearon bien, pero el modelo puede haber
            # devuelto un objeto con la clave "error" por su cuenta.
            if clave_cache is not None and "error" not in resultado:
                cache_razonamiento.guardar(
                    clave_cache, resultado, ruta=cache_razonamiento.RUTA_CACHE
                )
            return resultado
```

El `return {"error": ...}` del final (tras los 2 intentos fallidos) no toca el caché, así que no hay que cambiarlo.

- [x] **Step 8: Correr los tests**

Run: `pytest tests/test_reasoning.py -v`
Expected: PASS

- [x] **Step 9: Activar el caché en los dos call sites repetitivos**

En `gestion_causas/fases/goteo.py`, `_detectar_acuerdo_y_pago`:

```python
    resultado = reasoning.preguntar(
        tarea, contexto, SCHEMA_ACUERDO, etiqueta="goteo.acuerdo_y_pago", cachear=True
    )
```

En `gestion_causas/fases/seguimiento.py`, `_clasificar_pedido`:

```python
    return reasoning.preguntar(
        tarea, contexto, SCHEMA_CLASIFICAR_PEDIDO,
        etiqueta="seguimiento.clasificar_pedido", cachear=True,
    )
```

**No** se activa en `smu.py` ni en `agenda.py`: esas 4 llamadas corren una sola vez por causa nueva (alta, u ofrecimiento a 4 días hábiles de la audiencia), así que no hay repetición que ahorrar, y dos de ellas dependen del contenido de un PDF que la clave no ve (`ruta_archivo` no entra en el contexto).

- [x] **Step 10: Agregar el caché a `.gitignore`**

En `gestion_causas/.gitignore`, bajo "Estado en tiempo de ejecución":

```
cache_razonamiento.json
```

- [x] **Step 11: Correr todos los tests y commitear**

Run: `pytest -q`
Expected: PASS

```bash
git add gestion_causas/cache_razonamiento.py gestion_causas/reasoning.py \
        gestion_causas/fases/goteo.py gestion_causas/fases/seguimiento.py \
        gestion_causas/.gitignore tests/test_cache_razonamiento.py tests/test_reasoning.py
git commit -m "perf(gestion_causas): cachea el razonamiento entre corridas por hash del contexto"
```

---

## Task 4: Acotar el contexto de `goteo`

**Files:**
- Modify: `gestion_causas/fases/goteo.py:34` (`LIMITE_CONTEXTO_CHARS`) y `_acotar_mensajes_por_tamano`
- Test: `tests/fases/test_goteo.py`

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces: `goteo._acotar_mensajes_por_tamano(mensajes: list[dict], limite: int) -> bool` — misma firma, misma semántica de retorno (si hubo truncado), pero descarta mensajes enteros desde el más antiguo en vez de recortar caracteres.

- [x] **Step 1: Escribir los tests que fallan del truncado por mensaje entero**

```python
# tests/fases/test_goteo.py — agregar
from gestion_causas.fases import goteo


class TestAcotarMensajesPorTamano:
    def test_no_trunca_si_entra_en_el_limite(self):
        mensajes = [{"cuerpo": "a" * 10}, {"cuerpo": "b" * 10}]
        assert goteo._acotar_mensajes_por_tamano(mensajes, 100) is False
        assert len(mensajes) == 2

    def test_descarta_los_mensajes_mas_antiguos_enteros(self):
        """Los mensajes vienen en orden cronológico ascendente. Se descartan
        desde el principio, sin partir ninguno al medio."""
        mensajes = [{"cuerpo": "viejo" * 10}, {"cuerpo": "medio" * 10}, {"cuerpo": "nuevo" * 10}]

        assert goteo._acotar_mensajes_por_tamano(mensajes, 100) is True

        assert len(mensajes) == 2
        assert mensajes[0]["cuerpo"].startswith("medio")
        assert mensajes[-1]["cuerpo"].startswith("nuevo")

    def test_conserva_el_ultimo_mensaje_aunque_solo_el_ya_exceda(self):
        """Un hilo cuyo único mensaje reciente ya supera el límite no puede
        quedar en una lista vacía: se le preguntaría a Claude sobre la nada.
        Se manda ese mensaje recortado por el principio."""
        mensajes = [{"cuerpo": "x" * 500}]

        assert goteo._acotar_mensajes_por_tamano(mensajes, 100) is True

        assert len(mensajes) == 1
        assert len(mensajes[0]["cuerpo"]) == 100
        assert mensajes[0]["cuerpo"] == "x" * 100

    def test_el_limite_por_defecto_es_acotado(self):
        assert goteo.LIMITE_CONTEXTO_CHARS == 40_000
```

- [x] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/fases/test_goteo.py::TestAcotarMensajesPorTamano -v`
Expected: FAIL — el truncado actual recorta caracteres del principio de cada mensaje sin descartar ninguno, y `LIMITE_CONTEXTO_CHARS` es `400_000`.

- [x] **Step 3: Implementar el truncado por mensaje entero**

Reemplazá la constante y la función en `gestion_causas/fases/goteo.py`:

```python
# Cota del contexto que le mandamos a claude -p por causa. Era 400_000
# (~100k tokens en UNA llamada, por causa, por corrida) cuando su único
# propósito era que un hilo de 29 mensajes (~800KB) no hiciera fallar la
# llamada con "Prompt is too long". Pero la pregunta que hacemos acá
# ("¿se cerró un acuerdo? ¿hay comprobante de pago?") se responde con los
# mensajes recientes: el historial viejo solo agrega costo. Con
# `_quitar_texto_citado` ya sacando el historial repetido de cada
# respuesta, 40k caracteres (~10k tokens) cubren de sobra los últimos
# mensajes reales de un hilo.
LIMITE_CONTEXTO_CHARS = 40_000


def _acotar_mensajes_por_tamano(mensajes: list[dict], limite: int) -> bool:
    """Si la suma de las longitudes de `cuerpo` en `mensajes` supera
    `limite`, descarta mensajes ENTEROS desde el principio (se asume orden
    cronológico ascendente, más antiguos primero) hasta bajar del límite.
    Muta `mensajes` in place. Devuelve si hubo truncado.

    Antes esto recortaba caracteres (`cuerpo[recorte:]`), lo que partía un
    mensaje al medio y dejaba un fragmento sin su encabezado — peor insumo
    para el modelo que no tener ese mensaje.

    El último mensaje nunca se descarta: si solo él ya excede el límite, se
    recorta su cuerpo por el principio (conservando el final, que es la
    parte nueva). Quedarse con una lista vacía sería preguntarle a Claude
    sobre la nada."""
    if sum(len(m["cuerpo"]) for m in mensajes) <= limite or not mensajes:
        return False

    while len(mensajes) > 1 and sum(len(m["cuerpo"]) for m in mensajes) > limite:
        mensajes.pop(0)

    if len(mensajes[0]["cuerpo"]) > limite:
        mensajes[0]["cuerpo"] = mensajes[0]["cuerpo"][-limite:]

    return True
```

- [x] **Step 4: Correr los tests**

Run: `pytest tests/fases/test_goteo.py -v`
Expected: PASS. Si algún test existente asumía el recorte por caracteres, actualizalo al comportamiento nuevo (descarte de mensajes enteros) — el aviso `_accion_contexto_truncado` que ve Nico no cambia.

- [x] **Step 5: Correr todos los tests y commitear**

Run: `pytest -q`
Expected: PASS

```bash
git add gestion_causas/fases/goteo.py tests/fases/test_goteo.py
git commit -m "perf(gestion_causas): goteo acota el contexto a 40k y trunca por mensaje entero"
```

---

## Task 5: Selección de modelo por llamada

**Files:**
- Modify: `gestion_causas/reasoning.py` (constantes de modelo, `preguntar`, `_ejecutar_claude`)
- Modify: `gestion_causas/fases/goteo.py` (`_detectar_acuerdo_y_pago`)
- Modify: `gestion_causas/fases/seguimiento.py` (`_clasificar_pedido`)
- Modify: `README.md` (sección de variables de entorno)
- Test: `tests/test_reasoning.py`

**Interfaces:**
- Consumes: `reasoning.preguntar(..., etiqueta=..., cachear=...)` (Tasks 1 y 3).
- Produces:
  - `reasoning.MODELO_CLASIFICACION: str` — id del modelo para clasificaciones acotadas, o `""` para el default del CLI.
  - `reasoning.preguntar(..., modelo: str | None = None)`

- [x] **Step 1: Escribir los tests que fallan**

```python
# tests/test_reasoning.py — dentro de TestEjecutarClaude
    def test_pasa_el_modelo_cuando_se_indica(self, monkeypatch, tmp_path):
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso("{}"))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        reasoning._ejecutar_claude("prompt", modelo="claude-haiku-4-5-20251001")

        assert "--model" in self.argv
        assert self.argv[self.argv.index("--model") + 1] == "claude-haiku-4-5-20251001"

    def test_no_pasa_model_si_el_modelo_es_vacio(self, monkeypatch, tmp_path):
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso("{}"))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        reasoning._ejecutar_claude("prompt", modelo="")

        assert "--model" not in self.argv
```

- [x] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_reasoning.py::TestEjecutarClaude -v`
Expected: FAIL con `TypeError: _ejecutar_claude() got an unexpected keyword argument 'modelo'`

- [x] **Step 3: Implementar la selección de modelo**

En `gestion_causas/reasoning.py`, agregá `import os` y, junto a `_FLAGS_MINIMOS`:

```python
# Modelo para las clasificaciones acotadas (`goteo.acuerdo_y_pago`,
# `seguimiento.clasificar_pedido`): devuelven 2-3 campos con un schema fijo
# sobre texto corto, no hace falta el modelo más caro. Las que SÍ lo
# necesitan (leer una demanda escaneada en modo visión y extraer montos
# exactos: `smu.ajustes_demanda`, `agenda.montos_ofrecimiento`) no pasan
# `modelo` y siguen con el default del CLI.
#
# Vacío ("") = default del CLI. Se puede forzar por entorno sin tocar
# código, para comparar calidad/costo contra los números de uso_tokens.py:
#   GESTION_CAUSAS_MODELO_CLASIFICACION=""  -> vuelve al default
MODELO_CLASIFICACION = os.environ.get(
    "GESTION_CAUSAS_MODELO_CLASIFICACION", "claude-haiku-4-5-20251001"
)
```

En `_ejecutar_claude`, agregá el parámetro y el flag:

```python
def _ejecutar_claude(prompt: str, ruta_archivo=None, etiqueta: str | None = None,
                     modelo: str | None = None) -> str:
```

y justo después de `argv = [ejecutable, "-p", *_FLAGS_MINIMOS]`:

```python
    if modelo:
        argv += ["--model", modelo]
```

En `preguntar`, agregá `modelo: str | None = None` a la firma y pasalo al partial:

```python
    ejecutar = ejecutar or functools.partial(_ejecutar_claude, etiqueta=etiqueta, modelo=modelo)
```

Un id de modelo inválido hace que `claude -p` salga con código distinto de cero, lo que `_ejecutar_claude` ya convierte en `RuntimeError`, que `preguntar` ya atrapa y devuelve como `{"error": ...}` — la fase sigue con la causa siguiente y el aviso llega a `acciones`. No hace falta validar el id.

- [x] **Step 4: Correr los tests**

Run: `pytest tests/test_reasoning.py -v`
Expected: PASS

- [x] **Step 5: Pasar el modelo en los dos call sites de clasificación**

En `gestion_causas/fases/goteo.py`, `_detectar_acuerdo_y_pago`:

```python
    resultado = reasoning.preguntar(
        tarea, contexto, SCHEMA_ACUERDO, etiqueta="goteo.acuerdo_y_pago",
        cachear=True, modelo=reasoning.MODELO_CLASIFICACION,
    )
```

En `gestion_causas/fases/seguimiento.py`, `_clasificar_pedido`:

```python
    return reasoning.preguntar(
        tarea, contexto, SCHEMA_CLASIFICAR_PEDIDO,
        etiqueta="seguimiento.clasificar_pedido", cachear=True,
        modelo=reasoning.MODELO_CLASIFICACION,
    )
```

`smu._generar_resumen_narrativo` queda con el default a propósito: redacta el párrafo que va al Excel de Juicios Vigentes que lee una persona, siguiendo una plantilla estricta. Es candidato a bajar de modelo, pero recién con los números de `uso_tokens.py` en la mano y comparando la redacción contra corridas anteriores.

- [x] **Step 6: Documentar la variable de entorno en el `README.md`**

En la sección "Credenciales y estado en tiempo de ejecución", agregá una subsección:

```markdown
### Variables de entorno opcionales

- `GESTION_CAUSAS_MODELO_CLASIFICACION` — modelo que usan las dos
  clasificaciones acotadas (`goteo.acuerdo_y_pago`,
  `seguimiento.clasificar_pedido`). Por defecto `claude-haiku-4-5-20251001`;
  ponela en vacío (`""`) para volver al modelo por defecto del CLI. Las
  llamadas que leen un PDF de demanda siempre usan el default.

El consumo real de cada llamada queda en `gestion_causas/uso_tokens.jsonl`
(una línea JSON por llamada). Para verlo sumado:

```bash
python -c "from gestion_causas import uso_tokens; import json; print(json.dumps(uso_tokens.resumen(), indent=2))"
```
```

- [x] **Step 7: Correr todos los tests y commitear**

Run: `pytest -q`
Expected: PASS

```bash
git add gestion_causas/reasoning.py gestion_causas/fases/goteo.py \
        gestion_causas/fases/seguimiento.py README.md tests/test_reasoning.py
git commit -m "perf(gestion_causas): las clasificaciones acotadas corren en un modelo más barato"
```

---

## Validación final (después de las 5 tasks)

- [x] **Step 1: Suite completa**

Run: `pytest -q`
Expected: PASS, sin tests salteados que antes corrían.

- [ ] **Step 2: Corrida real y comparación**

En la máquina de Nico, con las credenciales provisionadas:

```powershell
python -m gestion_causas.orquestador
```

Comprobá, contra la corrida de control de la Task 2 Step 8:
- el panel llega por correo con las mismas 5 fases y los mismos `titular`;
- el campo `uso_tokens` del JSON impreso bajó respecto de la corrida de control;
- `gestion_causas/uso_tokens.jsonl` tiene una línea por llamada, con `por_llamada` mostrando dónde se concentra el gasto.

- [ ] **Step 3: Segunda corrida el mismo día (verificación del caché)**

Volvé a correr el comando sin esperar a que cambie nada en Gmail. `uso_tokens` de la segunda corrida debería mostrar **menos llamadas** que la primera: las de `goteo.acuerdo_y_pago` y `seguimiento.clasificar_pedido` sobre hilos sin cambios ahora salen del caché. Si el número de llamadas es idéntico, el caché no está pegando — revisá que `cache_razonamiento.json` se haya creado y que las claves no estén cambiando entre corridas (el sospechoso sería algún campo con timestamp colándose en el `contexto`).
