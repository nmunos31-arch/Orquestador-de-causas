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

from . import agenda as agenda_mod
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
    "seguimiento": "Insistencias por documentos y acuerdos sin respuesta",
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


# Colores de urgencia usados por la bandeja de acciones y por las tarjetas de
# fase estructuradas.
_COLOR_URGENCIA = {
    "alta": ("#991b1b", "#fee2e2"),
    "media": ("#92400e", "#fef3c7"),
    "baja": ("#4b5563", "#f3f4f6"),
}
_COLOR_URGENCIA_DEFAULT = _COLOR_URGENCIA["media"]


def _metricas_html(metricas: list) -> str:
    """Chips de {"etiqueta", "valor"} — la parte numerica del resumen
    estructurado de una fase (ver contrato JSON en subagentes/*.md, seccion
    Resumen final)."""
    if not metricas:
        return ""
    chips = " ".join(
        _badge(
            f"{html_mod.escape(str(m.get('valor', '')))} {html_mod.escape(str(m.get('etiqueta', '')))}",
            "#374151", "#f3f4f6",
        )
        for m in metricas
    )
    return f'<div style="margin-top:6px;">{chips}</div>'


def _items_html(items: list) -> str:
    """Lista de novedades por causa (rit/titulo/detalle/etiqueta) — la parte
    de un resumen de fase que hoy es un parrafo corrido; acá se separa en
    una fila por causa."""
    if not items:
        return ""
    filas = []
    for it in items:
        rit = html_mod.escape(str(it.get("rit", "")))
        titulo = html_mod.escape(str(it.get("titulo", "")))
        detalle = html_mod.escape(str(it.get("detalle", "")))
        etiqueta = it.get("etiqueta")
        etiqueta_html = " " + _badge(html_mod.escape(str(etiqueta)), "#374151", "#e5e7eb") if etiqueta else ""
        encabezado = " ".join(p for p in (rit, titulo) if p)
        filas.append(
            f'<div style="margin-top:4px;padding-left:10px;border-left:2px solid #e5e7eb;">'
            f'<span style="font-weight:600;">{encabezado}</span>{etiqueta_html}'
            f'<div style="color:#4b5563;">{detalle}</div>'
            "</div>"
        )
    return f'<div style="margin-top:6px;">{"".join(filas)}</div>'


def _notas_html(notas: list) -> str:
    """Notas de criterio del subagente (ej. "dominio nuevo visto, decidir si
    agregarlo") — texto chico al pie de la tarjeta de la fase."""
    if not notas:
        return ""
    filas = "".join(f"<li>{html_mod.escape(str(n))}</li>" for n in notas)
    return f'<ul style="margin:6px 0 0;padding-left:18px;color:#9ca3af;font-size:12px;">{filas}</ul>'


# Recordá: todo campo nuevo que se agregue a _fila_resumen_html o
# _fila_causa_html debe pasar por html_mod.escape antes de insertarse en el
# f-string — no hay un wrapper que lo obligue estructuralmente.
def _fila_resumen_html(item: dict) -> str:
    """Tarjeta de una fase en "Resumen de la corrida". Tres formatos
    posibles, en este orden de prioridad:
    1. `error` presente: tarjeta roja (fase que no pudo correr).
    2. `titular` presente: tarjeta estructurada (titular + metricas + items
       + notas) — el contrato JSON que entregan las 5 fases (ver
       subagentes/*.md, "Resumen final").
    3. Si no, texto plano de `resultado` (fase que aplico "No corresponde
       hoy" o similar) o de `resultado_crudo` (el agente no devolvio JSON
       valido — se marca "formato libre" para que se note en el correo, sin
       perder la informacion)."""
    fase_clave = str(item.get("fase", ""))
    fase = html_mod.escape(_FASE_ETIQUETAS.get(fase_clave, fase_clave))
    error = item.get("error")
    titular = item.get("titular")

    if error:
        icono, color, borde = "❌", "#991b1b", "#dc2626"
        cuerpo = f'<div style="color:#374151;margin-top:2px;">ERROR - {html_mod.escape(str(error))}</div>'
    elif titular:
        icono, color, borde = "✅", "#166534", "#16a34a"
        cuerpo = (
            f'<div style="color:#374151;margin-top:2px;">{html_mod.escape(str(titular))}</div>'
            f'{_metricas_html(item.get("metricas") or [])}'
            f'{_items_html(item.get("items") or [])}'
            f'{_notas_html(item.get("notas") or [])}'
        )
    else:
        resultado_crudo = item.get("resultado_crudo")
        if resultado_crudo is not None:
            icono, color, borde = "◻", "#6b7280", "#9ca3af"
            texto = f'{_badge("formato libre", "#6b7280", "#f3f4f6")} {html_mod.escape(str(resultado_crudo))}'
        else:
            icono, color, borde = "✅", "#166534", "#16a34a"
            texto = html_mod.escape(str(item.get("resultado", "")) or "Sin novedades.")
        cuerpo = f'<div style="color:#374151;margin-top:2px;">{texto}</div>'

    return (
        f'<div style="border-left:4px solid {borde};background:#fff;padding:10px 14px;'
        f'margin-bottom:8px;border-radius:0 6px 6px 0;">'
        f'<div style="font-weight:700;color:{color};">{icono} {fase}</div>'
        f"{cuerpo}"
        "</div>"
    )


def acciones_consolidadas(
    resumen_corrida: list, causas: list, pedidos: list, borradores_pendientes: list | None = None
) -> list:
    """Junta todo lo que requiere que Nico haga algo, de las 4 fuentes que
    hoy quedan enterradas cada una en su propio rincon del panel/registro:
    las `acciones` que cada fase reporta en su resumen estructurado, los
    borradores de documentos sin enviar (ver
    cli.cmd_verificar_borradores_pendientes), las causas con
    `estado_acuerdo: pago_recibido_pendiente_confirmar`, y los pedidos sin audiencia agendada
    (`estado: gestion_manual` en registro_pedidos.json,
    ver `registro.pedidos_abiertos`). Devuelve una lista de
    {"origen", "rit", "que", "urgencia"}, sin ordenar (el llamador ordena)."""
    acciones = []
    rits_gestion_manual_reportados = set()
    for item in resumen_corrida:
        fase = item.get("fase", "")
        for accion in item.get("acciones") or []:
            rit = accion.get("rit", "")
            acciones.append({
                "origen": fase,
                "rit": rit,
                "que": accion.get("que", ""),
                "urgencia": accion.get("urgencia") or "media",
            })
            if fase == "seguimiento":
                rits_gestion_manual_reportados.add(rit)
    for b in (borradores_pendientes or []):
        detalle_empresa = f" ({b['empresa']} - {b['demandante']})" if b.get("empresa") else ""
        acciones.append({
            "origen": "smu",
            "rit": b.get("rit", ""),
            "que": f"Borrador de documentos sin enviar{detalle_empresa}",
            "urgencia": "media",
        })
    for c in causas:
        if c.get("fase") == "Pago recibido, pendiente confirmar cierre":
            acciones.append({
                "origen": "goteo",
                "rit": c.get("rit", ""),
                "que": f"Pago recibido para {c.get('demandante', '')} — confirmar cierre de la causa",
                "urgencia": "alta",
            })
    for p in pedidos:
        if p.get("estado") == "gestion_manual" and p.get("rit") not in rits_gestion_manual_reportados:
            acciones.append({
                "origen": "seguimiento",
                "rit": p.get("rit", ""),
                "que": f"Causa sin audiencia agendada, sin respuesta ({p.get('tipo', '')}) — requiere gestion manual",
                "urgencia": "alta",
            })
    return acciones


def _bandeja_html(acciones: list) -> str:
    if not acciones:
        return (
            '<div style="border-left:4px solid #16a34a;background:#fff;padding:10px 14px;'
            'border-radius:0 6px 6px 0;color:#166534;font-weight:600;">'
            "✅ Nada pendiente de tu parte"
            "</div>"
        )
    orden_urgencia = {"alta": 0, "media": 1, "baja": 2}
    ordenadas = sorted(
        acciones, key=lambda a: (orden_urgencia.get(a.get("urgencia"), 1), a.get("rit") or "")
    )
    filas = []
    for a in ordenadas:
        color, fondo = _COLOR_URGENCIA.get(a.get("urgencia"), _COLOR_URGENCIA_DEFAULT)
        badge_urgencia = _badge(html_mod.escape(str(a.get("urgencia") or "media")), color, fondo)
        rit = html_mod.escape(str(a.get("rit") or ""))
        rit_html = f'<span style="font-weight:600;">{rit}</span> ' if rit else ""
        que = html_mod.escape(str(a.get("que", "")))
        origen = html_mod.escape(str(_FASE_ETIQUETAS.get(a.get("origen"), a.get("origen", ""))))
        filas.append(
            f'<div style="border-left:4px solid {color};background:#fff;padding:8px 14px;'
            f'margin-bottom:6px;border-radius:0 6px 6px 0;">'
            f"{badge_urgencia} {rit_html}{que}"
            f'<div style="color:#9ca3af;font-size:11px;margin-top:2px;">{origen}</div>'
            "</div>"
        )
    return "".join(filas)


def pedidos_abiertos_para_panel(
    hoy: date | None = None, ruta_pedidos=None, ruta_seguimiento=None, ruta_causas=None
) -> list:
    """Lee registro_pedidos.json y arma la fila que va en la seccion "Pedidos
    abiertos" del panel: RIT, tipo, destinatario, dias habiles sin
    respuesta, que falta (para `documentos`) y en que aviso va (leido de
    registro_seguimiento.json, que sigue siendo la fuente de la cadencia).
    Ordenada por dias sin respuesta, descendente (los mas viejos primero —
    son los que mas urgen). `ruta_causas` se pasa a `registro.pedidos_abiertos`
    para excluir pedidos de causas ya cerradas (`causa_cerrada: true`)."""
    if hoy is None:
        hoy = date.today()
    kwargs_pedidos = {} if ruta_pedidos is None else {"ruta": ruta_pedidos}
    if ruta_causas is not None:
        kwargs_pedidos["ruta_causas"] = ruta_causas
    kwargs_seg = {} if ruta_seguimiento is None else {"ruta": ruta_seguimiento}

    filas = []
    for p in registro_mod.pedidos_abiertos(**kwargs_pedidos):
        fecha_envio = p.get("fecha_envio")
        dias = agenda_mod.dias_habiles_entre(fecha_envio, hoy) if fecha_envio else None
        pedidos_items = p.get("items_pedidos") or []
        recibidos = set(p.get("items_recibidos") or [])
        faltan = [i for i in pedidos_items if i not in recibidos] if pedidos_items else []

        thread_id = p.get("thread_id", "")
        seguimiento = registro_mod.obtener_seguimiento(thread_id, **kwargs_seg) if thread_id else None
        n_avisos = len((seguimiento or {}).get("avisos") or [])

        filas.append({
            "rit": p.get("rit") or "",
            "tipo": p.get("tipo") or "",
            "destinatario": p.get("destinatario") or "",
            "dias_habiles": dias,
            "faltan": faltan,
            "estado": p.get("estado") or "esperando",
            "n_avisos": n_avisos,
        })
    filas.sort(key=lambda f: (f["dias_habiles"] is None, -(f["dias_habiles"] or 0)))
    return filas


def _pedidos_abiertos_html(pedidos: list) -> str:
    if not pedidos:
        return "<p>Sin pedidos abiertos.</p>"
    filas = []
    for p in pedidos:
        dias = p["dias_habiles"]
        dias_texto = f"{dias} dias habiles" if dias is not None else "-"
        falta = ", ".join(p["faltan"]) if p["faltan"] else "-"
        if p["estado"] == "gestion_manual":
            aviso_badge = _badge("gestion manual", "#991b1b", "#fee2e2")
        elif p["n_avisos"] >= 1:
            aviso_badge = _badge(f"{p['n_avisos']}º aviso", "#92400e", "#fef3c7")
        else:
            aviso_badge = _badge("sin avisos", "#4b5563", "#f3f4f6")
        filas.append(
            "<tr>"
            f'<td style="padding:6px 10px;font-weight:600;white-space:nowrap;">{html_mod.escape(p["rit"])}</td>'
            f'<td style="padding:6px 10px;white-space:nowrap;">{html_mod.escape(p["tipo"])}</td>'
            f'<td style="padding:6px 10px;min-width:140px;">{html_mod.escape(p["destinatario"])}</td>'
            f'<td style="padding:6px 10px;white-space:nowrap;">{html_mod.escape(dias_texto)}</td>'
            f'<td style="padding:6px 10px;">{html_mod.escape(falta)}</td>'
            f'<td style="padding:6px 10px;white-space:nowrap;">{aviso_badge}</td>'
            "</tr>"
        )
    return f"""<div style="overflow-x:auto;">
<table cellpadding="0" cellspacing="0" style="width:100%;min-width:560px;border-collapse:collapse;font-size:13px;">
<tr style="background:#f3f4f6;text-align:left;color:#374151;">
<th style="padding:6px 10px;white-space:nowrap;">RIT</th><th style="padding:6px 10px;">Tipo</th>
<th style="padding:6px 10px;">Destinatario</th><th style="padding:6px 10px;white-space:nowrap;">Sin respuesta</th>
<th style="padding:6px 10px;">Falta</th><th style="padding:6px 10px;white-space:nowrap;">Aviso</th>
</tr>
{"".join(filas)}
</table>
</div>"""


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
    resumen_corrida: list[dict],
    hoy: date | None = None,
    ruta_registro=None,
    ruta_registro_pedidos=None,
    ruta_registro_seguimiento=None,
    borradores_pendientes: list | None = None,
) -> str:
    """Arma el HTML completo del panel: bandeja de acciones (todo lo que
    requiere que Nico haga algo, consolidado de las 4 fuentes que hoy
    quedan repartidas por el correo) + resumen de la corrida (una tarjeta
    por fase, estructurada o con su error) + pedidos abiertos (documentos y
    acuerdos que siguen esperando respuesta) + causas activas agrupadas por
    empresa en secciones plegables (las que tienen alertas quedan abiertas).

    `resumen_corrida` es una lista de dicts, uno por fase, en el contrato
    JSON documentado en subagentes/*.md ("Resumen final"): `{"fase",
    "error"}` si la fase no corrió, o con `"titular"/"metricas"/"items"/
    "acciones"/"notas"` si corrió (ver `_fila_resumen_html`). Un `"resultado"`
    (fase que reportó "No aplica...") o `"resultado_crudo"` (el agente no
    devolvió JSON válido) también se aceptan como fallback de texto plano.

    `borradores_pendientes` es la lista `pendientes` que devuelve
    `verificar-borradores-pendientes` (documentos sin enviar de corridas
    anteriores) — opcional, para no romper llamadas existentes que no lo
    pasen.
    """
    if hoy is None:
        hoy = date.today()
    causas = estado_causas(hoy=hoy, ruta=ruta_registro)
    pedidos = pedidos_abiertos_para_panel(
        hoy=hoy,
        ruta_pedidos=ruta_registro_pedidos,
        ruta_seguimiento=ruta_registro_seguimiento,
        ruta_causas=ruta_registro,
    )

    acciones = acciones_consolidadas(resumen_corrida, causas, pedidos, borradores_pendientes)
    bandeja_html = _bandeja_html(acciones)

    resumen_html = "".join(_fila_resumen_html(item) for item in resumen_corrida)
    if not resumen_html:
        resumen_html = "<div>Sin fases ejecutadas</div>"

    pedidos_html = _pedidos_abiertos_html(pedidos)

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
    chip_acciones = (
        _badge(f"{len(acciones)} accion(es) pendientes", "#991b1b", "#fee2e2")
        if acciones
        else _badge("nada pendiente", "#166534", "#dcfce7")
    )
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
{chip_total} {chip_alerta} {chip_acciones} {chip_errores}
</div>
<div style="background:#fff;padding:18px 22px;border-bottom:1px solid #e5e7eb;">
<h2 style="font-size:15px;color:#374151;margin:0 0 10px;">Requiere tu atencion</h2>
{bandeja_html}
</div>
<div style="background:#fff;padding:18px 22px;border-bottom:1px solid #e5e7eb;">
<h2 style="font-size:15px;color:#374151;margin:0 0 10px;">Resumen de la corrida</h2>
{resumen_html}
</div>
<div style="background:#fff;padding:18px 22px;border-bottom:1px solid #e5e7eb;">
<h2 style="font-size:15px;color:#374151;margin:0 0 10px;">Pedidos abiertos</h2>
{pedidos_html}
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
