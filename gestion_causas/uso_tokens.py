"""Telemetría de consumo de tokens de las llamadas a Claude.

Una línea JSON por llamada en un JSONL acumulativo — mismo criterio que
`bitacora.py` (append-only, auditable a mano), pero estructurado para poder
sumarlo. Es telemetría: `registrar` nunca lanza (ver `resumen` para leerlo).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

RUTA_USO_TOKENS = Path(__file__).parent / "uso_tokens.jsonl"


def registrar(evento: dict, ruta: Path = RUTA_USO_TOKENS) -> None:
    """Agrega `evento` como una línea JSON. Nunca lanza: si no se puede
    escribir (disco lleno, permisos, ruta inexistente), se descarta en
    silencio — para cuando se llama acá la llamada de razonamiento ya se
    pagó y su resultado tiene que llegar al llamador igual."""
    entrada = {"momento": datetime.now().isoformat(), **evento}
    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - telemetría nunca tumba una corrida
        pass


def resumen(ruta: Path = RUTA_USO_TOKENS, desde: str | None = None) -> dict:
    """Suma el JSONL. `desde` (AAAA-MM-DD) acota a los eventos de esa fecha
    en adelante. Una línea ilegible se saltea en vez de hacer fallar el
    resumen entero."""
    totales = {
        "llamadas": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "costo_usd": 0.0, "por_llamada": {},
    }
    if not Path(ruta).exists():
        return totales

    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        if desde and str(evento.get("momento", "")) < desde:
            continue
        totales["llamadas"] += 1
        for campo in ("input_tokens", "output_tokens",
                      "cache_creation_input_tokens", "cache_read_input_tokens"):
            totales[campo] += evento.get(campo) or 0
        totales["costo_usd"] += evento.get("costo_usd") or 0.0
        nombre = evento.get("llamada") or "desconocida"
        totales["por_llamada"][nombre] = totales["por_llamada"].get(nombre, 0) + 1

    return totales
