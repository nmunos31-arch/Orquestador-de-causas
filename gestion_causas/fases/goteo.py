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
    mapa_audiencias = _leer_mapa_audiencias(contexto_corrida)

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


def _leer_mapa_audiencias(contexto_corrida: dict) -> dict:
    info = contexto_corrida.get("mapa_audiencias") or {}
    ruta = info.get("ruta")
    if not ruta or not Path(ruta).exists():
        return {"rit_a_audiencia": {}}
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _armar_titular(con_documentos_nuevos: int, identificados_eerr: int) -> str:
    if con_documentos_nuevos == 0:
        return "Sin novedades"
    partes = [f"{con_documentos_nuevos} causas con documentos nuevos"]
    if identificados_eerr:
        partes.append(f"{identificados_eerr} identificados como EERR")
    return ", ".join(partes)
