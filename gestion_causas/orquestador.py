"""Driver del orquestador de gestion_causas, en Python.

Reemplazo completo de la tarea programada `gestion-causas-orquestador`
(ver docs en docs/superpowers/plans/ y, como referencia histórica del
contrato paso a paso, orquestador/SKILL.md), salvo el paso 1 ("contexto de
la corrida"), que sigue siendo un comando de CLI aparte
(`python -m gestion_causas.cli contexto-corrida`) — `correr()` requiere que
ya se haya corrido antes.

`correr_y_enviar_panel()` es el punto de entrada completo: despacha las 5
fases ('smu', 'goteo', 'agenda', 'seguimiento', 'calendario'), arma el
resumen de la corrida, revisa si quedaron borradores de documentos sin
enviar de corridas anteriores, genera el HTML del panel y lo envía por
correo a nmunoz@gomezyriesco.cl — igual que hacían los pasos 3 a 6 del
SKILL.md viejo, pero llamando directo a las funciones puro-Python
(`panel.generar_panel_html`, `gmail_personal_client.enviar_panel_estado`)
en vez de escribir archivos temporales intermedios entre llamadas de CLI
por separado (ya no hace falta: todo corre en el mismo proceso).

`seguimiento` y `calendario` solo se despachan en la corrida de la mañana
(`contexto_corrida["corrida"] == "manana"`, campo que ya arma
`cli.cmd_contexto_corrida`): sus umbrales son en días hábiles (seguimiento)
o solo corren los lunes (calendario, que además se autoevalúa internamente
con `es_lunes` — este filtro por "corrida" es una capa extra para no
llamarlas de más en las corridas de la tarde/noche)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import cli as cli_mod
from gestion_causas import gmail_personal_client
from gestion_causas import panel as panel_mod
from gestion_causas import registro as registro_mod
from gestion_causas import uso_tokens
from gestion_causas.fases import agenda as fases_agenda
from gestion_causas.fases import calendario as fases_calendario
from gestion_causas.fases import goteo as fases_goteo
from gestion_causas.fases import seguimiento as fases_seguimiento
from gestion_causas.fases import smu as fases_smu

RUTA_CONTEXTO_DEFAULT = Path(__file__).parent / "_contexto_corrida.json"

FASES_SOLO_CORRIDA_MANANA = {"seguimiento", "calendario"}

# Orden fijo en el que el panel muestra el resumen de cada fase — mismo
# contrato que ya documentaban subagentes/*.md ("Resumen final"), sin
# relación con el orden de despacho de `correr()` (que corre smu antes que
# goteo/agenda/seguimiento por las razones de paralelismo del docstring).
ORDEN_PANEL = ("calendario", "smu", "goteo", "agenda", "seguimiento")


def correr(
    ruta_contexto: Path = RUTA_CONTEXTO_DEFAULT,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    if not Path(ruta_contexto).exists():
        raise FileNotFoundError(
            f"No existe el contexto de corrida en {ruta_contexto}. "
            "Este driver requiere que ya se haya armado con "
            "`python -m gestion_causas.cli contexto-corrida` antes de correrlo."
        )
    contexto_corrida = json.loads(Path(ruta_contexto).read_text(encoding="utf-8"))
    es_corrida_manana = contexto_corrida.get("corrida") == "manana"

    fases = {}
    for nombre, funcion, kwargs_extra in (
        ("smu", fases_smu.correr, {"ruta_registro_ceco": ruta_registro_ceco}),
        ("goteo", fases_goteo.correr, {"ruta_registro_ceco": ruta_registro_ceco}),
        ("agenda", fases_agenda.correr, {}),
        ("seguimiento", fases_seguimiento.correr, {}),
        ("calendario", fases_calendario.correr, {}),
    ):
        if nombre in FASES_SOLO_CORRIDA_MANANA and not es_corrida_manana:
            continue
        try:
            fases[nombre] = funcion(
                contexto_corrida,
                ruta_registro_causas=ruta_registro_causas,
                **kwargs_extra,
            )
        except Exception as e:
            mensaje = f"{type(e).__name__}: {e}"
            bitacora_mod.registrar(f"Fase '{nombre}' falló: {mensaje}")
            fases[nombre] = {"fase": nombre, "error": mensaje}

    return {
        "fecha_hoy": contexto_corrida.get("fecha_hoy"),
        "corrida": contexto_corrida.get("corrida"),
        "fases": fases,
    }


def _resumen_como_lista(fases: dict, es_corrida_manana: bool) -> list[dict]:
    """Convierte el dict {nombre: resultado} que devuelve `correr()` en la
    lista ordenada (calendario, smu, goteo, agenda, seguimiento) que espera
    `panel.generar_panel_html` — mismo contrato "Resumen final" que ya
    documentaban subagentes/*.md. Una fase ausente del dict solo puede ser
    'calendario'/'seguimiento' en una corrida que no era de mañana (la única
    forma en que `correr()` se salta una fase), así que se completa con el
    mismo objeto "No aplica" que armaba el paso 3 del SKILL.md viejo."""
    lista = []
    for nombre in ORDEN_PANEL:
        if nombre in fases:
            lista.append(fases[nombre])
        else:
            lista.append({
                "fase": nombre,
                "resultado": "No aplica: solo corre en la corrida de la mañana.",
                "error": None,
            })
    return lista


def _armar_y_enviar_panel(fases: dict, fecha_hoy: str, es_corrida_manana: bool, *, ruta_registro_causas: Path) -> dict:
    """Pasos 3 a 5 del SKILL.md original: arma el resumen de la corrida,
    revisa si quedaron borradores de documentos sin enviar de corridas
    anteriores, genera el HTML del panel y lo envía por correo. Nunca lanza
    — cualquier falla en este tramo se anota en la bitácora y se devuelve en
    el resultado en vez de propagarse, porque para cuando se llega acá las 5
    fases ya corrieron y no tiene sentido perder ese trabajo por un problema
    de esta última parte."""
    resultado: dict = {"borradores": None, "panel_generado": False, "correo_enviado": False, "error": None}

    try:
        resultado["borradores"] = cli_mod.verificar_borradores_pendientes()
    except Exception as e:
        mensaje = f"{type(e).__name__}: {e}"
        bitacora_mod.registrar(f"Orquestador: no se pudo revisar borradores pendientes ({mensaje})")
        resultado["borradores"] = {"error": mensaje}

    borradores_pendientes = (
        resultado["borradores"].get("pendientes")
        if isinstance(resultado["borradores"], dict)
        else None
    )

    try:
        html = panel_mod.generar_panel_html(
            _resumen_como_lista(fases, es_corrida_manana),
            hoy=date.fromisoformat(fecha_hoy) if fecha_hoy else None,
            ruta_registro=ruta_registro_causas,
            borradores_pendientes=borradores_pendientes,
        )
        resultado["panel_generado"] = True
    except Exception as e:
        mensaje = f"{type(e).__name__}: {e}"
        bitacora_mod.registrar(f"Orquestador: fallo al generar el panel de estado ({mensaje})")
        resultado["error"] = mensaje
        return resultado

    try:
        # `permitir_login=False`: una corrida desatendida no puede quedarse
        # esperando a que alguien complete un login interactivo en el
        # navegador (mismo criterio que usa `cli._diagnosticar_token` para
        # los otros 3 tokens) — si el token personal no sirve, esto falla
        # rápido en vez de colgar la tarea para siempre.
        servicio = gmail_personal_client.construir_servicio(permitir_login=False)
        gmail_personal_client.enviar_panel_estado(
            f"Panel de gestión de causas - {fecha_hoy}", html, servicio=servicio
        )
        resultado["correo_enviado"] = True
    except Exception as e:
        mensaje = f"{type(e).__name__}: {e}"
        bitacora_mod.registrar(f"Orquestador: fallo al enviar el panel de estado ({mensaje})")
        resultado["error"] = mensaje

    return resultado


def correr_y_enviar_panel(
    ruta_contexto: Path = RUTA_CONTEXTO_DEFAULT,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    """Punto de entrada completo: `correr()` (las 5 fases) + `panel` (armar
    y enviar el panel de estado). Borra `ruta_contexto` al final, como hacía
    el paso 6 del SKILL.md viejo — best-effort, un archivo temporal que no
    se pudo borrar no es motivo para reportar la corrida como fallida."""
    resultado = correr(
        ruta_contexto, ruta_registro_causas=ruta_registro_causas, ruta_registro_ceco=ruta_registro_ceco
    )
    resultado["panel"] = _armar_y_enviar_panel(
        resultado["fases"],
        resultado["fecha_hoy"],
        resultado["corrida"] == "manana",
        ruta_registro_causas=ruta_registro_causas,
    )

    try:
        Path(ruta_contexto).unlink(missing_ok=True)
    except OSError as e:
        bitacora_mod.registrar(f"Orquestador: no se pudo borrar el contexto temporal de la corrida ({e})")

    return resultado


def _asegurar_contexto(ruta_contexto: Path = RUTA_CONTEXTO_DEFAULT) -> bool:
    """Arma `_contexto_corrida.json` si no existe (paso 1 del SKILL.md
    viejo), reusando `cli.main` en vez de duplicar `cmd_contexto_corrida`.
    Devuelve si el contexto quedó utilizable (`listo`).

    Con esto la tarea programada es un único comando
    (`python -m gestion_causas.orquestador`) en vez de dos pasos
    encadenados a mano por un agente — que era la última razón por la que
    el SKILL.md seguía necesitando un modelo para orquestar."""
    ruta = Path(ruta_contexto)
    if not ruta.exists():
        cli_mod.main(["contexto-corrida", "--salida", str(ruta)])
    if not ruta.exists():
        return False
    try:
        return bool(json.loads(ruta.read_text(encoding="utf-8")).get("listo"))
    except ValueError:
        return False


def main(argv=None) -> int:
    """Punto de entrada de la tarea programada. Arma el contexto si falta,
    corre las 5 fases, arma y envía el panel, y anota en la bitácora cuántos
    tokens costó la corrida (ver uso_tokens.py).

    Un contexto no listo (Gmail de trabajo o Calendar caídos) NO aborta: es
    exactamente el caso que el paso 1 del SKILL.md viejo mandaba igual, para
    que Nico se entere por el panel de que hay un token que reautorizar.
    `correr()` va a fallar cada fase por su cuenta y el panel las va a
    mostrar en error."""
    if not _asegurar_contexto():
        bitacora_mod.registrar(
            "Orquestador: contexto de corrida no listo (token caído) — se corre igual "
            "para que el panel avise"
        )

    antes = uso_tokens.resumen()
    resultado = correr_y_enviar_panel()
    despues = uso_tokens.resumen()

    resultado["uso_tokens"] = {
        "llamadas": despues["llamadas"] - antes["llamadas"],
        "input_tokens": despues["input_tokens"] - antes["input_tokens"],
        "output_tokens": despues["output_tokens"] - antes["output_tokens"],
        "cache_creation_input_tokens": (
            despues["cache_creation_input_tokens"] - antes["cache_creation_input_tokens"]
        ),
        "cache_read_input_tokens": (
            despues["cache_read_input_tokens"] - antes["cache_read_input_tokens"]
        ),
        "costo_usd": round(despues["costo_usd"] - antes["costo_usd"], 4),
    }
    uso = resultado["uso_tokens"]
    bitacora_mod.registrar(
        f"Orquestador: corrida terminada — {uso['llamadas']} llamadas a Claude, "
        f"{uso['input_tokens']} tokens de entrada, {uso['output_tokens']} de salida, "
        f"USD {uso['costo_usd']}"
    )

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
