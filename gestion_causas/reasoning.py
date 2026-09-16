"""Único punto de contacto entre el driver Python de gestion_causas y Claude.

Se usa solo para los pasos que requieren razonamiento sobre texto libre (ver
docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md) — el
resto del flujo es Python puro. Cada llamada es acotada: un prompt corto con
el contexto mínimo necesario (nunca un .md completo ni un hilo/PDF sin
filtrar) y un schema de salida JSON fijo.
"""

from __future__ import annotations

import json
import shutil
import subprocess

TIMEOUT_SEGUNDOS = 120


def preguntar(tarea: str, contexto: dict, schema: dict, *, ejecutar=None) -> dict:
    """Le pide a Claude que resuelva `tarea` sobre `contexto`, devolviendo un
    dict que cumple `schema`. Reintenta una vez si la respuesta no es JSON
    válido (o si `ejecutar` lanza una excepción); si vuelve a fallar, devuelve
    `{"error": "<detalle>"}` en vez de lanzar una excepción — el llamador
    decide qué hacer con eso (típicamente anotarlo en `acciones` del resumen
    y seguir con la siguiente causa).

    `ejecutar` es inyectable para tests: recibe el prompt armado y devuelve el
    texto de salida de Claude. Por defecto corre `claude -p "<prompt>"`. Una
    excepción de `ejecutar` (timeout, binario no encontrado, exit code
    distinto de cero, etc.) nunca se propaga fuera de `preguntar`.
    """
    ejecutar = ejecutar or _ejecutar_claude

    error_previo: str | None = None
    salida = ""
    for intento in range(2):
        prompt = _armar_prompt(tarea, contexto, schema, error_previo=error_previo)
        try:
            salida = ejecutar(prompt)
        except Exception as exc:  # noqa: BLE001 - una llamada externa (subprocess) no debe tumbar el batch
            error_previo = f"{type(exc).__name__}: {exc}"
            continue

        resultado = _parsear_json(salida)
        if resultado is not None:
            return resultado

        error_previo = salida

    return {
        "error": (
            "Claude no devolvió JSON válido tras 2 intentos. "
            f"Última respuesta: {error_previo[:500]!r}"
        )
    }


def _armar_prompt(tarea: str, contexto: dict, schema: dict, error_previo: str | None = None) -> str:
    partes = [
        tarea,
        "",
        "Contexto (JSON):",
        json.dumps(contexto, ensure_ascii=False, indent=2),
        "",
    ]
    if error_previo is not None:
        partes += [f"Tu respuesta anterior no era JSON válido: {error_previo!r}", ""]
    partes += [
        "Responde ÚNICAMENTE con un objeto JSON válido que cumpla este schema, "
        "sin texto antes ni después, y sin envolverlo en ```:",
        json.dumps(schema, ensure_ascii=False, indent=2),
    ]
    return "\n".join(partes)


def _parsear_json(texto: str) -> dict | None:
    texto = texto.strip()
    if texto.startswith("```"):
        sin_cerca = texto.strip("`")
        texto = sin_cerca.split("\n", 1)[1] if "\n" in sin_cerca else sin_cerca
        if texto.lower().startswith("json"):
            texto = texto[4:]
        texto = texto.strip()
    try:
        return json.loads(texto)
    except ValueError:
        return None


def _ejecutar_claude(prompt: str) -> str:
    """Corre `claude -p "<prompt>"`. En Windows, `claude` es un shim `.CMD` de
    npm que `subprocess.run` no encuentra si se le pasa el nombre desnudo (sin
    pasar por una shell) — hay que resolver la ruta completa con
    `shutil.which` primero (confirmado en una corrida real: sin esto, todas
    las llamadas fallaban con `FileNotFoundError: [WinError 2]`)."""
    ejecutable = shutil.which("claude")
    if ejecutable is None:
        raise RuntimeError("No se encontró el ejecutable 'claude' en el PATH.")
    resultado = subprocess.run(
        [ejecutable, "-p", prompt],
        capture_output=True, text=True, timeout=TIMEOUT_SEGUNDOS, check=False,
    )
    if resultado.returncode != 0:
        raise RuntimeError(
            f"claude -p terminó con código {resultado.returncode}: {resultado.stderr[:500]}"
        )
    return resultado.stdout
