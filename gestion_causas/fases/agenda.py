"""Driver Python de la fase 'agenda' — Plan A (ver plan de implementación
docs/superpowers/plans/2026-09-17-driver-python-agenda-plan-a.md): pasos 1,
2, 3 y 5 de subagentes/agenda.md. El paso 4 (invocación de la skill
/minuta-laboral) es Agenda Plan B, todavía no migrado.

Revisa las causas activas, resuelve su próxima audiencia desde el mapa que
el orquestador ya armó para toda la corrida, y en el hito de 14 días
corridos antes de una audiencia Única o de Juicio deja un borrador de
ofrecimiento a Román. Nunca envía correos (solo deja borradores) ni toca el
calendario."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from gestion_causas import agenda as dias_mod
from gestion_causas import mapas as mapas_mod
from gestion_causas import reasoning
from gestion_causas import registro as registro_mod

TIPOS_CON_OFRECIMIENTO = {"Única", "Juicio"}

_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

SCHEMA_OFRECIMIENTO = {
    "type": "object",
    "properties": {
        "demandantes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "apellido": {"type": "string"},
                    "monto_recargo_30": {"type": "integer"},
                    "monto_afc": {"type": "integer"},
                },
                "required": ["apellido", "monto_recargo_30", "monto_afc"],
            },
        },
        "hay_discrepancia": {"type": "boolean"},
        "detalle_discrepancia": {"type": "string"},
    },
    "required": ["demandantes", "hay_discrepancia", "detalle_discrepancia"],
}


def _evaluar_montos_ofrecimiento(texto_cuadro_original: str, ruta_demanda: Path) -> dict:
    """Lee el PDF de la demanda (Claude la lee con su propia herramienta
    Read, en modo visión si es un escaneo sin capa de texto) para extraer,
    por cada demandante de la causa (puede ser uno o varios — no hay ningún
    campo estructurado con la lista de demandantes hoy), los montos exactos
    de Recargo legal 30% y Devolución de AFC. Coteja contra
    `texto_cuadro_original` (el cuerpo del correo con el cuadro resumen
    original, que trae "Conceptos demandados" como texto libre) y avisa si
    hay una discrepancia entre ambos, en vez de ocultarla — la demanda es
    la fuente legal (ver agenda.md paso 3c)."""
    contexto = {"texto_cuadro_original": texto_cuadro_original}
    tarea = (
        "Leé el archivo de la demanda indicado más abajo con tu herramienta Read (si es "
        "un PDF escaneado sin capa de texto, se lee en modo visión). Andá a la sección de "
        "Petitorio/Por tanto (normalmente al final) y extraé, por CADA demandante que "
        "aparezca en la causa: su apellido (tal como aparece en la identificación de las "
        "partes; si hay dos demandantes con el mismo apellido, agregá la inicial del "
        "nombre para distinguirlos), el monto exacto del Recargo legal 30% (recargo por "
        "término injustificado, art. 168 del Código del Trabajo), y el monto exacto de la "
        "Devolución de AFC (aporte al seguro de cesantía). Si la causa tiene un solo "
        "demandante, la lista trae un único elemento.\n\n"
        "Además, compará estos montos contra 'texto_cuadro_original' de más abajo (el "
        "cuerpo del correo con el cuadro resumen original de la demanda): si hay una "
        "diferencia entre lo que dice la demanda y lo que traía el cuadro, marcá "
        "hay_discrepancia=true y describila brevemente en detalle_discrepancia (si no hay "
        "diferencia — o el cuadro no menciona montos —, hay_discrepancia=false y "
        "detalle_discrepancia vacío)."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_OFRECIMIENTO, ruta_archivo=ruta_demanda)


def _debe_generar_ofrecimiento(causa: dict, audiencia: dict, fecha_hoy: str) -> bool:
    """True si corresponde generar hoy el borrador de ofrecimiento (paso 3
    de agenda.md): el tipo de audiencia es Única o Juicio, la causa no
    marcó `aplica_ofrecimiento: false` (causas que no son una demanda
    laboral estándar contra la empresa), no se generó ya
    (`oferta_borrador_creado`), y ya se cumplió — hoy o antes — el hito de
    14 días corridos antes de la audiencia."""
    if audiencia.get("tipo") not in TIPOS_CON_OFRECIMIENTO:
        return False
    if causa.get("aplica_ofrecimiento") is False:
        return False
    if causa.get("oferta_borrador_creado"):
        return False
    fecha_audiencia = audiencia.get("fecha")
    if not fecha_audiencia:
        return False
    hito = dias_mod.dias_corridos_antes(fecha_audiencia, 14)
    return date.fromisoformat(fecha_hoy) >= hito


def _formatear_pesos(monto: int) -> str:
    return f"${monto:,}".replace(",", ".")


def _formatear_fecha_larga(fecha_iso: str) -> str:
    fecha = date.fromisoformat(fecha_iso)
    return f"{fecha.day} de {_MESES_ES[fecha.month]} de {fecha.year}"


def _armar_cuerpo_ofrecimiento(
    demandantes: list[dict], tipo_audiencia: str, fecha_audiencia: str, dias_hasta_audiencia: int
) -> str:
    """Arma el cuerpo del borrador de ofrecimiento EXACTAMENTE con la
    plantilla vigente (memoria gestion_causas_borrador_ofrecimiento_formato,
    corregida el 18.08.2026 — no la plantilla desactualizada de
    agenda.md paso 3e): desglose de Recargo 30%/AFC/Total por cada
    demandante, sin agregar contexto de negociación ni escenarios
    alternativos. La pregunta final ofrece el 60% de (Recargo 30% + AFC)
    por persona, redondeado a un peso entero."""
    fecha_legible = _formatear_fecha_larga(fecha_audiencia)
    tipo_legible = "de juicio" if tipo_audiencia == "Juicio" else "única"

    bloques = []
    ofertas = []
    total_general = 0
    for demandante in demandantes:
        recargo = demandante["monto_recargo_30"]
        afc = demandante["monto_afc"]
        total_persona = recargo + afc
        total_general += total_persona
        apellido = demandante["apellido"]
        bloques.append(
            f"{apellido}:\n"
            f"Recargo 30%: {_formatear_pesos(recargo)}\n"
            f"Devolución AFC: {_formatear_pesos(afc)}\n"
            f"Total: {_formatear_pesos(total_persona)}"
        )
        ofertas.append((apellido, round(total_persona * 0.6)))

    cuerpo = (
        "Estimado Román:\n\n"
        f"En esta causa, con audiencia {tipo_legible} fijada para el {fecha_legible} "
        f"(en {dias_hasta_audiencia} días), se demanda lo siguiente:\n\n"
        + "\n\n".join(bloques) + "\n\n"
    )
    if len(demandantes) > 1:
        cuerpo += f"Total demandado (todos): {_formatear_pesos(total_general)}\n\n"

    if len(ofertas) == 1:
        apellido, oferta = ofertas[0]
        pregunta = (
            f"Por lo anterior, consulto si hago un ofrecimiento por {_formatear_pesos(oferta)} "
            f"para don/doña {apellido}, equivalente al 60% del total"
        )
    else:
        partes = [f"{_formatear_pesos(oferta)} para don/doña {apellido}" for apellido, oferta in ofertas]
        pregunta = (
            "Por lo anterior, consulto si hago un ofrecimiento por "
            + ", ".join(partes[:-1]) + " y " + partes[-1] + ", equivalente al 60% del total"
        )

    return cuerpo + pregunta + "\n\n\nAtentamente,"


def _armar_asunto_ofrecimiento(causa: dict, rit: str) -> str:
    apellido = causa.get("demandante", "")
    empresa = causa.get("empresa", "")
    return f'Demanda laboral "{apellido} con {empresa}" Rit {rit}'


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
) -> dict:
    causas = registro_mod.causas_para_goteo(
        hoy=contexto_corrida["fecha_hoy"], dias_ventana_post_audiencia=0, ruta=ruta_registro_causas
    )
    if not causas:
        return {
            "fase": "agenda",
            "titular": "Sin causas activas para revisar agenda",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    mapa_audiencias = mapas_mod.leer_mapa_audiencias(contexto_corrida)

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = []
    ofrecimientos_creados = 0
    sin_evento = 0

    for causa in causas:
        rit = causa["rit"]
        audiencia = mapa_audiencias.get("rit_a_audiencia", {}).get(rit)
        if not audiencia:
            sin_evento += 1
            continue
        if audiencia.get("tipo") == "Ambiguo":
            notas.append({
                "tipo": "audiencia_ambigua",
                "detalle": (
                    f"{rit}: no se pudo determinar el tipo de audiencia "
                    f"({audiencia.get('resumen', '')}) — revisar a mano."
                ),
            })
            continue

        # Paso 3 (hito de 14 días — borrador de ofrecimiento) se agrega en
        # una tarea siguiente de este plan.

    resumen = {
        "fase": "agenda",
        "titular": _armar_titular(ofrecimientos_creados),
        "metricas": [
            {"etiqueta": "Causas revisadas", "valor": len(causas)},
            {"etiqueta": "Borradores de ofrecimiento creados", "valor": ofrecimientos_creados},
            {"etiqueta": "Sin evento de calendario todavía", "valor": sin_evento},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _armar_titular(ofrecimientos_creados: int) -> str:
    if ofrecimientos_creados == 0:
        return "Sin novedades"
    plural = "es" if ofrecimientos_creados != 1 else ""
    return f"{ofrecimientos_creados} borrador{plural} de ofrecimiento creado{plural}"
