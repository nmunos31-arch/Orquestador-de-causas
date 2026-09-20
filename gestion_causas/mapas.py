"""Lectura de los mapas que el ciclo arma una sola vez por corrida
(ver ciclo.py) y que varias fases reusan, para que nunca diverjan en
cómo resuelven la misma pregunta — ej. `goteo` y `agenda` deciden el tipo de
audiencia (Única/Preparatoria/Juicio/Ambiguo) de un RIT con el mismo
criterio, leyendo el mismo archivo."""

from __future__ import annotations

import json
from pathlib import Path


def leer_mapa_audiencias(contexto_corrida: dict) -> dict:
    """Lee el mapa RIT -> audiencia ({"fecha", "resumen", "tipo"}) que el
    ciclo ya resolvió para toda la corrida (paso 0 de agenda.md / paso
    3a de goteo.md). Si el contexto no trae la ruta, o el archivo no existe
    (ej. corriendo la fase suelta sin ciclo), devuelve un mapa vacío
    en vez de fallar."""
    info = contexto_corrida.get("mapa_audiencias") or {}
    ruta = info.get("ruta")
    if not ruta or not Path(ruta).exists():
        return {"rit_a_audiencia": {}}
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def leer_mapa_hilos(contexto_corrida: dict) -> dict:
    """Lee el barrido combinado de Gmail que el ciclo ya armó para toda
    la corrida (`rit_a_hilos`, `hilos`) — mismo mapa que usa `goteo.py` paso 2
    y `seguimiento.py` paso 3b para el cruce por RIT sin volver a golpear
    Gmail. Si el contexto no trae la ruta, o el archivo no existe (ej.
    corriendo la fase suelta sin ciclo), devuelve un mapa vacío en vez
    de fallar; `_notas` trae una nota por cada búsqueda que quedó truncada."""
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
