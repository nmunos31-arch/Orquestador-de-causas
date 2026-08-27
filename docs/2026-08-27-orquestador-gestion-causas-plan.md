# Orquestador único para el ciclo de gestión de causas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar las 4 tareas programadas del ciclo de gestión de causas (`gestion-causas-calendario`, `gestion-causas-smu`, `gestion-causas-goteo`, `gestion-causas-agenda`) por una sola tarea programada (`gestion-causas-orquestador`) que despacha las 4 fases como subagentes secuenciales aislados y, al terminar, arma y envía por correo un panel HTML con el estado completo del ciclo.

**Architecture:** Se agregan dos piezas de código nuevas al paquete `gestion_causas/` (una función de envío acotada en `gmail_client.py` y un módulo `panel.py` que arma el HTML a partir de `registro_causas.json`), expuestas por dos subcomandos nuevos del CLI (`panel-html`, `enviar-panel`). El contenido de las 4 `SKILL.md` actuales se migra casi textual a 4 archivos de prompt (`gestion_causas/subagentes/*.md`) que el `SKILL.md` del orquestador despacha con la herramienta Agent, en orden fijo, capturando el resultado de cada uno para el panel. Las 4 tareas antiguas quedan desactivadas, no borradas.

**Tech Stack:** Python 3.14 (paquete `gestion_causas`), pytest, argparse, Gmail API (google-api-python-client), Claude Code scheduled tasks + herramienta Agent.

**Spec:** [docs/2026-08-27-orquestador-gestion-causas-design.md](2026-08-27-orquestador-gestion-causas-design.md)

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `gestion_causas/gmail_client.py` (modificar) | Agrega `enviar_panel_estado()` — única función que puede enviar correo, destinatario fijo. |
| `gestion_causas/panel.py` (crear) | Calcula el estado de cada causa a partir del registro y arma el HTML del panel. Sin efectos secundarios (no toca Gmail ni red). |
| `gestion_causas/cli.py` (modificar) | Agrega subcomandos `panel-html` y `enviar-panel`. |
| `gestion_causas/subagentes/calendario.md` (crear) | Prompt de la Fase 0, migrado de la tarea `gestion-causas-calendario`, con autoevaluación de turno (solo lunes). |
| `gestion_causas/subagentes/smu.md` (crear) | Prompt de las Fases 1-2, migrado de `gestion-causas-smu`. |
| `gestion_causas/subagentes/goteo.md` (crear) | Prompt de la Fase 3, migrado de `gestion-causas-goteo`. |
| `gestion_causas/subagentes/agenda.md` (crear) | Prompt de las Fases 4-6, migrado de `gestion-causas-agenda`. |
| Tarea programada `gestion-causas-orquestador` (crear vía MCP) | Orquesta el despacho secuencial de los 4 subagentes y el envío del panel. |
| `tests/test_gmail_client.py` (modificar) | Ajusta la garantía de no-envío para permitir la excepción acotada. |
| `tests/test_panel.py` (crear) | Cubre `estado_causas()` y `generar_panel_html()`. |
| `tests/test_cli.py` (modificar) | Cubre `panel-html` y `enviar-panel`. |

---

### Task 1: `enviar_panel_estado` en `gmail_client.py`

**Files:**
- Modify: `Actualizador de informes/gestion_causas/gmail_client.py`
- Test: `Actualizador de informes/tests/test_gmail_client.py`

- [ ] **Step 1: Escribe los tests que fallan**

Reemplaza el método `test_no_hay_funciones_de_envio` existente (líneas 14-19 de `tests/test_gmail_client.py`) para que permita explícitamente la única función de envío acotada:

```python
    def test_no_hay_funciones_de_envio(self):
        nombres = [n for n, _ in inspect.getmembers(gmail_client, inspect.isfunction)]
        permitido_envio = {"enviar_panel_estado"}
        prohibidos_envio = {"enviar", "send", "mandar", "responder", "reply"}
        for nombre in nombres:
            if nombre in permitido_envio:
                continue
            partes = set(nombre.lower().replace("_", " ").split())
            assert not (partes & prohibidos_envio), f"Función sospechosa de enviar: {nombre}"
```

Reemplaza `test_codigo_fuente_no_llama_a_drafts_send_ni_messages_send` (líneas 28-33) para que el `messages().send` solo esté permitido dentro de `enviar_panel_estado`:

```python
    def test_codigo_fuente_no_llama_a_drafts_send_ni_messages_send_fuera_del_panel(self):
        fuente_modulo = inspect.getsource(gmail_client)
        fuente_panel = inspect.getsource(gmail_client.enviar_panel_estado)
        fuente_sin_panel = fuente_modulo.replace(fuente_panel, "")
        assert "drafts().send" not in fuente_modulo
        assert ".trash(" not in fuente_modulo
        assert "untrash" not in fuente_modulo
        assert "messages().send" not in fuente_sin_panel
```

Actualiza `test_scopes_son_los_esperados` (líneas 53-60) agregando el nuevo scope:

```python
    def test_scopes_son_los_esperados(self):
        esperados = {
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        }
        assert set(gmail_client.SCOPES) == esperados
```

Agrega una clase nueva al final del archivo (después de `TestScopesMinimos`, antes de `TestExtraccionDeTextoYAdjuntos`):

```python
class TestEnvioAcotadoDelPanel:
    def test_enviar_panel_estado_llama_a_messages_send(self):
        fuente = inspect.getsource(gmail_client.enviar_panel_estado)
        assert "messages().send" in fuente

    def test_enviar_panel_estado_no_acepta_destinatario_arbitrario(self):
        parametros = inspect.signature(gmail_client.enviar_panel_estado).parameters
        assert "destinatario" not in parametros
        assert "to" not in parametros

    def test_enviar_panel_estado_usa_destinatario_fijo(self):
        assert gmail_client.PANEL_DESTINATARIO == "nmunoz@gomezyriesco.cl"

    def test_enviar_panel_estado_rechaza_html_vacio(self):
        import pytest

        with pytest.raises(ValueError):
            gmail_client.enviar_panel_estado("Asunto de prueba", "")
```

- [ ] **Step 2: Corre los tests y verifica que fallan**

Run: `cd "Actualizador de informes" && python -m pytest tests/test_gmail_client.py -v`
Expected: FAIL — `AttributeError: module 'gestion_causas.gmail_client' has no attribute 'enviar_panel_estado'` (y el test de scopes falla porque falta `gmail.send`).

- [ ] **Step 3: Implementa `enviar_panel_estado` y el scope nuevo**

En `gestion_causas/gmail_client.py`, agrega el scope al final de la lista `SCOPES` (líneas 47-52), actualizando el comentario que la precede:

```python
# gmail.modify es necesario para threads().modify() / messages().modify()
# (aplicar la etiqueta de color y la de "procesado" a un hilo) — ver
# GARANTÍA DE SEGURIDAD arriba sobre por qué se pidió pese a ser más amplio
# de lo ideal. Se mantiene además gmail.labels (administración de las
# etiquetas en sí) y gmail.readonly/gmail.compose. Deliberadamente NO se
# pide https://mail.google.com/ (acceso total, incluye enviar sin
# restricciones).
#
# gmail.send se agregó para una única excepción acotada: enviar_panel_estado()
# (ver más abajo), que solo puede mandar el panel de estado del ciclo de
# gestión de causas a nmunoz@gomezyriesco.cl — un correo de auto-reporte, no
# una gestión hacia terceros. El resto del módulo sigue sin poder enviar
# nada (ver GARANTÍA DE SEGURIDAD).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
```

Agrega la constante del destinatario fijo justo debajo de `ETIQUETA_PROCESADO` (línea 75):

```python
ETIQUETA_PROCESADO = "Procesado-GestionCausas"

# Único destinatario permitido de enviar_panel_estado() — ver esa función
# más abajo. No es un parámetro: la garantía de que este módulo no puede
# mandar correo a nadie más queda en el código, no en el llamador.
PANEL_DESTINATARIO = "nmunoz@gomezyriesco.cl"
```

Agrega la función nueva al final del archivo (después de `borrador_existe`, que es la última función del módulo):

```python
def enviar_panel_estado(asunto: str, html: str, servicio=None) -> dict:
    """Envía el panel de estado del ciclo de gestión de causas a
    PANEL_DESTINATARIO (nmunoz@gomezyriesco.cl).

    Única función de este módulo que llama a messages().send — excepción
    acotada y verificada por tests/test_gmail_client.py
    (TestEnvioAcotadoDelPanel): no acepta un destinatario distinto del
    propio Nico (no expone parámetro `destinatario`/`to`), y es un correo
    de auto-reporte a sí mismo, no una gestión hacia terceros. Ver GARANTÍA
    DE SEGURIDAD al inicio del módulo.
    """
    if not html or not html.strip():
        raise ValueError("El panel no puede enviarse vacío")
    if servicio is None:
        servicio = construir_servicio()
    cuerpo_mensaje = _construir_cuerpo_mensaje(
        PANEL_DESTINATARIO, asunto, html, None, True, None
    )
    return servicio.users().messages().send(userId="me", body=cuerpo_mensaje).execute()
```

- [ ] **Step 4: Corre los tests y verifica que pasan**

Run: `cd "Actualizador de informes" && python -m pytest tests/test_gmail_client.py -v`
Expected: PASS (todos los tests, incluidos los 4 nuevos de `TestEnvioAcotadoDelPanel`).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/gmail_client.py" "Actualizador de informes/tests/test_gmail_client.py"
git commit -m "feat(gestion_causas): agregar envio acotado del panel de estado a gmail_client"
```

---

### Task 2: Módulo `panel.py`

**Files:**
- Create: `Actualizador de informes/gestion_causas/panel.py`
- Test: `Actualizador de informes/tests/test_panel.py`

- [ ] **Step 1: Escribe el test que falla**

Crea `tests/test_panel.py`:

```python
import json
from datetime import date
from pathlib import Path

from gestion_causas.panel import estado_causas, generar_panel_html


def _escribir_registro(tmp_path, causas: dict) -> Path:
    ruta = tmp_path / "registro_causas.json"
    ruta.write_text(json.dumps(causas, ensure_ascii=False), encoding="utf-8")
    return ruta


class TestEstadoCausas:
    def test_causa_recien_registrada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas == [{
            "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
            "fase": "Recien registrada", "fecha_audiencia": "",
            "dias_sin_actualizar": 0, "alerta": False,
        }]

    def test_causa_con_demanda_guardada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-2-2026": {
                "rit": "M-2-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Demanda guardada, en curso"

    def test_causa_con_ofrecimiento(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-3-2026": {
                "rit": "M-3-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "oferta_borrador_creado": True,
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Ofrecimiento enviado a Roman"

    def test_causa_con_minuta(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-4-2026": {
                "rit": "M-4-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "oferta_borrador_creado": True,
                "minuta_ejecutada": True, "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Minuta generada"

    def test_causa_cerrada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-5-2026": {
                "rit": "M-5-2026", "empresa": "Alvi", "demandante": "Soto",
                "causa_cerrada": True, "ultima_actualizacion": "2026-01-01T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Cerrada"
        assert filas[0]["alerta"] is False

    def test_alerta_por_dias_sin_actualizar(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-6-2026": {
                "rit": "M-6-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-01T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["dias_sin_actualizar"] == 26
        assert filas[0]["alerta"] is True

    def test_sin_alerta_dentro_del_umbral(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-7-2026": {
                "rit": "M-7-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-22T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["dias_sin_actualizar"] == 5
        assert filas[0]["alerta"] is False

    def test_ordena_por_rit(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-9-2026": {"rit": "M-9-2026", "empresa": "Alvi", "demandante": "B"},
            "M-2-2026": {"rit": "M-2-2026", "empresa": "Alvi", "demandante": "A"},
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert [f["rit"] for f in filas] == ["M-2-2026", "M-9-2026"]


class TestGenerarPanelHtml:
    def test_incluye_resumen_de_fases(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [
            {"fase": "calendario", "resultado": "No corresponde hoy", "error": None},
            {"fase": "smu", "resultado": "2 causas nuevas", "error": None},
        ]
        contenido = generar_panel_html(resumen, hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "calendario" in contenido
        assert "No corresponde hoy" in contenido
        assert "2 causas nuevas" in contenido

    def test_marca_errores_de_fase(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [{"fase": "goteo", "resultado": None, "error": "token vencido"}]
        contenido = generar_panel_html(resumen, hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "ERROR" in contenido
        assert "token vencido" in contenido

    def test_escapa_html_de_los_datos(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "<script>alert(1)</script>",
                "demandante": "Soto", "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "<script>alert(1)</script>" not in contenido
        assert "&lt;script&gt;" in contenido

    def test_incluye_tabla_de_causas(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
                "fecha_audiencia": "2026-09-10", "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "M-1-2026" in contenido
        assert "2026-09-10" in contenido

    def test_sin_causas_activas_no_falla(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "Sin causas activas" in contenido
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `cd "Actualizador de informes" && python -m pytest tests/test_panel.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gestion_causas.panel'`

- [ ] **Step 3: Implementa `panel.py`**

Crea `gestion_causas/panel.py`:

```python
#!/usr/bin/env python3
"""
Panel de estado del ciclo de gestión de causas.

Arma, a partir de registro_causas.json (sin agregar ningún campo nuevo al
registro), una vista HTML de una sola lectura del estado de cada causa
activa más un resumen de lo que hizo cada fase en la corrida — usado por
el orquestador (gestion-causas-orquestador) para el correo de auto-reporte
que envía al final de cada corrida (ver
enviar_panel_estado en gmail_client.py y el diseño en
docs/2026-08-27-orquestador-gestion-causas-design.md).
"""

import html as html_mod
from datetime import date, datetime

from . import registro as registro_mod

# Umbral (días corridos) a partir del cual una causa abierta sin novedades
# se marca con alerta en el panel. Valor inicial acordado en el diseño;
# ajustar aquí si en la práctica resulta muy sensible o muy laxo.
DIAS_ALERTA_SIN_ACTUALIZAR = 7


def _fase_actual(causa: dict) -> str:
    """Infiere una etiqueta de fase legible a partir de los campos que ya
    guardan calendario/smu/goteo/agenda en el registro — no es un campo
    propio, se recalcula siempre desde cero."""
    if causa.get("causa_cerrada"):
        return "Cerrada"
    if causa.get("minuta_ejecutada"):
        return "Minuta generada"
    if causa.get("oferta_borrador_creado"):
        return "Ofrecimiento enviado a Roman"
    if causa.get("tiene_demanda"):
        return "Demanda guardada, en curso"
    return "Recien registrada"


def _dias_sin_actualizar(causa: dict, hoy: date) -> int | None:
    marca = causa.get("ultima_actualizacion")
    if not marca:
        return None
    try:
        fecha = datetime.fromisoformat(marca).date()
    except ValueError:
        return None
    return (hoy - fecha).days


def estado_causas(hoy: date | None = None, ruta=None) -> list[dict]:
    """Lee registro_causas.json (o `ruta` si se indica) y devuelve una lista
    de dicts, uno por causa, con: rit, empresa, demandante, fase,
    fecha_audiencia, dias_sin_actualizar, alerta. Ordenada por RIT."""
    if hoy is None:
        hoy = date.today()
    kwargs = {} if ruta is None else {"ruta": ruta}
    registro = registro_mod.cargar_registro_causas(**kwargs)

    filas = []
    for causa in registro.values():
        dias = _dias_sin_actualizar(causa, hoy)
        cerrada = bool(causa.get("causa_cerrada"))
        filas.append({
            "rit": causa.get("rit", ""),
            "empresa": causa.get("empresa", ""),
            "demandante": causa.get("demandante") or causa.get("trabajador_demandado") or "",
            "fase": _fase_actual(causa),
            "fecha_audiencia": causa.get("fecha_audiencia") or "",
            "dias_sin_actualizar": dias,
            "alerta": (not cerrada) and dias is not None and dias >= DIAS_ALERTA_SIN_ACTUALIZAR,
        })
    filas.sort(key=lambda f: f["rit"])
    return filas


def _fila_resumen_html(item: dict) -> str:
    fase = html_mod.escape(str(item.get("fase", "")))
    error = item.get("error")
    if error:
        detalle = "ERROR - " + html_mod.escape(str(error))
    else:
        detalle = html_mod.escape(str(item.get("resultado", "")))
    return f"<li><strong>{fase}</strong>: {detalle}</li>"


def _fila_causa_html(causa: dict) -> str:
    estilo = ' style="background:#fff3cd;"' if causa["alerta"] else ""
    alerta_texto = f"{causa['dias_sin_actualizar']} dias sin novedades" if causa["alerta"] else ""
    return (
        f"<tr{estilo}>"
        f"<td>{html_mod.escape(causa['rit'])}</td>"
        f"<td>{html_mod.escape(causa['empresa'])}</td>"
        f"<td>{html_mod.escape(causa['demandante'])}</td>"
        f"<td>{html_mod.escape(causa['fase'])}</td>"
        f"<td>{html_mod.escape(causa['fecha_audiencia'])}</td>"
        f"<td>{html_mod.escape(alerta_texto)}</td>"
        "</tr>"
    )


def generar_panel_html(
    resumen_corrida: list[dict], hoy: date | None = None, ruta_registro=None
) -> str:
    """Arma el HTML completo del panel: resumen de la corrida (una entrada
    por fase, con lo que hizo o su error) + tabla de estado por causa.

    `resumen_corrida` es una lista de dicts
    {"fase": str, "resultado": str | None, "error": str | None}, en el
    orden en que corrieron los subagentes del orquestador (calendario, smu,
    goteo, agenda).
    """
    if hoy is None:
        hoy = date.today()
    causas = estado_causas(hoy=hoy, ruta=ruta_registro)

    resumen_html = "".join(_fila_resumen_html(item) for item in resumen_corrida)
    if not resumen_html:
        resumen_html = "<li>Sin fases ejecutadas</li>"

    causas_html = "".join(_fila_causa_html(c) for c in causas)
    if not causas_html:
        causas_html = '<tr><td colspan="6">Sin causas activas</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif;">
<h2>Panel de gestion de causas - {hoy.isoformat()}</h2>
<h3>Resumen de la corrida</h3>
<ul>{resumen_html}</ul>
<h3>Estado de cada causa activa</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
<tr><th>RIT</th><th>Empresa</th><th>Demandante</th><th>Fase</th><th>Audiencia</th><th>Alerta</th></tr>
{causas_html}
</table>
</body>
</html>"""
```

- [ ] **Step 4: Corre el test y verifica que pasa**

Run: `cd "Actualizador de informes" && python -m pytest tests/test_panel.py -v`
Expected: PASS (los 13 tests).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/panel.py" "Actualizador de informes/tests/test_panel.py"
git commit -m "feat(gestion_causas): agregar modulo panel.py para el estado del ciclo de causas"
```

---

### Task 3: Subcomandos `panel-html` y `enviar-panel` en el CLI

**Files:**
- Modify: `Actualizador de informes/gestion_causas/cli.py`
- Test: `Actualizador de informes/tests/test_cli.py`

- [ ] **Step 1: Escribe los tests que fallan**

Agrega a `tests/test_cli.py`, dentro de la clase `TestSubcomandosSinRed` (o como clase nueva al final del archivo):

```python
class TestPanel:
    def test_panel_html_escribe_archivo(self, tmp_path, capsys):
        resumen_json = tmp_path / "resumen.json"
        resumen_json.write_text(
            json.dumps([{"fase": "smu", "resultado": "sin novedades", "error": None}]),
            encoding="utf-8",
        )
        salida_html = tmp_path / "panel.html"
        registro_vacio = tmp_path / "registro_causas.json"
        registro_vacio.write_text("{}", encoding="utf-8")

        import gestion_causas.registro as registro_mod
        original = registro_mod.RUTA_REGISTRO_CAUSAS
        registro_mod.RUTA_REGISTRO_CAUSAS = registro_vacio
        try:
            codigo = main([
                "panel-html",
                "--resumen-json", str(resumen_json),
                "--salida", str(salida_html),
                "--hoy", "2026-08-27",
            ])
        finally:
            registro_mod.RUTA_REGISTRO_CAUSAS = original

        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["escrito"] is True
        assert salida_html.exists()
        assert "smu" in salida_html.read_text(encoding="utf-8")

    def test_enviar_panel_dry_run_no_envia(self, tmp_path, capsys):
        html_file = tmp_path / "panel.html"
        html_file.write_text("<html>contenido</html>", encoding="utf-8")

        codigo = main([
            "--dry-run", "enviar-panel",
            "--html-file", str(html_file),
            "--asunto", "Panel de prueba",
        ])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True
```

Actualiza el set `esperados` de `test_todos_los_subcomandos_esperados_existen` agregando `"panel-html"` y `"enviar-panel"`.

- [ ] **Step 2: Corre los tests y verifica que fallan**

Run: `cd "Actualizador de informes" && python -m pytest tests/test_cli.py -v -k "Panel or subcomandos_esperados"`
Expected: FAIL — `error: argument comando: invalid choice: 'panel-html'`

- [ ] **Step 3: Implementa los subcomandos**

En `gestion_causas/cli.py`, agrega el import nuevo junto a los demás (línea 43, orden alfabético: después de `ics`, antes de `registro`):

```python
from . import ics as ics_mod
from . import panel as panel_mod
from . import registro as registro_mod
```

Agrega las dos funciones `cmd_*` después de `cmd_buscar_audiencia_por_rit` (última función `cmd_*` del archivo, justo antes de `construir_parser`):

```python
def cmd_panel_html(args) -> int:
    with open(args.resumen_json, "r", encoding="utf-8") as f:
        resumen = json.load(f)
    hoy = date.fromisoformat(args.hoy) if args.hoy else None
    contenido = panel_mod.generar_panel_html(resumen, hoy=hoy)
    Path(args.salida).write_text(contenido, encoding="utf-8")
    _imprimir_json({"escrito": True, "ruta": args.salida})
    return 0


def cmd_enviar_panel(args) -> int:
    contenido = Path(args.html_file).read_text(encoding="utf-8")
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "enviar-panel", "asunto": args.asunto})
        return 0
    resultado = gmail_client.enviar_panel_estado(args.asunto, contenido)
    _imprimir_json(resultado)
    return 0
```

Agrega los subparsers correspondientes en `construir_parser()`, justo antes del `return parser` final:

```python
    p = sub.add_parser(
        "panel-html",
        help="Arma el HTML del panel de estado del ciclo de causas y lo escribe a un archivo",
    )
    p.add_argument("--resumen-json", required=True, help='Ruta a un JSON: [{"fase":.., "resultado":.., "error":..}, ...]')
    p.add_argument("--salida", required=True, help="Ruta donde escribir el HTML generado")
    p.add_argument("--hoy", default=None, help="Fecha AAAA-MM-DD a usar como 'hoy' (pruebas); por defecto hoy")
    p.set_defaults(func=cmd_panel_html)

    p = sub.add_parser(
        "enviar-panel",
        help="Envia el panel de estado por correo a nmunoz@gomezyriesco.cl (unica excepcion a la regla de no enviar correos)",
    )
    p.add_argument("--html-file", required=True)
    p.add_argument("--asunto", required=True)
    p.set_defaults(func=cmd_enviar_panel)

    return parser
```

- [ ] **Step 4: Corre los tests y verifica que pasan**

Run: `cd "Actualizador de informes" && python -m pytest tests/test_cli.py -v`
Expected: PASS (todos, incluidos los 2 nuevos y el de subcomandos esperados).

- [ ] **Step 5: Corre toda la suite de tests del paquete**

Run: `cd "Actualizador de informes" && python -m pytest -v`
Expected: PASS (ningún test existente roto por los cambios de Task 1-3).

- [ ] **Step 6: Commit**

```bash
git add "Actualizador de informes/gestion_causas/cli.py" "Actualizador de informes/tests/test_cli.py"
git commit -m "feat(gestion_causas): agregar subcomandos panel-html y enviar-panel al CLI"
```

---

### Task 4: Migrar `gestion-causas-calendario` a `subagentes/calendario.md`

**Files:**
- Create: `Actualizador de informes/gestion_causas/subagentes/calendario.md`

- [ ] **Step 1: Crea la carpeta y copia el contenido actual**

```bash
mkdir -p "Actualizador de informes/gestion_causas/subagentes"
cp "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-calendario/SKILL.md" "Actualizador de informes/gestion_causas/subagentes/calendario.md"
```

- [ ] **Step 2: Reemplaza el encabezado por el framing de subagente + autoevaluación de turno**

En `Actualizador de informes/gestion_causas/subagentes/calendario.md`, reemplaza (el bloque va desde el inicio del archivo hasta el final del primer párrafo "...ver el diseño completo en ... streamed-pizza.md."):

Old string:
```
---
name: gestion-causas-calendario
description: Fase 0: barre el calendario de nmunoz@gomezyriesco.cl buscando audiencias de las 6 empresas de interés que no estén registradas, y las da de alta (registro + etiqueta + carpeta si va a audiencia única o preparatoria)
---

---
name: gestion-causas-calendario
description: "Fase 0: barre el calendario de nmunoz@gomezyriesco.cl buscando audiencias de las 6 empresas de interés que no estén registradas, y las da de alta (registro + etiqueta + carpeta si va a audiencia única o preparatoria)"
---

Tarea programada desatendida (sin usuario presente). Fase 0 del proyecto "Gestión
automática de causas nuevas desde la casilla del trabajo" — ver el diseño completo en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`.
```

New string:
```
# Subagente "calendario" (Fase 0) del orquestador gestion-causas-orquestador

Fase 0 del proyecto "Gestión automática de causas nuevas desde la casilla del trabajo" —
ver el diseño completo en `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`
y en `Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase 0 de cada corrida.

## 0. Autoevaluación de turno

Esta fase solo actúa **los lunes**. Antes de hacer nada más, determina la fecha de hoy
(zona horaria de Chile) y el día de la semana:
- Si **no** es lunes: termina de inmediato. Tu único mensaje final debe ser
  "No corresponde hoy (Fase 0 solo corre los lunes)." No ejecutes ningún comando del CLI.
- Si es lunes: sigue con el resto de este archivo.
```

- [ ] **Step 3: Renombra la sección "0. Prerrequisito" para no chocar con la nueva "0."**

Old string:
```
## 0. Prerrequisito: tokens autorizados
```

New string:
```
## 0b. Prerrequisito: tokens autorizados
```

- [ ] **Step 4: Ajusta el cierre para que el resumen final sea lo que lee el orquestador**

Old string:
```
## 3. Resumen final

Entrega un resumen breve y legible:
```

New string:
```
## 3. Resumen final

Tu **último mensaje** de esta ejecución es el resumen que el orquestador va a copiar tal
cual a la sección "Fase calendario" del panel de estado — que sea breve y legible:
```

- [ ] **Step 5: Verifica que el resto del archivo (reglas de negocio) no cambió**

Run: `diff <(tail -n +5 "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-calendario/SKILL.md") <(tail -n +12 "Actualizador de informes/gestion_causas/subagentes/calendario.md") | head -40`
Expected: sin diferencias más allá de las 3 ediciones de los pasos 2-4 (los números de paso "1.", "2.", "3." del cuerpo original no cambiaron).

- [ ] **Step 6: Commit**

```bash
git add "Actualizador de informes/gestion_causas/subagentes/calendario.md"
git commit -m "feat(gestion_causas): migrar Fase 0 (calendario) a subagente del orquestador"
```

---

### Task 5: Migrar `gestion-causas-smu` a `subagentes/smu.md`

**Files:**
- Create: `Actualizador de informes/gestion_causas/subagentes/smu.md`

- [ ] **Step 1: Copia el contenido actual**

```bash
cp "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-smu/SKILL.md" "Actualizador de informes/gestion_causas/subagentes/smu.md"
```

- [ ] **Step 2: Reemplaza el encabezado**

Old string:
```
---
name: gestion-causas-smu
description: Revisa la casilla nmunoz@gomezyriesco.cl, registra causas nuevas de Rendic/Alvi/Super 10/SSLL/Preunic/Salcobrand, crea su carpeta en Minutas, guarda la demanda, pide los documentos de prueba y actualiza el Informe de Juicios Vigentes (solo para las 4 causas de SMU)
---

Tarea programada desatendida (sin usuario presente). Fases 1 y 2 del proyecto "Gestión
automática de causas nuevas desde la casilla del trabajo" — ver el diseño completo en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`. El goteo de
documentos (Fase 3) y la agenda de audiencias (Fase 4) son tareas programadas aparte
(`gestion-causas-goteo` y `gestion-causas-agenda`).
```

New string:
```
# Subagente "smu" (Fases 1-2) del orquestador gestion-causas-orquestador

Fases 1 y 2 del proyecto "Gestión automática de causas nuevas desde la casilla del
trabajo" — ver el diseño completo en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md` y en
`Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "smu" de cada corrida, siempre después de "calendario" y antes de
"goteo".
```

- [ ] **Step 3: Ajusta el cierre**

Old string:
```
## 3. Resumen final

Entrega un resumen breve y legible con:
```

New string:
```
## 3. Resumen final

Tu **último mensaje** de esta ejecución es el resumen que el orquestador va a copiar tal
cual a la sección "Fase smu" del panel de estado — que sea breve y legible, con:
```

- [ ] **Step 4: Verifica que el resto del archivo no cambió**

Run: `diff <(tail -n +8 "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-smu/SKILL.md") <(tail -n +11 "Actualizador de informes/gestion_causas/subagentes/smu.md") | head -40`
Expected: sin diferencias más allá de la edición del paso 3.

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/subagentes/smu.md"
git commit -m "feat(gestion_causas): migrar Fases 1-2 (smu) a subagente del orquestador"
```

---

### Task 6: Migrar `gestion-causas-goteo` a `subagentes/goteo.md`

**Files:**
- Create: `Actualizador de informes/gestion_causas/subagentes/goteo.md`

- [ ] **Step 1: Copia el contenido actual**

```bash
cp "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-goteo/SKILL.md" "Actualizador de informes/gestion_causas/subagentes/goteo.md"
```

- [ ] **Step 2: Reemplaza el encabezado**

Old string:
```
---
name: gestion-causas-goteo
description: Revisa las causas activas de Rendic/Alvi/Super 10/SSLL por documentos nuevos que hayan llegado por goteo (contrato, finiquito, EERR, etc.) y los guarda en la carpeta de cada causa (o en su subcarpeta "Exhibición de documentos" si la próxima audiencia es de juicio)
---

---
name: gestion-causas-goteo
description: Revisa las causas activas de Rendic/Alvi/Super 10/SSLL por documentos nuevos que hayan llegado por goteo (contrato, finiquito, EERR, etc.) y los guarda en la carpeta de cada causa (o en su subcarpeta "Exhibición de documentos" si la próxima audiencia es de juicio)
---

Tarea programada desatendida (sin usuario presente). Fase 3 del proyecto "Gestión
automática de causas nuevas desde la casilla del trabajo" — ver el diseño completo en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`. Depende de que
la tarea `gestion-causas-smu` (Fases 1-2) ya haya registrado las causas — esta tarea NO
descubre causas nuevas, solo revisa las ya conocidas por si llegaron documentos nuevos en
la misma cadena de correo. **Nunca** envía correos ni borra nada, y no toca el calendario.
```

New string:
```
# Subagente "goteo" (Fase 3) del orquestador gestion-causas-orquestador

Fase 3 del proyecto "Gestión automática de causas nuevas desde la casilla del trabajo" —
ver el diseño completo en `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`
y en `Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "goteo" de cada corrida, siempre después de "smu" (para poder revisar
en el mismo lote las causas recién registradas) y antes de "agenda". Depende de que el
subagente "smu" ya haya registrado las causas — este subagente NO descubre causas nuevas,
solo revisa las ya conocidas por si llegaron documentos nuevos en la misma cadena de
correo. **Nunca** envía correos ni borra nada, y no toca el calendario.
```

- [ ] **Step 3: Ajusta el cierre**

Old string:
```
## 3. Resumen final

Entrega un resumen breve: cuántas causas se revisaron, cuántas tenían documentos nuevos
```

New string:
```
## 3. Resumen final

Tu **último mensaje** de esta ejecución es el resumen que el orquestador va a copiar tal
cual a la sección "Fase goteo" del panel de estado. Entrega un resumen breve: cuántas
causas se revisaron, cuántas tenían documentos nuevos
```

- [ ] **Step 4: Verifica que el resto del archivo (incluidas las reglas de filtro de dominio y de asunto) no cambió**

Run: `diff <(tail -n +14 "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-goteo/SKILL.md") <(tail -n +13 "Actualizador de informes/gestion_causas/subagentes/goteo.md") | head -60`
Expected: sin diferencias más allá de la edición del paso 3. Esto es crítico: las reglas de dominios confiables y de exclusión de reportes consolidados (acumuladas a lo largo de varias corridas reales, ver bitácora) deben quedar intactas.

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/subagentes/goteo.md"
git commit -m "feat(gestion_causas): migrar Fase 3 (goteo) a subagente del orquestador"
```

---

### Task 7: Migrar `gestion-causas-agenda` a `subagentes/agenda.md`

**Files:**
- Create: `Actualizador de informes/gestion_causas/subagentes/agenda.md`

- [ ] **Step 1: Copia el contenido actual**

```bash
cp "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-agenda/SKILL.md" "Actualizador de informes/gestion_causas/subagentes/agenda.md"
```

- [ ] **Step 2: Reemplaza el encabezado**

Old string:
```
---
name: gestion-causas-agenda
description: A 14 días corridos de la audiencia única/de juicio, deja un borrador de ofrecimiento para Román; a 4 días hábiles de la audiencia única/preparatoria, corre /minuta-laboral
---

---
name: gestion-causas-agenda
description: A 14 días corridos de la audiencia única/de juicio, deja un borrador de ofrecimiento para Román; a 4 días hábiles de la audiencia única/preparatoria, corre /minuta-laboral
---

Tarea programada desatendida (sin usuario presente). Fase 4 del proyecto "Gestión
automática de causas nuevas desde la casilla del trabajo" — ver el diseño completo en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`. Depende de que
`gestion-causas-smu` ya haya registrado las causas (aplica a las 6 empresas: Rendic
Hermanos, Alvi, Super 10, Servicios Logísticos Santiago, Preunic y Salcobrand — esta
tarea no filtra por empresa, trabaja sobre lo que ya está en el registro local).
```

New string:
```
# Subagente "agenda" (Fases 4-6) del orquestador gestion-causas-orquestador

Fase 4 del proyecto "Gestión automática de causas nuevas desde la casilla del trabajo" —
ver el diseño completo en `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`
y en `Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "agenda" de cada corrida, siempre al final (después de "calendario",
"smu" y "goteo"). Depende de que el subagente "smu" ya haya registrado las causas (aplica
a las 6 empresas: Rendic Hermanos, Alvi, Super 10, Servicios Logísticos Santiago, Preunic
y Salcobrand — este subagente no filtra por empresa, trabaja sobre lo que ya está en el
registro local).
```

- [ ] **Step 3: Ajusta el cierre**

Old string:
```
## 5. Resumen final

Entrega un resumen breve: cuántas causas se revisaron, cuántos borradores de
```

New string:
```
## 5. Resumen final

Tu **último mensaje** de esta ejecución es el resumen que el orquestador va a copiar tal
cual a la sección "Fase agenda" del panel de estado. Entrega un resumen breve: cuántas
causas se revisaron, cuántos borradores de
```

- [ ] **Step 4: Verifica que el resto del archivo no cambió**

Run: `diff <(tail -n +11 "C:/Users/usuario/.claude/scheduled-tasks/gestion-causas-agenda/SKILL.md") <(tail -n +13 "Actualizador de informes/gestion_causas/subagentes/agenda.md") | head -60`
Expected: sin diferencias más allá de la edición del paso 3 (en particular, la plantilla exacta del correo de ofrecimiento del paso 3e no debe cambiar ni un carácter).

- [ ] **Step 5: Commit**

```bash
git add "Actualizador de informes/gestion_causas/subagentes/agenda.md"
git commit -m "feat(gestion_causas): migrar Fases 4-6 (agenda) a subagente del orquestador"
```

---

### Task 8: Crear la tarea programada `gestion-causas-orquestador`

**Files:** N/A — configuración de runtime (scheduled task), no archivos del repo.

- [ ] **Step 1: Autoriza el scope nuevo de Gmail (una sola vez, interactivo)**

El token `token_gmail_trabajo.json` fue autorizado antes de agregar el scope `gmail.send`
(Task 1) — hay que renovarlo con el consentimiento del usuario. Borra el token actual y
fuerza un nuevo login:

```bash
cd "Actualizador de informes" && rm gestion_causas/token_gmail_trabajo.json && python -m gestion_causas.cli diagnostico
```

Expected: se abre el navegador pidiendo iniciar sesión con `nmunoz@gomezyriesco.cl` y
aceptar los permisos (ahora incluye "enviar correo en tu nombre"); al terminar, el
comando imprime `{"email": "nmunoz@gomezyriesco.cl", "scopes": [...]}`. Si esto no lo
puede hacer el agente que ejecuta el plan (requiere un navegador interactivo del
usuario), delega este paso a Nico antes de continuar.

- [ ] **Step 2: Crea la tarea programada con `create_scheduled_task`**

Llama a la herramienta `create_scheduled_task` con estos parámetros exactos:

- `taskId`: `gestion-causas-orquestador`
- `description`: `Orquesta las 4 fases del ciclo de gestión de causas (calendario, smu, goteo, agenda) como subagentes secuenciales y envía un panel de estado por correo`
- `cronExpression`: `0 9,14,18 * * *`
- `prompt`:

```
Tarea programada desatendida (sin usuario presente). Reemplaza a las 4 tareas
`gestion-causas-calendario`, `gestion-causas-smu`, `gestion-causas-goteo` y
`gestion-causas-agenda` (quedan desactivadas, no borradas). Diseño completo en
`Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`.

Objetivo de esta corrida: ejecutar, en este orden fijo y **uno a la vez** (nunca en
paralelo), las 4 fases del ciclo de gestión de causas como subagentes aislados, y al
terminar armar y enviar por correo un panel de estado a nmunoz@gomezyriesco.cl.

Trabaja siempre con `Actualizador de informes` como directorio de trabajo para los
comandos de Bash/PowerShell.

## 1. Despacha los 4 subagentes, en este orden

Para cada fase de la tabla de abajo, usa la herramienta Agent (subagente nuevo, sin
contexto previo de esta conversación) con el siguiente prompt, reemplazando `<ARCHIVO>`
por la ruta indicada:

"Leé completo el archivo <ARCHIVO> con la herramienta Read, y seguí sus instrucciones al
pie de la letra como si fueran tu única tarea (incluye su propio manejo de errores y de
autenticación). Tu último mensaje de esta conversación debe ser exactamente el resumen
final que ese archivo te pide entregar — entre 1 y 5 líneas, sin texto adicional antes ni
después."

| Orden | Fase | ARCHIVO |
|---|---|---|
| 1 | calendario | Actualizador de informes\gestion_causas\subagentes\calendario.md |
| 2 | smu | Actualizador de informes\gestion_causas\subagentes\smu.md |
| 3 | goteo | Actualizador de informes\gestion_causas\subagentes\goteo.md |
| 4 | agenda | Actualizador de informes\gestion_causas\subagentes\agenda.md |

Espera a que cada subagente termine antes de despachar el siguiente (nunca los corras en
paralelo — comparten registro_causas.json y goteo/agenda dependen de que smu haya corrido
antes en la misma corrida).

Si un subagente falla o no responde (error de la herramienta Agent, o su último mensaje
no es un resumen coherente): no te detengas. Anota como resultado de esa fase el texto
"ERROR: <descripción breve del fallo>" y sigue con la siguiente fase de la lista. Un
fallo de una fase nunca cancela las demás ni el envío del panel.

## 2. Arma el JSON de resumen de la corrida

Con el resultado de cada subagente (su último mensaje, o el texto de error del punto
anterior), escribe con la herramienta Write un archivo temporal en
Actualizador de informes\gestion_causas\_panel_resumen_temp.json, con este formato
exacto (un objeto por fase, en el mismo orden en que corrieron):

[
  {"fase": "calendario", "resultado": "<resumen o null>", "error": "<solo si fallo, si no null>"},
  {"fase": "smu", "resultado": "...", "error": null},
  {"fase": "goteo", "resultado": "...", "error": null},
  {"fase": "agenda", "resultado": "...", "error": null}
]

## 3. Genera el HTML del panel

python -m gestion_causas.cli panel-html --resumen-json "Actualizador de informes\gestion_causas\_panel_resumen_temp.json" --salida "Actualizador de informes\gestion_causas\_panel_temp.html"

Esto lee registro_causas.json y escribe el HTML completo del panel en el archivo
indicado. No requiere red ni credenciales.

## 4. Envía el panel por correo

python -m gestion_causas.cli enviar-panel --html-file "Actualizador de informes\gestion_causas\_panel_temp.html" --asunto "Panel de gestión de causas - <fecha de hoy AAAA-MM-DD>"

Esta es la única acción de toda la automatización que envía un correo (excepción
acotada, solo a nmunoz@gomezyriesco.cl — ver el diseño). Si el comando falla (token
vencido, sin red, etc.), no reintentes en esta corrida: anota el error con

python -m gestion_causas.cli bitacora --mensaje "Orquestador: fallo al enviar el panel de estado (<error>)"

y sigue al paso 5 igual.

## 5. Limpieza y resumen final

Borra los dos archivos temporales del paso 2 y 3 (_panel_resumen_temp.json,
_panel_temp.html) si siguen existiendo.

Entrega un resumen final breve: qué hizo cada una de las 4 fases (una línea cada una,
tomada de su resultado/error), y si el panel se envió correctamente o falló.
```

- [ ] **Step 3: Corre la tarea una vez manualmente y revisa el correo**

Ejecuta la tarea recién creada de forma manual (no esperar al próximo cron) y confirma
que llegó el correo "Panel de gestión de causas - ..." a `nmunoz@gomezyriesco.cl`, que
el HTML se ve bien (tabla de causas, resumen de fases), y que no quedaron los archivos
temporales `_panel_resumen_temp.json` / `_panel_temp.html` en
`Actualizador de informes/gestion_causas/`.

---

### Task 9: Correr en paralelo, validar, y desactivar las tareas antiguas

**Files:** N/A — configuración de runtime.

- [ ] **Step 1: Deja correr ambas versiones en paralelo un mínimo de 2-3 días**

Las 4 tareas antiguas (`gestion-causas-calendario`, `gestion-causas-smu`,
`gestion-causas-goteo`, `gestion-causas-agenda`) siguen `enabled: true` durante este
período — no las toques todavía. El objetivo es comparar: ¿el orquestador detecta las
mismas causas nuevas, los mismos documentos de goteo, los mismos hitos de agenda que las
tareas antiguas? Compara `bitacora.md` de ambos períodos.

- [ ] **Step 2: Una vez validado, desactiva las 4 tareas antiguas**

Para cada una de las 4, llama a `update_scheduled_task` con `enabled: false`:
- `gestion-causas-calendario`
- `gestion-causas-smu`
- `gestion-causas-goteo`
- `gestion-causas-agenda`

No las borres — quedan como referencia histórica (mismo criterio ya usado con
`actualizar-informe-juicios`). `revision-semanal-calendario-audiencias` no se toca: está
fuera de este proyecto (ver nota en el diseño).

- [ ] **Step 3: Confirma con Nico**

Avisa que las 4 tareas antiguas quedaron desactivadas y que `gestion-causas-orquestador`
es ahora la única fuente del ciclo de gestión de causas, corriendo 3 veces al día con el
panel de estado por correo.

---

## Self-Review

**Cobertura del spec:**
- Orquestador único, 4 subagentes secuenciales, orden fijo (calendario→smu→goteo→agenda) → Tasks 4-8.
- Aislamiento de fallas (un fallo no cancela las demás fases ni el panel) → prompt del orquestador (Task 8, pasos 1 y 4).
- Panel HTML calculado sobre datos existentes, sin campos nuevos en el registro → Task 2 (`panel.py` lee `registro_causas.json` tal cual).
- Excepción acotada de envío, solo a `nmunoz@gomezyriesco.cl`, verificada por tests → Task 1.
- Manejo de errores de envío del propio correo (no reintenta, anota en bitácora) → Task 8 paso 4 del prompt.
- Pruebas para la función de envío y para el armado del HTML → Tasks 1 y 2.
- Migración sin reescritura de las reglas de negocio ya afinadas (dominios confiables, exclusión de reportes, plantilla de ofrecimiento) → Tasks 4-7, con paso explícito de `diff` para confirmar que el cuerpo no cambió.
- `revision-semanal-calendario-audiencias` fuera de alcance → no aparece en ninguna tarea de este plan.

**Placeholders:** ninguno — cada paso tiene código/comandos/contenido completo, sin "TBD" ni "similar a la Task N" sin repetir el contenido real.

**Consistencia de tipos/nombres:** `enviar_panel_estado(asunto, html, servicio=None)` en Task 1 coincide con el llamado `gmail_client.enviar_panel_estado(args.asunto, contenido)` en Task 3. `generar_panel_html(resumen_corrida, hoy=None, ruta_registro=None)` en Task 2 coincide con `panel_mod.generar_panel_html(resumen, hoy=hoy)` en Task 3 (el CLI no pasa `ruta_registro`, usa el default de producción — correcto, los tests de Task 3 monkeypatchean `registro_mod.RUTA_REGISTRO_CAUSAS` en vez de pasar la ruta, porque el CLI no expone ese parámetro). `PANEL_DESTINATARIO` se define en Task 1 y se verifica en el mismo Task 1 — no se usa en otros módulos.
