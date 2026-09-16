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
