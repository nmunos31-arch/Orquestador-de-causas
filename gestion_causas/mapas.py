"""Lectura de los mapas que el orquestador arma una sola vez por corrida
(ver orquestador.py) y que varias fases reusan, para que nunca diverjan en
cómo resuelven la misma pregunta — ej. `goteo` y `agenda` deciden el tipo de
audiencia (Única/Preparatoria/Juicio/Ambiguo) de un RIT con el mismo
criterio, leyendo el mismo archivo."""

from __future__ import annotations

import json
from pathlib import Path


def leer_mapa_audiencias(contexto_corrida: dict) -> dict:
    """Lee el mapa RIT -> audiencia ({"fecha", "resumen", "tipo"}) que el
    orquestador ya resolvió para toda la corrida (paso 0 de agenda.md / paso
    3a de goteo.md). Si el contexto no trae la ruta, o el archivo no existe
    (ej. corriendo la fase suelta sin orquestador), devuelve un mapa vacío
    en vez de fallar."""
    info = contexto_corrida.get("mapa_audiencias") or {}
    ruta = info.get("ruta")
    if not ruta or not Path(ruta).exists():
        return {"rit_a_audiencia": {}}
    return json.loads(Path(ruta).read_text(encoding="utf-8"))
