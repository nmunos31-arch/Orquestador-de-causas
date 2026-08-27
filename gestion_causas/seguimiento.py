#!/usr/bin/env python3
"""
Análisis puro (sin llamadas a Gmail) de hilos ya traídos, para detectar
correos propios sin respuesta — Fase 5 ("gestion-causas-sin-respuesta") y
Fase 6 ("gestion-causas-documentos-pendientes").

Todas las funciones reciben los mensajes ya leídos (mismo formato que
devuelve gmail_client.leer_mensaje / cli.cmd_leer_hilo: dict con "id",
"sender", "to", "cc", "date", "subject", "cuerpo_texto") y no tocan la red,
así se testean sin credenciales — mismo criterio que agenda.py y registro.py.
"""

import re
from datetime import datetime
from email.utils import getaddresses, parsedate_to_datetime

_PREFIJOS_ASUNTO = re.compile(r"^\s*(re|rv|fwd|fw)\s*:\s*", re.IGNORECASE)


def extraer_direccion(remitente: str) -> str:
    """"Nombre Apellido <a@b.cl>" -> "a@b.cl" (minúsculas). Si `remitente` ya
    es solo la dirección, la devuelve normalizada igual. Cadena vacía si no
    se puede extraer nada."""
    direcciones = getaddresses([remitente or ""])
    if not direcciones or not direcciones[0][1]:
        return ""
    return direcciones[0][1].strip().lower()


def extraer_nombre_pila(remitente: str) -> str:
    """"Alexis Cubillos Arellano <acubillos@divisionlogistica.cl>" -> "Alexis".
    Si no hay nombre (solo la dirección), usa la parte antes de la @ tal
    cual, capitalizada. Usado para el saludo de los borradores de
    insistencia ("Estimado/a [Nombre]")."""
    nombre, direccion = (getaddresses([remitente or ""]) or [("", "")])[0]
    nombre = nombre.strip()
    if nombre:
        return nombre.split()[0]
    if direccion:
        return direccion.split("@")[0].capitalize()
    return ""


def parsear_fecha(valor: str) -> datetime:
    """Parsea la fecha RFC 2822 del header "Date" de un mensaje de Gmail."""
    return parsedate_to_datetime(valor)


def normalizar_asunto(asunto: str) -> str:
    """Quita prefijos "Re:"/"RV:"/"Fwd:"/"FW:" repetidos al inicio (Gmail los
    va acumulando: "Re: RV: Re: Causa laboral ..."), para poder evaluar si el
    asunto real empieza con un texto dado (ej. "Causa laboral")."""
    asunto = asunto or ""
    anterior = None
    while anterior != asunto:
        anterior = asunto
        asunto = _PREFIJOS_ASUNTO.sub("", asunto)
    return asunto.strip()


def destinatarios_respuesta(mensaje: dict, direccion_propia: str) -> dict:
    """A partir de los headers From/To/Cc del `mensaje` (el que se está
    respondiendo), arma {"para": <dirección del remitente original>, "cc":
    [resto de To+Cc, sin `direccion_propia` ni el propio "para"]} — para
    armar un "responder a todos" sin incluirse a uno mismo dos veces."""
    propia = (direccion_propia or "").strip().lower()
    para = extraer_direccion(mensaje.get("sender", ""))

    vistos = {propia, para}
    cc = []
    for campo in ("to", "cc"):
        for _, direccion in getaddresses([mensaje.get(campo, "") or ""]):
            direccion = direccion.strip().lower()
            if direccion and direccion not in vistos:
                vistos.add(direccion)
                cc.append(direccion)
    return {"para": para, "cc": cc}


_PATRONES_CIERRE = re.compile(
    r"(acuso recibo|acusamos recibo|muchas gracias|lo tenemos presente|"
    r"saludos cordiales|quedamos atentos)",
    re.IGNORECASE,
)


def parece_cierre_sin_pedido(cuerpo_texto: str) -> bool:
    """Heurística: True si el cuerpo parece un acuse de recibo/cierre de
    conversación corto (ej. "Estimada Daniela: Acuso recibo. Saludos
    cordiales.") que no espera respuesta, en vez de un correo que sí la
    espera (una propuesta, un pedido de documentos, una insistencia). Se usa
    como ayuda — el juicio final de si un hilo "espera respuesta" lo hace
    quien orquesta la tarea programada, no esta función."""
    texto = (cuerpo_texto or "").strip()
    if not texto:
        return False
    # Corto y con alguna frase de cierre típica: cuenta como cierre.
    return len(texto) < 400 and bool(_PATRONES_CIERRE.search(texto))


def analizar_hilo(
    mensajes: list,
    ahora: datetime,
    direccion_propia: str,
    responder_esperado: str | None = None,
) -> dict:
    """Analiza los mensajes de un hilo (ordenados como los devuelve Gmail,
    de más antiguo a más reciente) y determina si el último mensaje propio
    sigue sin respuesta.

    - `direccion_propia`: la casilla que corre la automatización
      (nmunoz@gomezyriesco.cl) — se usa para encontrar "el último mensaje
      propio".
    - `responder_esperado`: si se entrega, "sin respuesta" exige que no haya
      ningún mensaje posterior AL último propio enviado por esa dirección
      puntual (no basta con que conteste un tercero del hilo — caso real
      O-348-2026: Alexis contestó pero Daniela seguía sin responder). Si es
      None, "sin respuesta" es simplemente que el último mensaje del hilo
      sea el propio.

    Devuelve:
        {
            "iniciado_por": <dirección del primer mensaje>,
            "ultimo_mensaje_propio": <dict del mensaje o None>,
            "ultimo_mensaje": <dict del último mensaje del hilo>,
            "hay_respuesta_posterior": bool,
            "horas_sin_respuesta": float | None,
            "participantes": [direcciones únicas del hilo],
        }
    Si no hay ningún mensaje propio en el hilo, "horas_sin_respuesta" es None
    (no aplica: nada que insistir).
    """
    propia = (direccion_propia or "").strip().lower()
    esperado = (responder_esperado or "").strip().lower() or None

    participantes = []
    vistos = set()
    for m in mensajes:
        d = extraer_direccion(m.get("sender", ""))
        if d and d not in vistos:
            vistos.add(d)
            participantes.append(d)

    iniciado_por = extraer_direccion(mensajes[0]["sender"]) if mensajes else ""

    ultimo_mensaje_propio = None
    indice_ultimo_propio = None
    for i, m in enumerate(mensajes):
        if extraer_direccion(m.get("sender", "")) == propia:
            ultimo_mensaje_propio = m
            indice_ultimo_propio = i

    ultimo_mensaje = mensajes[-1] if mensajes else None

    if ultimo_mensaje_propio is None:
        return {
            "iniciado_por": iniciado_por,
            "ultimo_mensaje_propio": None,
            "ultimo_mensaje": ultimo_mensaje,
            "hay_respuesta_posterior": None,
            "horas_sin_respuesta": None,
            "participantes": participantes,
        }

    posteriores = mensajes[indice_ultimo_propio + 1:]
    if esperado:
        hay_respuesta_posterior = any(
            extraer_direccion(m.get("sender", "")) == esperado for m in posteriores
        )
    else:
        hay_respuesta_posterior = len(posteriores) > 0

    horas_sin_respuesta = None
    if not hay_respuesta_posterior:
        fecha_propio = parsear_fecha(ultimo_mensaje_propio["date"])
        horas_sin_respuesta = (ahora - fecha_propio).total_seconds() / 3600.0

    return {
        "iniciado_por": iniciado_por,
        "ultimo_mensaje_propio": ultimo_mensaje_propio,
        "ultimo_mensaje": ultimo_mensaje,
        "hay_respuesta_posterior": hay_respuesta_posterior,
        "horas_sin_respuesta": horas_sin_respuesta,
        "participantes": participantes,
    }


def destinatarios_de_ultimo_propio(mensaje_propio: dict, direccion_propia: str) -> dict:
    """A partir de los headers To/Cc del ÚLTIMO MENSAJE PROPIO (el que se
    quedó sin respuesta), arma {"para": <primer destinatario>, "cc": [el
    resto]} — a quién insistirle cuando nadie contestó nada, así que no hay
    remitente ajeno del cual tomar el "para" (a diferencia de
    destinatarios_respuesta, pensada para responder a un mensaje ajeno)."""
    propia = (direccion_propia or "").strip().lower()
    direcciones = []
    vistos = {propia}
    for campo in ("to", "cc"):
        for _, direccion in getaddresses([mensaje_propio.get(campo, "") or ""]):
            direccion = direccion.strip().lower()
            if direccion and direccion not in vistos:
                vistos.add(direccion)
                direcciones.append(direccion)
    if not direcciones:
        return {"para": "", "cc": []}
    return {"para": direcciones[0], "cc": direcciones[1:]}
