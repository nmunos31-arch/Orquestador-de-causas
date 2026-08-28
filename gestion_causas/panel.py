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


def _formato_fecha(fecha_iso: str) -> str:
    """Convierte una fecha ISO (YYYY-MM-DD) al formato dd-mm-yyyy usado en el
    panel. Si `fecha_iso` viene vacía o no calza con ese formato, se
    devuelve tal cual — el registro es la fuente de verdad, no la tocamos."""
    if not fecha_iso:
        return fecha_iso
    try:
        return datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return fecha_iso


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


# Nombres internos de fase (calendario/smu/goteo/agenda) vs. lo que se
# muestra en el correo — los internos son claves estables usadas por el
# orquestador y el resumen JSON; acá se traducen a una etiqueta que describe
# qué hace cada una, para que el panel se entienda sin conocer el código.
_FASE_ETIQUETAS = {
    "calendario": "Calendario (búsqueda de causas no detectadas por correo)",
    "smu": "Registro de causas nuevas",
    "goteo": "Recopilador de documentos",
    "agenda": "Minutas de prueba y ofrecimientos de acuerdos",
}


# Color (texto, fondo) por cada valor posible de "fase" de una causa (ver
# _fase_actual) — usado para pintar el badge de la columna Fase en la tabla.
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


def _badge(texto: str, color: str, fondo: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;'
        f'font-size:12px;font-weight:600;color:{color};background:{fondo};'
        f'white-space:nowrap;">{texto}</span>'
    )


# Recordá: todo campo nuevo que se agregue a _fila_resumen_html o
# _fila_causa_html debe pasar por html_mod.escape antes de insertarse en el
# f-string — no hay un wrapper que lo obligue estructuralmente.
def _fila_resumen_html(item: dict) -> str:
    fase_clave = str(item.get("fase", ""))
    fase = html_mod.escape(_FASE_ETIQUETAS.get(fase_clave, fase_clave))
    error = item.get("error")
    if error:
        icono, color, borde = "❌", "#991b1b", "#dc2626"
        detalle = "ERROR - " + html_mod.escape(str(error))
    else:
        icono, color, borde = "✅", "#166534", "#16a34a"
        detalle = html_mod.escape(str(item.get("resultado", "")) or "Sin novedades.")
    return (
        f'<div style="border-left:4px solid {borde};background:#fff;padding:10px 14px;'
        f'margin-bottom:8px;border-radius:0 6px 6px 0;">'
        f'<div style="font-weight:700;color:{color};">{icono} {fase}</div>'
        f'<div style="color:#374151;margin-top:2px;">{detalle}</div>'
        "</div>"
    )


def _fila_causa_html(causa: dict) -> str:
    estilo = ' style="background:#fff7ed;"' if causa["alerta"] else ""
    color, fondo = _COLOR_FASE_CAUSA.get(causa["fase"], _COLOR_FASE_CAUSA_DEFAULT)
    fase_badge = _badge(html_mod.escape(causa["fase"]), color, fondo)
    if causa["alerta"]:
        alerta_html = _badge(
            f"⚠ {causa['dias_sin_actualizar']} dias sin novedades", "#92400e", "#fef3c7"
        )
    else:
        alerta_html = ""
    return (
        f"<tr{estilo}>"
        f'<td style="padding:6px 10px;font-weight:600;white-space:nowrap;">{html_mod.escape(causa["rit"])}</td>'
        f'<td style="padding:6px 10px;min-width:160px;">{html_mod.escape(causa["demandante"])}</td>'
        f'<td style="padding:6px 10px;white-space:nowrap;">{fase_badge}</td>'
        f'<td style="padding:6px 10px;white-space:nowrap;">{html_mod.escape(_formato_fecha(causa["fecha_audiencia"]))}</td>'
        f'<td style="padding:6px 10px;white-space:nowrap;">{alerta_html}</td>'
        "</tr>"
    )


def _grupo_empresa_html(empresa: str, causas_empresa: list[dict]) -> str:
    causas_ordenadas = sorted(
        causas_empresa, key=lambda c: (not c["alerta"], c["rit"])
    )
    n_alertas = sum(1 for c in causas_ordenadas if c["alerta"])
    resumen_alertas = f" &middot; {_badge(f'{n_alertas} con alerta', '#92400e', '#fef3c7')}" if n_alertas else ""
    filas = "".join(_fila_causa_html(c) for c in causas_ordenadas)
    abierto = " open" if n_alertas else ""
    etiqueta_n = "causa" if len(causas_ordenadas) == 1 else "causas"
    return f"""<details{abierto} style="margin-bottom:10px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
<summary style="cursor:pointer;list-style:none;padding:10px 14px;background:#f9fafb;font-weight:700;color:#111827;">
{html_mod.escape(empresa)} <span style="font-weight:400;color:#6b7280;">({len(causas_ordenadas)} {etiqueta_n}){resumen_alertas}</span>
</summary>
<div style="overflow-x:auto;">
<table cellpadding="0" cellspacing="0" style="width:100%;min-width:520px;border-collapse:collapse;font-size:13px;">
<tr style="background:#f3f4f6;text-align:left;color:#374151;">
<th style="padding:6px 10px;white-space:nowrap;">RIT</th><th style="padding:6px 10px;">Demandante</th>
<th style="padding:6px 10px;white-space:nowrap;">Fase</th><th style="padding:6px 10px;white-space:nowrap;">Audiencia</th>
<th style="padding:6px 10px;white-space:nowrap;">Alerta</th>
</tr>
{filas}
</table>
</div>
</details>"""


def generar_panel_html(
    resumen_corrida: list[dict], hoy: date | None = None, ruta_registro=None
) -> str:
    """Arma el HTML completo del panel: resumen de la corrida (una tarjeta
    por fase, con lo que hizo o su error) + causas activas agrupadas por
    empresa en secciones plegables (las que tienen alertas quedan abiertas).

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
        resumen_html = "<div>Sin fases ejecutadas</div>"

    if causas:
        grupos: dict[str, list[dict]] = {}
        for c in causas:
            grupos.setdefault(c["empresa"], []).append(c)
        causas_html = "".join(
            _grupo_empresa_html(empresa, causas_empresa)
            for empresa, causas_empresa in sorted(grupos.items())
        )
        total = len(causas)
        con_alerta = sum(1 for c in causas if c["alerta"])
    else:
        causas_html = "<p>Sin causas activas.</p>"
        total = 0
        con_alerta = 0

    errores_fase = sum(1 for item in resumen_corrida if item.get("error"))
    chip_total = _badge(f"{total} causas activas", "#1e40af", "#dbeafe")
    chip_alerta = _badge(f"{con_alerta} con alerta", "#92400e", "#fef3c7")
    chip_errores = (
        _badge(f"{errores_fase} fase(s) con error", "#991b1b", "#fee2e2")
        if errores_fase
        else _badge("todas las fases OK", "#166534", "#dcfce7")
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f3f4f6;margin:0;padding:20px;color:#111827;">
<div style="max-width:760px;margin:0 auto;">
<div style="background:#111827;color:#fff;padding:18px 22px;border-radius:10px 10px 0 0;">
<h1 style="margin:0;font-size:19px;">Panel de gestion de causas</h1>
<div style="color:#9ca3af;font-size:13px;margin-top:2px;">{hoy.strftime("%d-%m-%Y")}</div>
</div>
<div style="background:#fff;padding:16px 22px;border-bottom:1px solid #e5e7eb;">
{chip_total} {chip_alerta} {chip_errores}
</div>
<div style="background:#fff;padding:18px 22px;">
<h2 style="font-size:15px;color:#374151;margin:0 0 10px;">Resumen de la corrida</h2>
{resumen_html}
</div>
<div style="background:#fff;padding:18px 22px;border-radius:0 0 10px 10px;">
<h2 style="font-size:15px;color:#374151;margin:0 0 10px;">Causas activas por empresa</h2>
{causas_html}
<p style="font-size:12px;color:#9ca3af;margin-top:14px;">
{_badge(f"&#9888; {DIAS_ALERTA_SIN_ACTUALIZAR}+ dias sin novedades", "#92400e", "#fef3c7")}
&nbsp;se marca en naranjo — hace clic en el nombre de una empresa para desplegar o
plegar sus causas.
</p>
</div>
</div>
</body>
</html>"""
