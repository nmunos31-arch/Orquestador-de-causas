#!/usr/bin/env python3
"""
Registro persistente de causas y de CECOs (locales) procesados por la gestión
automática de causas nuevas desde la casilla nmunoz@gomezyriesco.cl.

Dos archivos JSON, ambos junto a este módulo salvo que se indique otra ruta:
- registro_causas.json: una entrada por RIT normalizado. Da idempotencia —
  saber si una causa ya fue registrada, y qué datos faltan.
- registro_ceco.json: por código CECO, el local y las fechas de despido para
  las que ya se recibió el EERR (usado en la Fase 2 para no volver a pedirlo).

Ver docs del diseño: "Actualizador de informes/docs/2026-07-07-informe-juicios-email-design.md"
y el plan en C:\\Users\\usuario\\.claude\\plans\\1-contrato-de-trabajo-streamed-pizza.md.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path

RUTA_REGISTRO_CAUSAS = Path(__file__).parent / "registro_causas.json"
RUTA_REGISTRO_CECO = Path(__file__).parent / "registro_ceco.json"
RUTA_REGISTRO_SEGUIMIENTO = Path(__file__).parent / "registro_seguimiento.json"


def normalizar_rit(valor) -> str:
    """Quita espacios en blanco y normaliza guiones especiales a "-".

    Duplicado deliberado de la función homónima en actualizar_informe_juicios.py
    (mismo comportamiento, misma razón: RITs copiados a mano traen tabs o
    guiones no separables). Se duplica en vez de importar para que este
    paquete no dependa de la ubicación del script del Excel.
    """
    texto = "".join(str(valor).split()).upper()
    for guion in ("‐", "‑", "‒", "–", "—"):
        texto = texto.replace(guion, "-")
    return texto


_PATRON_RIT = re.compile(
    r"([A-Za-z])[-‐‑‒–—]\s?(\d{1,6})[-‐‑‒–—]\s?(\d{4})"
)


def extraer_rit(texto: str) -> str | None:
    """Busca un RIT (ej. "M-643-2026") dentro de un texto libre (título de
    evento de calendario, asunto de correo) y lo devuelve normalizado, o
    None si no encuentra ninguno. Usado por el barrido de calendario
    (Fase 0) para identificar causas a partir del resumen del evento."""
    coincidencia = _PATRON_RIT.search(texto)
    if not coincidencia:
        return None
    letra, numero, anio = coincidencia.groups()
    return f"{letra.upper()}-{numero}-{anio}"


def _cargar(ruta: Path) -> dict:
    if not ruta.exists():
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar(ruta: Path, datos: dict) -> None:
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)


# ── Registro de causas ────────────────────────────────────────────────────
def cargar_registro_causas(ruta: Path = RUTA_REGISTRO_CAUSAS) -> dict:
    return _cargar(ruta)


def obtener_causa(rit: str, ruta: Path = RUTA_REGISTRO_CAUSAS) -> dict | None:
    return cargar_registro_causas(ruta).get(normalizar_rit(rit))


def registrar_causa(rit: str, datos: dict, ruta: Path = RUTA_REGISTRO_CAUSAS) -> dict:
    """Da de alta una causa nueva o actualiza (merge) una existente.

    `datos` puede traer, entre otros: thread_id, message_id, empresa, ceco,
    demandante, carpeta, fecha_despido, fecha_audiencia (AAAA-MM-DD, para la
    Fase 4), tiene_demanda, tiene_ceco, campos_faltantes (lista).

    Si el RIT ya existía, se hace merge superficial (los campos nuevos pisan
    a los viejos; los campos no incluidos en `datos` se conservan) — así una
    corrida posterior que trae el CECO que faltaba no pierde lo ya guardado.

    Devuelve la entrada final guardada.
    """
    registro = cargar_registro_causas(ruta)
    clave = normalizar_rit(rit)
    existente = registro.get(clave, {})
    fusionada = {**existente, **datos}
    fusionada["rit"] = rit
    fusionada.setdefault("primera_vez_registrada", datetime.now().isoformat())
    fusionada["ultima_actualizacion"] = datetime.now().isoformat()
    registro[clave] = fusionada
    _guardar(ruta, registro)
    return fusionada


def causa_ya_registrada(rit: str, ruta: Path = RUTA_REGISTRO_CAUSAS) -> bool:
    return obtener_causa(rit, ruta) is not None


def causas_con_borrador_pendiente(ruta: Path = RUTA_REGISTRO_CAUSAS) -> list:
    """Causas cuyo campo `borrador_documentos_draft_id` está seteado (no
    None/vacío) — candidatas a que la tarea programada verifique contra
    Gmail si ese borrador sigue sin enviar (ver gmail_client.borrador_existe).
    Este módulo no llama a Gmail: solo lee el registro local."""
    return [
        entrada for entrada in cargar_registro_causas(ruta).values()
        if entrada.get("borrador_documentos_draft_id")
    ]


def causas_para_goteo(
    hoy=None, dias_ventana_post_audiencia: int = 60, ruta: Path = RUTA_REGISTRO_CAUSAS
) -> list:
    """Causas que conviene seguir revisando por documentos nuevos (Fase 3):
    las que todavía no tienen fecha de audiencia registrada, o cuya audiencia
    fue hace `dias_ventana_post_audiencia` días o menos (la prueba puede
    seguir llegando un tiempo después, ej. por una reprogramación). Acota el
    barrido para que no crezca sin límite a medida que se acumulan causas
    viejas ya cerradas. Las causas con `causa_cerrada: true` se excluyen
    siempre, sin importar si tienen fecha de audiencia.

    `hoy` es inyectable para tests; por defecto usa la fecha actual.
    Devuelve una lista de entradas del registro (dicts), cada una con su
    "rit" y "thread_id".
    """
    if hoy is None:
        hoy = date.today()
    else:
        hoy = _parsear_fecha(hoy)

    resultado = []
    for entrada in cargar_registro_causas(ruta).values():
        if entrada.get("causa_cerrada"):
            continue
        fecha_audiencia = entrada.get("fecha_audiencia")
        if not fecha_audiencia:
            resultado.append(entrada)
            continue
        dias_desde_audiencia = (hoy - _parsear_fecha(fecha_audiencia)).days
        if dias_desde_audiencia <= dias_ventana_post_audiencia:
            resultado.append(entrada)
    return resultado


# ── Registro de CECO (locales) ────────────────────────────────────────────
def cargar_registro_ceco(ruta: Path = RUTA_REGISTRO_CECO) -> dict:
    return _cargar(ruta)


def _parsear_fecha(valor) -> date:
    if isinstance(valor, date):
        return valor
    return datetime.strptime(str(valor), "%Y-%m-%d").date()


def _dias_entre(a: date, b: date) -> int:
    return abs((a - b).days)


def registrar_eerr_recibido(
    ceco: str, fecha_despido, rit_causa: str, ruta: Path = RUTA_REGISTRO_CECO
) -> None:
    """Anota que se recibió el EERR del local `ceco` con motivo del despido de
    fecha `fecha_despido` (para la causa `rit_causa`)."""
    registro = cargar_registro_ceco(ruta)
    ceco_norm = str(ceco).strip().upper()
    entradas = registro.setdefault(ceco_norm, [])
    entradas.append({
        "fecha_despido": str(_parsear_fecha(fecha_despido)),
        "rit_causa": rit_causa,
    })
    _guardar(ruta, registro)


def buscar_eerr_reusable(
    ceco: str, fecha_despido, dias_tolerancia: int = 90, ruta: Path = RUTA_REGISTRO_CECO
) -> dict | None:
    """Busca si ya existe un EERR recibido para el mismo CECO con un despido a
    menos de `dias_tolerancia` días del `fecha_despido` dado (regla del
    usuario: 3 meses ~ 90 días). Si hay más de uno dentro de tolerancia,
    devuelve el más cercano en fecha.

    Devuelve la entrada reusable o None.
    """
    if not ceco:
        return None
    registro = cargar_registro_ceco(ruta)
    ceco_norm = str(ceco).strip().upper()
    entradas = registro.get(ceco_norm, [])
    if not entradas:
        return None

    objetivo = _parsear_fecha(fecha_despido)
    candidatas = [
        (e, _dias_entre(objetivo, _parsear_fecha(e["fecha_despido"])))
        for e in entradas
    ]
    candidatas = [(e, dist) for e, dist in candidatas if dist <= dias_tolerancia]
    if not candidatas:
        return None
    candidatas.sort(key=lambda par: par[1])
    return candidatas[0][0]


# ── Registro de seguimiento (Fases 5 y 6: correos sin respuesta / documentos
# pendientes) ────────────────────────────────────────────────────────────
def cargar_registro_seguimiento(ruta: Path = RUTA_REGISTRO_SEGUIMIENTO) -> dict:
    return _cargar(ruta)


def obtener_seguimiento(thread_id: str, ruta: Path = RUTA_REGISTRO_SEGUIMIENTO) -> dict | None:
    return cargar_registro_seguimiento(ruta).get(thread_id)


def registrar_aviso(
    thread_id: str,
    tipo: str,
    fecha,
    rit: str | None = None,
    draft_id: str | None = None,
    ruta: Path = RUTA_REGISTRO_SEGUIMIENTO,
) -> dict:
    """Anota que se creó un borrador de insistencia/recordatorio para
    `thread_id` en `fecha` (AAAA-MM-DD). `tipo` es uno de "acuerdo-daniela",
    "causa-laboral" o "documentos" — solo informativo, no cambia la lógica de
    cadencia. Devuelve la entrada final guardada."""
    registro = cargar_registro_seguimiento(ruta)
    entrada = registro.setdefault(thread_id, {"tipo": tipo, "rit": rit, "avisos": []})
    entrada["tipo"] = tipo
    if rit:
        entrada["rit"] = rit
    entrada["avisos"].append({
        "n": len(entrada["avisos"]) + 1,
        "fecha": str(_parsear_fecha(fecha)),
        "draft_id": draft_id,
    })
    entrada["ultima_revision"] = datetime.now().isoformat()
    registro[thread_id] = entrada
    _guardar(ruta, registro)
    return entrada


def puede_insistir(
    thread_id: str,
    hoy=None,
    ruta: Path = RUTA_REGISTRO_SEGUIMIENTO,
    ruta_feriados=None,
) -> dict:
    """Aplica la cadencia acordada con el usuario: el 1er aviso siempre
    procede; el 2º solo si pasaron al menos 2 días hábiles desde el 1º; del
    3º en adelante nunca se genera borrador (solo se reporta en el resumen
    de la tarea, requiere gestión manual).

    Devuelve {"puede": bool, "n_aviso": int, "motivo": str}, donde
    `n_aviso` es el número de aviso que correspondería crear a continuación
    (1, 2, o el que ya se agotó).
    """
    from . import agenda as agenda_mod

    if hoy is None:
        hoy = date.today()
    else:
        hoy = _parsear_fecha(hoy)

    entrada = obtener_seguimiento(thread_id, ruta)
    avisos = entrada["avisos"] if entrada else []

    if len(avisos) == 0:
        return {"puede": True, "n_aviso": 1, "motivo": "sin avisos previos"}

    if len(avisos) == 1:
        kwargs = {} if ruta_feriados is None else {"ruta_feriados": ruta_feriados}
        transcurridos = agenda_mod.dias_habiles_entre(avisos[0]["fecha"], hoy, **kwargs)
        if transcurridos >= 2:
            return {"puede": True, "n_aviso": 2, "motivo": f"pasaron {transcurridos} dias habiles desde el 1er aviso"}
        return {
            "puede": False, "n_aviso": 2,
            "motivo": f"solo pasaron {transcurridos} dias habiles desde el 1er aviso (se requieren 2)",
        }

    return {
        "puede": False, "n_aviso": len(avisos) + 1,
        "motivo": f"ya se hicieron {len(avisos)} avisos, requiere gestion manual",
    }
