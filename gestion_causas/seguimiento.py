#!/usr/bin/env python3
"""
Análisis puro (sin llamadas a Gmail) de hilos ya traídos, para detectar
correos propios sin respuesta (subagente "seguimiento") y para armar el
barrido combinado de causas activas por RIT (subagente "goteo", comando
`mapa-hilos-por-rit`).

Todas las funciones reciben los mensajes ya leídos (mismo formato que
devuelve gmail_client.leer_mensaje / cli.cmd_leer_hilo: dict con "id",
"sender", "to", "cc", "date", "subject", "cuerpo_texto") y no tocan la red,
así se testean sin credenciales — mismo criterio que agenda.py y registro.py.
"""

import re
from datetime import date, datetime, timedelta
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


# ── Barrido combinado de Gmail por RIT (goteo.md paso 2 / seguimiento.md
# paso 3b) — ver docs/2026-08-28-goteo-incremental-y-acuerdo-pago-design.md
# para el historial de los 3 patrones de reporte consolidado que motivaron
# este filtro, confirmados en producción (Provisiones/Informe de
# provision/Riesgo causas estado sentencias, colados por error en varias
# causas antes de agregarse aquí como filtro mecánico). ──────────────────
_PREFIJOS_REPORTE_CONSOLIDADO = (
    "provisiones demanda laborales",
    "informe de provision",
    "informe provision",
    "risgo causas estado sentencias",
    "riesgo causas estado sentencias",
)


def _sin_acentos(texto: str) -> str:
    """Normaliza tildes comunes para comparar "provision"/"provisión" sin
    depender de que el asunto real las traiga bien codificadas."""
    tabla = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")
    return texto.translate(tabla)


def es_reporte_consolidado(asunto: str) -> bool:
    """True si `asunto` (tal cual, con o sin prefijos Re:/RV:/Fwd:) es un
    reporte/consolidado interno que menciona muchas causas de pasada, no
    prueba de una causa puntual — ver la nota de filtro de asunto en
    subagentes/goteo.md. Quita los prefijos y compara sin distinguir
    mayúsculas/tildes."""
    normalizado = _sin_acentos(normalizar_asunto(asunto)).strip().lower()
    return normalizado.startswith(_PREFIJOS_REPORTE_CONSOLIDADO)


def hilo_es_reporte_consolidado(mensajes: list) -> bool:
    """True si **cualquiera** de los mensajes del hilo tiene un asunto que
    matchea `es_reporte_consolidado` — con uno solo que matchee, se descarta
    el hilo completo (mismo criterio de goteo.md paso 2d)."""
    return any(es_reporte_consolidado(m.get("subject", "")) for m in mensajes)


def agrupar_causas_para_barrido(causas: list, hoy: date | None = None) -> dict:
    """Separa las causas activas (ver registro.causas_para_goteo) en los dos
    grupos del barrido combinado de goteo.md paso 2b:

    - "ya_revisadas": causas con `goteo_ultima_revision` guardada. Trae
      `rits` y `fecha_corte` (la `goteo_ultima_revision` más antigua del
      grupo, menos 1 día de colchón — el operador `after:` de Gmail filtra
      por día completo, así que sin el colchón se pierde lo llegado el mismo
      día después de una corrida anterior).
    - "primera_revision": causas sin `goteo_ultima_revision` — se buscan sin
      filtro de fecha, mismo criterio que un escaneo completo.

    También trae, a nivel de la raíz, "thread_por_rit": {rit: thread_id} para
    **toda** causa activa con `thread_id` registrado, sea "ya_revisada" o de
    "primera_revision" (bug confirmado el 2026-09-03 con T-26-2026: antes
    esta red de seguridad solo cubría primera_revision, así que una causa ya
    revisada cuyo hilo original nunca menciona su RIT como texto —el caso
    normal cuando el hilo sigue siendo "Notificación demanda laboral ..."
    sin el RIT en el asunto— quedaba fuera de la búsqueda de Gmail para
    siempre, aunque le llegaran documentos reales en esa misma cadena). El
    llamador (`cli._generar_mapa_hilos_por_rit`) usa este mapa para
    garantizar que el hilo original de cada causa se revise siempre, y para
    atribuírselo a su RIT sin depender de `clasificar_rits_de_hilo`.

    Un grupo con `rits` vacío no se busca (el llamador debe saltearlo). No
    toca la red — solo agrupa lo que ya trajo `causas_para_goteo`."""
    if hoy is None:
        hoy = date.today()

    ya_revisadas_rits = []
    fechas_revision = []
    primera_revision_rits = []
    thread_por_rit = {}

    for causa in causas:
        rit = causa.get("rit")
        if not rit:
            continue
        if causa.get("thread_id"):
            thread_por_rit[rit] = causa["thread_id"]
        ultima = causa.get("goteo_ultima_revision")
        if ultima:
            ya_revisadas_rits.append(rit)
            fechas_revision.append(date.fromisoformat(ultima))
        else:
            primera_revision_rits.append(rit)

    fecha_corte = None
    if fechas_revision:
        fecha_corte = str(min(fechas_revision) - timedelta(days=1))

    return {
        "ya_revisadas": {"rits": ya_revisadas_rits, "fecha_corte": fecha_corte},
        "primera_revision": {"rits": primera_revision_rits},
        "thread_por_rit": thread_por_rit,
    }


def construir_query_or_rits(rits: list, fecha_corte: str | None = None) -> str:
    """Arma el operador OR de Gmail para una lista de RITs, cada uno entre
    comillas (evita que Gmail interprete el guion del RIT como operador de
    exclusión), con `after:<fecha_corte>` antepuesto si se entrega."""
    or_rits = "(" + " OR ".join(f'"{rit}"' for rit in rits) + ")"
    if fecha_corte:
        fecha_gmail = fecha_corte.replace("-", "/")
        return f"after:{fecha_gmail} {or_rits}"
    return or_rits


def clasificar_rits_de_hilo(rits_activos: list, mensajes: list) -> list:
    """Devuelve los RITs de `rits_activos` que aparecen literalmente en el
    asunto de **algún** mensaje del hilo (normalizado, sin prefijos
    Re:/RV:/Fwd:/Fw: — el RIT queda en el asunto de toda la cadena, incluidas
    las respuestas). Comparación insensible a mayúsculas. Puede devolver más
    de un RIT si el hilo los menciona a todos (raro, pero no se descarta a
    ciegas — ver subagentes/goteo.md paso 2d, "usa criterio")."""
    asuntos_normalizados = [normalizar_asunto(m.get("subject", "")).lower() for m in mensajes]
    encontrados = []
    for rit in rits_activos:
        rit_normalizado = rit.lower()
        if any(rit_normalizado in asunto for asunto in asuntos_normalizados):
            encontrados.append(rit)
    return encontrados
