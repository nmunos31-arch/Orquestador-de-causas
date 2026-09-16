"""Driver Python de la fase 'smu' (Fase 1-2, ingesta y registro — ver spec
en docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md
y, como referencia histórica de las reglas completas, subagentes/smu.md).

Alcance de este módulo (ver plan
docs/superpowers/plans/2026-09-16-driver-python-smu-ingesta.md): busca
correos nuevos de demandas de las 6 empresas del proyecto, extrae el
cuadro-resumen, filtra duplicados, crea la carpeta, guarda la demanda,
escribe la fila del Excel de Juicios Vigentes, registra la causa, etiqueta
el hilo y lo marca procesado. NO arma el borrador de documentos a solicitar
(ver Plan B, un plan separado) — no requiere que orquestador.py haya armado
ningún mapa previo, a diferencia de goteo."""

from __future__ import annotations

from pathlib import Path

from actualizar_informe_juicios import RUTA_EXCEL_JUICIOS, agregar_causa
from gestion_causas import bitacora as bitacora_mod
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import registro as registro_mod
from gestion_causas import reasoning
from gestion_causas.cuadro_resumen import cuadro_completo, extraer_campos_cuadro
from gestion_causas.empresas import normalizar_empresa
from gestion_causas.gmail_client import COLOR_POR_EMPRESA, EMPRESAS_SIN_EXCEL, ETIQUETA_PROCESADO
from gestion_causas.seguimiento import extraer_direccion

QUERY_CANDIDATOS = (
    'from:(smu.cl OR sb.cl OR gomezyriesco.cl) subject:DEMANDA '
    'after:2026/07/01 -label:"Procesado-GestionCausas"'
)


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
) -> dict:
    hilos = gmail_client.buscar_hilos(QUERY_CANDIDATOS, max_resultados=50)
    if not hilos:
        return {
            "fase": "smu",
            "titular": "Sin correos nuevos",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = []
    causas_nuevas = 0

    for hilo_resumen in hilos:
        thread_id = hilo_resumen["id"]
        mensajes = gmail_client.leer_hilo(thread_id)
        if not mensajes:
            continue
        primer_mensaje = mensajes[0]

        origen = _origen_cadena(primer_mensaje)
        if origen.get("error"):
            acciones.append({
                "rit": None,
                "que": f"No se pudo evaluar el origen de un hilo automáticamente: {origen['error']}",
                "urgencia": "media",
            })
            continue
        if not origen["valida"]:
            continue

        campos = extraer_campos_cuadro(primer_mensaje.get("cuerpo_texto", ""))
        if not cuadro_completo(campos):
            notas.append({
                "tipo": "cuadro_incompleto",
                "detalle": f"Hilo {thread_id}: cuadro incompleto o mal formado (falta Rit, Tribunal o Cuantía) — revisar a mano.",
            })
            continue

        empresa = normalizar_empresa(campos.get("demandada", ""))
        if empresa is None:
            continue

        rit = campos["rit"]
        if registro_mod.causa_ya_registrada(rit, ruta=ruta_registro_causas):
            continue

        apellido = campos.get("demandante", "").split()[-1].title() if campos.get("demandante") else rit

        carpeta_existente = carpetas_mod.buscar_carpeta_existente_por_rit(rit)
        carpeta = carpeta_existente or carpetas_mod.crear_carpeta_causa(apellido, empresa, rit)

        demanda_guardada = False
        for adjunto in primer_mensaje.get("adjuntos", []):
            if not adjunto["filename"].lower().endswith(".pdf"):
                continue
            contenido = gmail_client.descargar_adjunto(primer_mensaje["id"], adjunto["attachment_id"])
            if carpetas_mod.es_adjunto_firma(adjunto["filename"], len(contenido)):
                continue
            resultado = carpetas_mod.guardar_adjunto(carpeta, "demanda.pdf", contenido)
            demanda_guardada = resultado["guardado"] or demanda_guardada
            break

        if not demanda_guardada:
            notas.append({
                "tipo": "sin_demanda",
                "detalle": f"{rit}: no se encontró un PDF de demanda en el correo — súbela a mano.",
            })

        # El resumen narrativo solo hace falta para la fila del Excel — Preunic y
        # Salcobrand nunca tienen fila (ver EMPRESAS_SIN_EXCEL), así que ni siquiera
        # vale la pena gastar el llamado a Claude para esos dos casos.
        if empresa not in EMPRESAS_SIN_EXCEL:
            deteccion_resumen = _generar_resumen_narrativo(campos, primer_mensaje.get("cuerpo_texto", ""))
            if deteccion_resumen.get("error"):
                acciones.append({
                    "rit": rit,
                    "que": f"No se pudo redactar el Resumen del Excel automáticamente: {deteccion_resumen['error']}",
                    "urgencia": "media",
                })
            else:
                datos_excel = {
                    "juzgado": campos.get("tribunal", ""),
                    "materia": campos.get("materia", ""),
                    "causa": rit,
                    "cuantia": campos.get("cuantia", ""),
                    "resumen": deteccion_resumen.get("resumen", ""),
                }
                try:
                    agregar_causa(RUTA_EXCEL_JUICIOS, datos_excel)
                except PermissionError:
                    acciones.append({
                        "rit": rit,
                        "que": "El Excel de Juicios Vigentes está abierto/bloqueado — no se pudo escribir la fila. Se reintenta en la próxima corrida.",
                        "urgencia": "alta",
                    })

        registro_mod.registrar_causa(
            rit,
            {
                "empresa": empresa,
                "demandante": campos.get("demandante", ""),
                "carpeta": str(carpeta),
                "thread_id": thread_id,
                "tiene_demanda": demanda_guardada,
                "aplica_excel": empresa not in EMPRESAS_SIN_EXCEL,
            },
            ruta=ruta_registro_causas,
        )

        color = COLOR_POR_EMPRESA.get(empresa)
        label_empresa = gmail_client.obtener_o_crear_etiqueta(empresa, color=color)
        gmail_client.aplicar_etiqueta_a_hilo(thread_id, label_empresa)
        label_procesado = gmail_client.obtener_o_crear_etiqueta(ETIQUETA_PROCESADO)
        gmail_client.aplicar_etiqueta_a_hilo(thread_id, label_procesado)

        bitacora_mod.registrar(
            f"Causa nueva registrada ({empresa}), carpeta '{carpeta.name}'"
            + ("" if demanda_guardada else " — sin demanda adjunta, súbela a mano"),
            rit=rit,
        )

        items.append({"rit": rit, "titulo": f"{empresa} - {campos.get('demandante', '').title()}"})
        causas_nuevas += 1

    resumen = {
        "fase": "smu",
        "titular": _armar_titular(causas_nuevas),
        "metricas": [
            {"etiqueta": "Causas nuevas", "valor": causas_nuevas},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _armar_titular(causas_nuevas: int) -> str:
    if causas_nuevas == 0:
        return "Sin causas nuevas"
    return f"{causas_nuevas} causas nuevas registradas"


SCHEMA_RESUMEN = {
    "type": "object",
    "properties": {"resumen": {"type": "string"}},
    "required": ["resumen"],
}


def _generar_resumen_narrativo(campos: dict, cuerpo_texto_completo: str) -> dict:
    """Redacta el párrafo "Resumen" del Excel de Juicios Vigentes siguiendo
    la plantilla exacta de docs/2026-07-07-informe-juicios-email-design.md
    (sección "Plantilla del Resumen"). `cuerpo_texto_completo` se pasa
    entero (no solo los campos ya extraídos) porque el bloque "Hechos" y
    "Conceptos demandados" son texto libre, sin acotar con regex."""
    contexto = {"campos_extraidos": campos, "cuerpo_completo_del_correo": cuerpo_texto_completo}
    tarea = (
        'Redactá el párrafo "Resumen" de una fila del Excel de Juicios Vigentes, '
        "siguiendo EXACTAMENTE esta plantilla (reemplazando lo que va entre corchetes, "
        "sin agregar ni quitar nada de la estructura):\n\n"
        '"Demanda de despido injustificado y cobro de prestaciones laborales interpuesta '
        "por [Demandante(s), formato Nombre Propio] por haber sido "
        "[desvinculad[o/a/os/as]] el [fecha de despido] por [causal]. Solicita el pago "
        "total de [Cuantía formateada como $#.###.###] por [conceptos demandados, sin "
        'montos parciales]."\n\n'
        "Reglas: Demandante(s) en formato Nombre Propio (no mayúsculas sostenidas), "
        "varios demandantes separados por comas y 'y' antes del último. Concordancia de "
        "género según el nombre (singular) o plural coherente con el grupo. Fecha y "
        "causal de despido se sacan del bloque 'Hechos' del cuerpo del correo. Formato de "
        "fecha: día con dos dígitos, mes en palabras y minúsculas, año completo (ej. '08 "
        "de enero de 2026'). Conceptos demandados: solo las etiquetas de los conceptos, "
        "sin repetir montos parciales."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_RESUMEN)


SCHEMA_ORIGEN_CADENA = {
    "type": "object",
    "properties": {
        "es_reenvio_de_cuadro": {"type": "boolean"},
        "justificacion": {"type": "string"},
    },
    "required": ["es_reenvio_de_cuadro", "justificacion"],
}


def _evaluar_origen_gomezyriesco(primer_mensaje: dict) -> dict:
    """El primer mensaje del hilo es de @gomezyriesco.cl — decide si es un
    reenvío/acuse de recibo que cita (texto citado, ej. con '>') un
    cuadro-resumen firmado por alguien de @smu.cl/@sb.cl (cadena VÁLIDA), o
    si es Nico/Román iniciando una conversación interna (cadena NO válida,
    la usa la fase 'agenda', no esta)."""
    contexto = {
        "remitente": primer_mensaje.get("sender", ""),
        "asunto": primer_mensaje.get("subject", ""),
        "cuerpo": primer_mensaje.get("cuerpo_texto", ""),
    }
    tarea = (
        "El primer mensaje de este hilo de correo lo envió alguien de dominio "
        "@gomezyriesco.cl. Decidí si es un reenvío o acuse de recibo corto que cita, "
        "dentro del cuerpo (texto citado, típicamente con '>' o similar), un "
        "cuadro-resumen completo de una causa laboral (campos como Rit, Tribunal, "
        "Demandante, etc.) firmado originalmente por alguien de dominio @smu.cl o "
        "@sb.cl — en ese caso es una cadena VÁLIDA. Si en cambio es alguien de "
        "gomezyriesco.cl iniciando una conversación (ej. preguntando sobre estrategia "
        "de una causa ya conocida), sin ningún cuadro-resumen citado, es una cadena "
        "INTERNA, no válida para esta tarea."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_ORIGEN_CADENA)


def _dominio(remitente: str) -> str:
    direccion = extraer_direccion(remitente)
    return direccion.rsplit("@", 1)[1].lower() if "@" in direccion else ""


def _origen_cadena(primer_mensaje: dict) -> dict:
    """Devuelve {"valida": True|False, "error": <str, opcional>}."""
    dominio = _dominio(primer_mensaje.get("sender", ""))
    if dominio in ("smu.cl", "sb.cl"):
        return {"valida": True}
    if dominio == "gomezyriesco.cl":
        deteccion = _evaluar_origen_gomezyriesco(primer_mensaje)
        if deteccion.get("error"):
            return {"valida": False, "error": deteccion["error"]}
        return {"valida": bool(deteccion.get("es_reenvio_de_cuadro"))}
    return {"valida": False}
