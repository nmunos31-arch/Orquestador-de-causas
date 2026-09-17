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
from gestion_causas import registro as registro_mod

TIPOS_CON_OFRECIMIENTO = {"Única", "Juicio"}


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
