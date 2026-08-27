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


# Recordá: todo campo nuevo que se agregue a _fila_resumen_html o
# _fila_causa_html debe pasar por html_mod.escape antes de insertarse en el
# f-string — no hay un wrapper que lo obligue estructuralmente.
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
