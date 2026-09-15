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
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import registro as registro_mod
from gestion_causas import reasoning
from gestion_causas.carpetas import carpeta_destino_por_tipo_audiencia
from gestion_causas.seguimiento import es_remitente_confiable

NOMBRES_ADJUNTO_EXCLUIDOS = {"invite.ics"}


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    causas = registro_mod.causas_para_goteo(ruta=ruta_registro_causas)
    if not causas:
        return {
            "fase": "goteo",
            "titular": "Sin causas activas para revisar",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    return {
        "fase": "goteo",
        "titular": f"{len(causas)} causas activas revisadas",
        "metricas": [{"etiqueta": "Causas revisadas", "valor": len(causas)}],
        "items": [],
        "acciones": [],
        "notas": [],
    }
