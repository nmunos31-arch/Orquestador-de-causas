"""Único punto de contacto entre el driver Python de gestion_causas y Claude.

Se usa solo para los pasos que requieren razonamiento sobre texto libre (ver
docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md) — el
resto del flujo es Python puro. Cada llamada es acotada: un prompt corto con
el contexto mínimo necesario (nunca un .md completo ni un hilo/PDF sin
filtrar) y un schema de salida JSON fijo.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path

from gestion_causas import cache_razonamiento
from gestion_causas import uso_tokens

TIMEOUT_SEGUNDOS = 180
TIMEOUT_SKILL_SEGUNDOS = 1800

# Modelo para las clasificaciones acotadas (`goteo.acuerdo_y_pago`,
# `seguimiento.clasificar_pedido`): devuelven 2-3 campos con un schema fijo
# sobre texto corto, no hace falta el modelo más caro. Las que SÍ lo
# necesitan (leer una demanda escaneada en modo visión y extraer montos
# exactos: `smu.ajustes_demanda`, `agenda.montos_ofrecimiento`) no pasan
# `modelo` y siguen con el default del CLI.
#
# Vacío ("") = default del CLI. Se puede forzar por entorno sin tocar
# código, para comparar calidad/costo contra los números de uso_tokens.py:
#   GESTION_CAUSAS_MODELO_CLASIFICACION=""  -> vuelve al default
MODELO_CLASIFICACION = os.environ.get(
    "GESTION_CAUSAS_MODELO_CLASIFICACION", "claude-haiku-4-5-20251001"
)

# `_ejecutar_claude` no necesita nada de esto: ni skills (no se invoca
# ninguna con /), ni la config de settings del proyecto/usuario (los
# permisos ya se fijan explícitamente por llamada). Sin apagarlo, cada
# proceso `claude -p` nuevo vuelve a cargar y cachear ese contexto fijo
# desde cero (ver docstring de `_ejecutar_claude`).
#
# `--output-format json` devuelve un envoltorio con el `usage` real de la
# llamada (ver uso_tokens.py). Sin esto no hay forma de saber qué cuesta
# cada punto de razonamiento — y todo lo que se optimice encima es una
# estimación a ciegas.
_FLAGS_MINIMOS = ["--disable-slash-commands", "--setting-sources", "", "--output-format", "json"]


def preguntar(
    tarea: str, contexto: dict, schema: dict, *, ejecutar=None, ruta_archivo=None,
    etiqueta: str | None = None, cachear: bool = False, modelo: str | None = None,
) -> dict:
    """Le pide a Claude que resuelva `tarea` sobre `contexto`, devolviendo un
    dict que cumple `schema`. Reintenta una vez si la respuesta no es JSON
    válido (o si `ejecutar` lanza una excepción); si vuelve a fallar, devuelve
    `{"error": "<detalle>"}` en vez de lanzar una excepción — el llamador
    decide qué hacer con eso (típicamente anotarlo en `acciones` del resumen
    y seguir con la siguiente causa).

    `ejecutar` es inyectable para tests: recibe el prompt armado y devuelve el
    texto de salida de Claude. Por defecto corre `claude -p`, pasando el
    prompt por stdin (no como argumento de línea de comandos, ver
    `_ejecutar_claude`). Una excepción de `ejecutar` (timeout, binario no
    encontrado, exit code distinto de cero, etc.) nunca se propaga fuera de
    `preguntar`.

    `ruta_archivo` (opcional) deja que Claude lea ese archivo puntual con su
    propia herramienta `Read` (necesario para PDFs, incluidos escaneos que se
    leen en modo visión) en vez de intentar meter su contenido en `contexto`
    como texto. Cuando se entrega, se pasa como segundo argumento a
    `ejecutar` (`ejecutar(prompt, ruta_archivo=ruta_archivo)`); si no se
    entrega, `ejecutar` se llama igual que siempre (`ejecutar(prompt)`), así
    que ningún llamador existente que no use `ruta_archivo` se ve afectado.
    """
    ejecutar = ejecutar or functools.partial(_ejecutar_claude, etiqueta=etiqueta, modelo=modelo)

    # El caché se consulta ANTES de armar el prompt: la clave depende de
    # (tarea, contexto), no del prompt final, para que agregar un campo al
    # formato del prompt (ej. la línea de `ruta_archivo`) no invalide todo
    # el caché de golpe.
    clave_cache = cache_razonamiento.clave(tarea, contexto) if cachear else None
    if clave_cache is not None:
        cacheado = cache_razonamiento.obtener(clave_cache, ruta=cache_razonamiento.RUTA_CACHE)
        if cacheado is not None:
            return cacheado

    error_previo: str | None = None
    salida = ""
    for intento in range(2):
        prompt = _armar_prompt(tarea, contexto, schema, error_previo=error_previo, ruta_archivo=ruta_archivo)
        try:
            if ruta_archivo is not None:
                salida = ejecutar(prompt, ruta_archivo=ruta_archivo)
            else:
                salida = ejecutar(prompt)
        except Exception as exc:  # noqa: BLE001 - una llamada externa (subprocess) no debe tumbar el batch
            error_previo = f"{type(exc).__name__}: {exc}"
            continue

        resultado = _parsear_json(salida)
        if resultado is not None:
            # Nunca se cachea un `{"error": ...}`: una entrada así
            # envenenaría la causa por DIAS_VIGENCIA. Solo llegan acá
            # respuestas que parsearon bien, pero el modelo puede haber
            # devuelto un objeto con la clave "error" por su cuenta.
            if clave_cache is not None and "error" not in resultado:
                cache_razonamiento.guardar(
                    clave_cache, resultado, ruta=cache_razonamiento.RUTA_CACHE
                )
            return resultado

        error_previo = salida

    return {
        "error": (
            "Claude no devolvió JSON válido tras 2 intentos. "
            f"Última respuesta: {error_previo[:500]!r}"
        )
    }


def invocar_skill(
    prompt: str, carpeta: Path, *, ejecutar=None, timeout: int = TIMEOUT_SKILL_SEGUNDOS
) -> dict:
    """Invoca una skill de Claude Code (ej. `/minuta-laboral`) dejándola operar
    con permisos amplios (`Read`, `Write`, `Bash`) pero acotados a `carpeta` —
    a diferencia de `preguntar`, que solo permite `Read` porque su salida es
    JSON acotado por schema. Se usa para pasos que producen archivos (una
    skill que genera un `.docx`/PDF), no una respuesta estructurada.

    No parsea JSON ni reintenta: un prompt de skill no es determinístico de
    la misma forma que un JSON mal formado, y reintentar podría duplicar
    trabajo de una skill que ya escribió archivos parciales. Devuelve
    `{"ok": True, "salida": <stdout>}` si el subprocess termina con exit code
    0, o `{"error": "<detalle>"}` (sin lanzar excepción) si `ejecutar` falla
    (timeout, binario no encontrado, exit code distinto de cero, etc.) — el
    llamador decide qué hacer, típicamente anotarlo en `acciones` del resumen
    y no marcar el paso como completado, para que se reintente en la corrida
    siguiente."""
    ejecutar = ejecutar or _ejecutar_claude_skill
    try:
        salida = ejecutar(prompt, carpeta, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - una llamada externa (subprocess) no debe tumbar el batch
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "salida": salida}


def _ejecutar_claude_skill(prompt: str, carpeta: Path, *, timeout: int) -> str:
    """Mismo patrón de invocación que `_ejecutar_claude` (resolver `claude`
    con `shutil.which`, prompt por stdin, `encoding="utf-8"` explícito — ver
    docstring de `_ejecutar_claude` para el detalle de cada uno), pero con
    `--allowedTools "Read,Write,Bash"` en vez de solo `Read`: la skill
    instala paquetes de Python (`pymupdf`, `pypdf`) y escribe el `.docx`/PDF
    generado en `carpeta`. Nunca se usa `--dangerously-skip-permissions`."""
    ejecutable = shutil.which("claude")
    if ejecutable is None:
        raise RuntimeError("No se encontró el ejecutable 'claude' en el PATH.")

    argv = [
        ejecutable, "-p",
        "--output-format", "json",
        "--allowedTools", "Read,Write,Bash",
        "--add-dir", str(carpeta),
        "--strict-mcp-config",
    ]

    resultado = subprocess.run(
        argv,
        input=prompt,
        capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False,
    )
    if resultado.returncode != 0:
        detalle = resultado.stderr[:500] or resultado.stdout[:500]
        raise RuntimeError(f"claude -p (skill) terminó con código {resultado.returncode}: {detalle}")
    return _desenvolver_salida(resultado.stdout, etiqueta="minuta-laboral")


def _armar_prompt(
    tarea: str, contexto: dict, schema: dict, error_previo: str | None = None, ruta_archivo=None
) -> str:
    partes = [tarea, ""]
    if ruta_archivo is not None:
        partes += [
            f"Antes de responder, usá tu herramienta Read para leer el archivo en esta "
            f"ruta absoluta: {ruta_archivo}",
            "",
        ]
    partes += [
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


def _ejecutar_claude(prompt: str, ruta_archivo=None, etiqueta: str | None = None,
                     modelo: str | None = None) -> str:
    """Corre `claude -p`, pasando el prompt por stdin (no como argumento de
    línea de comandos) — en Windows, un prompt largo (el contexto de una
    causa con muchos correos puede ser de decenas de miles de caracteres)
    excede el límite de longitud de línea de comandos del sistema operativo
    si se pasa como argv, y falla con `WinError 206` / "línea de comandos
    demasiado larga" (confirmado en una corrida real). Por stdin no hay ese
    límite.

    En Windows, `claude` es un shim `.CMD` de npm que `subprocess.run` no
    encuentra si se le pasa el nombre desnudo (sin pasar por una shell) —
    hay que resolver la ruta completa con `shutil.which` primero (también
    confirmado en una corrida real: sin esto, todas las llamadas fallaban
    con `FileNotFoundError: [WinError 2]`).

    Se fuerza `encoding="utf-8"` explícitamente: con `text=True` sin
    `encoding`, Python usa la codepage por defecto del sistema operativo
    (en Windows, típicamente `cp1252`, no UTF-8) para escribir el stdin en
    el hilo interno `_writerthread` de `subprocess`. El contexto real de
    una causa suele traer caracteres fuera de ese rango (guiones no
    separables, flechas, etc.), lo que hace fallar la escritura en ese
    hilo en silencio: `claude -p` no recibe stdin, agota el timeout de
    espera y termina con exit code distinto de cero (confirmado en una
    corrida real, con la mitad de las llamadas de razonamiento fallando
    así).

    Si se entrega `ruta_archivo`, se agrega `--allowedTools Read --add-dir
    <carpeta_del_archivo>` — el mínimo privilegio necesario para que Claude
    pueda leer ESE archivo puntual con su herramienta Read (soporta PDFs,
    incluido modo visión para escaneos sin capa de texto) sin habilitar
    ninguna otra herramienta ni acceso a ningún otro directorio. Nunca se
    usa `--dangerously-skip-permissions`.

    Siempre se agregan además los flags de `_FLAGS_MINIMOS`: esta llamada
    solo necesita texto de entrada y JSON de salida (o, con `ruta_archivo`,
    además `Read`) — nunca MCP servers, skills, ni la config de
    settings/CLAUDE.md del proyecto o el usuario. Sin esto, cada invocación
    de `claude -p` (un proceso nuevo y sin caché compartido con las demás)
    paga de nuevo el costo de cargar todo ese contexto: confirmado en una
    corrida real que ~99% de los tokens consumidos por 24 llamadas de
    razonamiento (~1.3M) eran `cache_creation`/`cache_read` de ese contexto
    fijo, no contenido de la tarea — con estos flags bajó a ~25% en una
    prueba equivalente."""
    ejecutable = shutil.which("claude")
    if ejecutable is None:
        raise RuntimeError("No se encontró el ejecutable 'claude' en el PATH.")

    argv = [ejecutable, "-p", *_FLAGS_MINIMOS]
    if modelo:
        argv += ["--model", modelo]
    if ruta_archivo is not None:
        settings_lectura_acotada = json.dumps({"permissions": {"deny": ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]}})
        argv += [
            "--allowedTools", "Read",
            "--add-dir", str(Path(ruta_archivo).parent),
            "--settings", settings_lectura_acotada,
            "--strict-mcp-config",
        ]
    else:
        argv += ["--tools", "", "--strict-mcp-config"]

    resultado = subprocess.run(
        argv,
        input=prompt,
        capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SEGUNDOS, check=False,
    )
    if resultado.returncode != 0:
        # claude -p no siempre escribe el motivo del fallo en stderr — un
        # prompt que excede su límite de tamaño imprime "Prompt is too long"
        # por stdout con stderr vacío (confirmado en una corrida real con un
        # hilo de correo de ~800KB), y mirar solo stderr dejaba el error
        # vacío e inútil para diagnosticar. Preferimos stderr cuando tiene
        # contenido (suele ser más específico), y caemos a stdout si no.
        detalle = resultado.stderr[:500] or resultado.stdout[:500]
        raise RuntimeError(f"claude -p terminó con código {resultado.returncode}: {detalle}")
    return _desenvolver_salida(resultado.stdout, etiqueta=etiqueta)


def _desenvolver_salida(stdout: str, *, etiqueta: str | None = None) -> str:
    """Parsea el envoltorio de `--output-format json`: registra el `usage` y
    devuelve el texto de `result`.

    Dos casos que NO son "la respuesta del modelo":
    - `is_error: true` con exit code 0 — un rechazo o un prompt demasiado
      largo no siempre sale con código distinto de cero, y sin esto el texto
      del error se devolvería como si fuera la respuesta (y después fallaría
      como "JSON inválido", gatillando el reintento, que lo paga de nuevo).
    - stdout que no es JSON — si una versión del CLI deja de envolver la
      salida, se devuelve el stdout crudo en vez de perder la respuesta.
    """
    try:
        envoltorio = json.loads(stdout)
    except ValueError:
        return stdout
    if not isinstance(envoltorio, dict) or "result" not in envoltorio:
        return stdout

    uso = envoltorio.get("usage") or {}
    uso_tokens.registrar(
        {
            "llamada": etiqueta or "desconocida",
            "input_tokens": uso.get("input_tokens"),
            "output_tokens": uso.get("output_tokens"),
            "cache_creation_input_tokens": uso.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": uso.get("cache_read_input_tokens"),
            "costo_usd": envoltorio.get("total_cost_usd"),
            "modelo": envoltorio.get("model"),
        },
        ruta=uso_tokens.RUTA_USO_TOKENS,
    )

    if envoltorio.get("is_error"):
        raise RuntimeError(f"claude -p devolvió is_error: {str(envoltorio.get('result'))[:500]}")
    return envoltorio["result"]
