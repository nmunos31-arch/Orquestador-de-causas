"""Driver Python de la fase 'goteo' (ver spec en
docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md y,
como referencia histórica de las reglas, subagentes/goteo.md).

Revisa las causas activas por si llegaron documentos nuevos en su cadena de
correo. Nunca envía correos ni borra nada, y no toca el calendario. Depende
de que `orquestador.py` ya haya armado `_contexto_corrida.json` antes de
llamar a `correr()` — este módulo no arma su propio contexto (ver "Alcance"
del plan de implementación)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import mapas as mapas_mod
from gestion_causas import registro as registro_mod
from gestion_causas import reasoning
from gestion_causas.carpetas import carpeta_destino_por_tipo_audiencia
from gestion_causas.seguimiento import es_remitente_confiable

NOMBRES_ADJUNTO_EXCLUIDOS = {"invite.ics"}

# Cota de seguridad para el tamaño total del contexto que le mandamos a
# claude -p: un hilo de correo real de 29 mensajes (~800KB) hizo que
# claude -p rechazara el prompt con "Prompt is too long" (confirmado en una
# corrida real). El recorte de texto citado (_quitar_texto_citado) resuelve
# la causa de fondo (el historial repetido en cada respuesta), pero esta
# cota es la última red de seguridad para que un hilo igual de largo nunca
# vuelva a tumbar la evaluación por completo.
LIMITE_CONTEXTO_CHARS = 400_000

# Patrones de inicio de texto citado en clientes de correo en español
# (Gmail y Outlook en modo texto plano) — cada correo de un hilo suele
# repetir el historial completo de los anteriores, que ya está disponible
# en el mensaje original respectivo.
_PATRONES_INICIO_CITA = [
    re.compile(r"^>", re.MULTILINE),
    re.compile(r"^El .+ escribió:\s*$", re.MULTILINE),
    re.compile(r"^De:.*\n(?:Enviado|Para|Asunto):", re.MULTILINE),
    re.compile(r"^-{3,}\s*Mensaje original\s*-{3,}", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^_{10,}\s*$", re.MULTILINE),
]


def _quitar_texto_citado(cuerpo_texto: str) -> str:
    """Corta `cuerpo_texto` en la primera línea que marca el inicio del
    historial citado (la respuesta anterior, que el correo repite aunque ya
    esté disponible en su mensaje original). Si no encuentra ningún patrón
    conocido, devuelve el cuerpo intacto — un recorte conservador que nunca
    descarta contenido de un formato no reconocido."""
    primer_inicio = min(
        (m.start() for patron in _PATRONES_INICIO_CITA for m in [patron.search(cuerpo_texto)] if m),
        default=None,
    )
    if primer_inicio is None:
        return cuerpo_texto
    return cuerpo_texto[:primer_inicio].rstrip()


def _acotar_mensajes_por_tamano(mensajes: list[dict], limite: int) -> bool:
    """Si la suma de las longitudes de `cuerpo` en `mensajes` supera
    `limite`, trunca por el principio (se asume orden cronológico
    ascendente, mensajes más antiguos primero) hasta bajar del límite. Muta
    `mensajes` in place. Devuelve si hubo truncado."""
    exceso = sum(len(m["cuerpo"]) for m in mensajes) - limite
    if exceso <= 0:
        return False
    for mensaje in mensajes:
        if exceso <= 0:
            break
        recorte = min(len(mensaje["cuerpo"]), exceso)
        mensaje["cuerpo"] = mensaje["cuerpo"][recorte:]
        exceso -= recorte
    return True


SCHEMA_ACUERDO = {
    "type": "object",
    "properties": {
        "acuerdo_cerrado": {"type": "boolean"},
        "pago_confirmado": {"type": "boolean"},
        "justificacion": {"type": "string"},
    },
    "required": ["acuerdo_cerrado", "pago_confirmado", "justificacion"],
}


def _detectar_acuerdo_y_pago(mensajes_hilos: list[dict]) -> dict:
    """Le pregunta a Claude si el hilo confirma que se ALCANZÓ Y APROBÓ un
    acuerdo (no alcanza con que el tribunal haya propuesto bases de
    conciliación — ver memoria gestion_causas_bases_tribunal_no_es_acuerdo) y
    si hay un comprobante de pago asociado."""
    contexto = {
        "mensajes": [
            {
                "remitente": m.get("sender", ""),
                "asunto": m.get("subject", ""),
                "cuerpo": _quitar_texto_citado(m.get("cuerpo_texto", "")),
            }
            for m in mensajes_hilos
        ]
    }
    hubo_truncado = _acotar_mensajes_por_tamano(contexto["mensajes"], LIMITE_CONTEXTO_CHARS)
    tarea = (
        "Estos son los mensajes de un hilo de correo sobre una causa laboral. "
        "Decidí si el hilo confirma que se ALCANZÓ Y APROBÓ un acuerdo "
        "(avenimiento/conciliación) entre las partes. Que el tribunal haya "
        "propuesto bases de conciliación en una audiencia NO cuenta como "
        "acuerdo alcanzado — hace falta confirmación de que las partes lo "
        "cerraron (ej. 'acta de conciliación', 'avenimiento aprobado', 'se "
        "aprobó el acuerdo por $X', 'conciliación total'). Además decidí si "
        "alguno de los mensajes trae un comprobante de pago o transferencia "
        "asociado a ese acuerdo."
    )
    resultado = reasoning.preguntar(tarea, contexto, SCHEMA_ACUERDO)
    if hubo_truncado:
        resultado = {**resultado, "_contexto_truncado": True}
    return resultado


def _accion_error_deteccion(rit: str, error: str) -> dict:
    return {
        "rit": rit,
        "que": f"No se pudo evaluar acuerdo/pago automáticamente: {error}",
        "urgencia": "media",
    }


def _accion_contexto_truncado(rit: str) -> dict:
    return {
        "rit": rit,
        "que": (
            "El hilo de correo es muy largo y se truncaron mensajes antiguos "
            "antes de evaluarlo con Claude — revisar manualmente si hay dudas."
        ),
        "urgencia": "media",
    }


def _evaluar_acuerdo_y_pago(
    rit: str, mensajes_hilos: list[dict], ruta_registro_causas: Path, acciones: list[dict]
) -> None:
    """Corre la detección de acuerdo/pago para una causa (si hay hilos
    nuevos) y aplica la transición de estado correspondiente, agregando a
    `acciones` (mutado in place) el aviso para Nico — de éxito o de error.
    No hace nada si `mensajes_hilos` está vacío, ni si la causa ya está en el
    estado terminal `pago_recibido_pendiente_confirmar`. Un valor de
    `estado_acuerdo` desconocido se trata igual que 'sin acuerdo todavía'."""
    if not mensajes_hilos:
        return

    causa_registrada = registro_mod.obtener_causa(rit, ruta=ruta_registro_causas) or {}
    estado_actual = causa_registrada.get("estado_acuerdo")

    if estado_actual not in ("pendiente_pago", "pago_recibido_pendiente_confirmar"):
        deteccion = _detectar_acuerdo_y_pago(mensajes_hilos)
        if deteccion.get("_contexto_truncado"):
            acciones.append(_accion_contexto_truncado(rit))
        if deteccion.get("error"):
            acciones.append(_accion_error_deteccion(rit, deteccion["error"]))
        elif deteccion.get("acuerdo_cerrado"):
            registro_mod.registrar_causa(rit, {"estado_acuerdo": "pendiente_pago"}, ruta=ruta_registro_causas)
            bitacora_mod.registrar("Acuerdo alcanzado, pendiente de pago", rit=rit)
            acciones.append({"rit": rit, "que": "Acuerdo alcanzado, pendiente de pago", "urgencia": "alta"})
    elif estado_actual == "pendiente_pago":
        deteccion = _detectar_acuerdo_y_pago(mensajes_hilos)
        if deteccion.get("_contexto_truncado"):
            acciones.append(_accion_contexto_truncado(rit))
        if deteccion.get("error"):
            acciones.append(_accion_error_deteccion(rit, deteccion["error"]))
        elif deteccion.get("pago_confirmado"):
            registro_mod.registrar_causa(
                rit, {"estado_acuerdo": "pago_recibido_pendiente_confirmar"}, ruta=ruta_registro_causas
            )
            bitacora_mod.registrar(
                "Comprobante de pago recibido, pendiente que Nico confirme el cierre", rit=rit
            )
            acciones.append({"rit": rit, "que": "Pago recibido, pendiente confirmar cierre", "urgencia": "alta"})


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    causas = registro_mod.causas_para_goteo(hoy=contexto_corrida["fecha_hoy"], ruta=ruta_registro_causas)
    if not causas:
        return {
            "fase": "goteo",
            "titular": "Sin causas activas para revisar",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    mapa_hilos = _leer_mapa_hilos(contexto_corrida)
    mapa_audiencias = mapas_mod.leer_mapa_audiencias(contexto_corrida)

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = list(mapa_hilos.get("_notas", []))
    con_documentos_nuevos = 0
    identificados_eerr = 0

    for causa in causas:
        rit = causa["rit"]
        hilos_rit = mapa_hilos.get("rit_a_hilos", {}).get(rit, [])
        mensajes_hilos = [
            mensaje
            for thread_id in hilos_rit
            for mensaje in mapa_hilos.get("hilos", {}).get(thread_id, [])
        ]

        _evaluar_acuerdo_y_pago(rit, mensajes_hilos, ruta_registro_causas, acciones)

        carpeta = causa.get("carpeta")
        if not carpeta:
            notas.append({
                "tipo": "sin_carpeta",
                "detalle": (
                    f"{rit}: la causa todavía no tiene carpeta asignada (sin demanda "
                    "encontrada aún) — se salteó la revisión de documentos nuevos."
                ),
            })
        else:
            tipo_audiencia = mapa_audiencias.get("rit_a_audiencia", {}).get(rit, {}).get("tipo")
            carpeta_causa = Path(carpeta)
            carpeta_destino = carpeta_destino_por_tipo_audiencia(carpeta_causa, tipo_audiencia)

            guardados = _guardar_adjuntos_confiables(mensajes_hilos, carpeta_destino)
            if guardados:
                con_documentos_nuevos += 1
                item = {
                    "rit": rit,
                    "titulo": f"{causa.get('demandante', '')} con {causa.get('empresa', '')}",
                    "detalle": f"{len(guardados)} documentos nuevos: {', '.join(g['filename'] for g in guardados)}",
                }
                if tipo_audiencia == "Juicio":
                    item["etiqueta"] = "Exhibición de documentos"
                items.append(item)
                bitacora_mod.registrar(
                    f"Goteo: se guardaron {len(guardados)} documentos nuevos "
                    f"({', '.join(g['filename'] for g in guardados)})"
                    + (", en Exhibición de documentos por audiencia de juicio" if tipo_audiencia == "Juicio" else ""),
                    rit=rit,
                )

            for adjunto_guardado in guardados:
                if not carpetas_mod.parece_eerr(adjunto_guardado["filename"]):
                    continue
                ceco = causa.get("ceco")
                fecha_despido = causa.get("fecha_despido")
                if ceco and fecha_despido:
                    registro_mod.registrar_eerr_recibido(ceco, fecha_despido, rit, ruta=ruta_registro_ceco)
                    identificados_eerr += 1

        # Paso 3h: siempre se guarda la fecha de revisión, haya o no
        # novedades — permite que la próxima corrida acote el barrido.
        registro_mod.registrar_causa(
            rit, {"goteo_ultima_revision": contexto_corrida["fecha_hoy"]}, ruta=ruta_registro_causas
        )

    resumen = {
        "fase": "goteo",
        "titular": _armar_titular(con_documentos_nuevos, identificados_eerr),
        "metricas": [
            {"etiqueta": "Causas revisadas", "valor": len(causas)},
            {"etiqueta": "Con documentos nuevos", "valor": con_documentos_nuevos},
            {"etiqueta": "Identificados como EERR", "valor": identificados_eerr},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _guardar_adjuntos_confiables(mensajes_hilos: list[dict], carpeta_destino: Path) -> list[dict]:
    """Guarda los adjuntos de `mensajes_hilos` que vengan de un remitente
    confiable, salvo `invite.ics` (ver subagentes/goteo.md, "Filtro de
    remitente confiable" y "Adjunto a excluir siempre"). `guardar_adjunto` ya
    hace de-dupe por nombre y por tamaño de bytes, así que no hace falta
    listar la carpeta antes. Devuelve la lista de adjuntos efectivamente
    guardados (con su `filename` original)."""
    guardados = []
    for mensaje in mensajes_hilos:
        if not es_remitente_confiable(mensaje.get("sender", "")):
            continue
        for adjunto in mensaje.get("adjuntos", []):
            nombre = adjunto["filename"]
            if nombre in NOMBRES_ADJUNTO_EXCLUIDOS:
                continue
            contenido = gmail_client.descargar_adjunto(mensaje["id"], adjunto["attachment_id"])
            if carpetas_mod.es_adjunto_firma(nombre, len(contenido)):
                continue
            resultado = carpetas_mod.guardar_adjunto(carpeta_destino, nombre, contenido)
            if resultado["guardado"]:
                guardados.append(adjunto)
    return guardados


def _leer_mapa_hilos(contexto_corrida: dict) -> dict:
    info = contexto_corrida.get("mapa_hilos") or {}
    ruta = info.get("ruta")
    if not ruta or not Path(ruta).exists():
        return {"rit_a_hilos": {}, "hilos": {}, "_notas": []}
    mapa = json.loads(Path(ruta).read_text(encoding="utf-8"))
    notas = []
    for entrada in mapa.get("truncado", []):
        notas.append({
            "tipo": "busqueda_truncada",
            "detalle": f"Búsqueda de {entrada['grupo']} quedó truncada ({entrada['total']} resultados)",
        })
    mapa["_notas"] = notas
    return mapa


def _armar_titular(con_documentos_nuevos: int, identificados_eerr: int) -> str:
    if con_documentos_nuevos == 0:
        return "Sin novedades"
    partes = [f"{con_documentos_nuevos} causas con documentos nuevos"]
    if identificados_eerr:
        partes.append(f"{identificados_eerr} identificados como EERR")
    return ", ".join(partes)
