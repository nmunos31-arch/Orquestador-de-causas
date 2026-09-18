"""Extracción de los campos de una sola línea del cuadro-resumen que llega
en el correo de una demanda nueva (ver subagentes/smu.md paso 2c y
docs/2026-07-07-informe-juicios-email-design.md). Solo extrae los campos que
son "Etiqueta: valor" en una línea — "Hechos" y "Conceptos demandados" son
texto libre/multilínea y se dejan para que los procese Claude directamente
sobre el cuerpo completo (ver `fases/smu.py::_generar_resumen_narrativo`),
en vez de intentar acotarlos con regex."""

from __future__ import annotations

import re
import unicodedata

CAMPOS_OBLIGATORIOS = ("rit", "tribunal", "cuantia")

# Clave interna -> variantes de etiqueta aceptadas (ya sin tildes, minúsculas).
_ETIQUETAS = {
    "rit": ("rit",),
    "tribunal": ("tribunal",),
    "demandante": ("demandante",),
    "rut": ("rut",),
    "fecha_audiencia": ("fecha audiencia", "fecha de audiencia"),
    "demandada": ("demandada",),
    "cuantia": ("cuantia",),
    "materia": ("materia",),
    "fecha_ingreso_pjud": ("fecha de ingreso al pjud", "fecha ingreso pjud", "fecha ingreso al pjud"),
}

_LINEA_ETIQUETA_VALOR = re.compile(r"^\s*([^:\n]{2,40}?)\s*:\s*(.+?)\s*$")


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()


def extraer_campos_cuadro(cuerpo_texto: str) -> dict:
    """Recorre `cuerpo_texto` línea por línea buscando "Etiqueta: valor".
    Devuelve un dict solo con las claves que encontró (nunca claves con
    valor vacío) — un campo ausente simplemente no aparece."""
    campos: dict = {}
    for linea in cuerpo_texto.splitlines():
        coincidencia = _LINEA_ETIQUETA_VALOR.match(linea)
        if not coincidencia:
            continue
        etiqueta_cruda = re.sub(r"\s+", " ", _sin_tildes(coincidencia.group(1).strip()))
        valor = coincidencia.group(2).strip()
        if not valor:
            continue
        for clave, variantes in _ETIQUETAS.items():
            if clave in campos:
                continue
            if etiqueta_cruda in variantes:
                campos[clave] = valor
                break
    return campos


def cuadro_completo(campos: dict) -> bool:
    """True si `campos` trae los 3 campos sin los que no vale la pena seguir
    (ver docs/2026-07-07-informe-juicios-email-design.md, "Manejo de
    errores")."""
    return all(campos.get(clave) for clave in CAMPOS_OBLIGATORIOS)


PATRON_CECO = re.compile(r"ceco\s*(?:[:=-]|\bes\b)?\s*(\d+|[A-Z]+[\d-]+)", re.IGNORECASE)


def buscar_ceco_en_mensajes(mensajes: list[dict]) -> str | None:
    """Busca un CECO mencionado en cualquiera de los mensajes de un hilo (ver
    subagentes/smu.md paso 2f: puede venir en el primer mensaje o en una
    respuesta posterior, ej. "nos confirme el CECO 8890"). Best-effort por
    regex, sin Claude — si de verdad no está en ningún mensaje, se completa
    en una corrida futura cuando llegue. Compartido por `fases/smu.py` (causas
    nuevas por correo) y `fases/calendario.py` (causas detectadas por
    calendario) para no divergir en el criterio."""
    for mensaje in mensajes:
        coincidencia = PATRON_CECO.search(mensaje.get("cuerpo_texto", ""))
        if coincidencia:
            return coincidencia.group(1).upper()
    return None


# Marcadores de inicio de texto citado en clientes de correo en español
# (Gmail y Outlook en modo texto plano) — mismo criterio que usa
# `fases/goteo.py` para recortar el historial citado de un hilo, pero acá se
# usa al revés: para quedarse solo con la parte citada (ver `texto_citado`).
_PATRONES_INICIO_CITA = [
    re.compile(r"^>", re.MULTILINE),
    re.compile(r"^El .+ escribió:\s*$", re.MULTILINE),
    re.compile(r"^De:.*\n(?:Enviado|Para|Asunto):", re.MULTILINE),
    re.compile(r"^-{3,}\s*Mensaje original\s*-{3,}", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^_{10,}\s*$", re.MULTILINE),
]


_PREFIJO_CITA_LINEA = re.compile(r"^\s*>+\s?", re.MULTILINE)


def texto_citado(cuerpo_texto: str) -> str:
    """Devuelve la parte de `cuerpo_texto` desde el primer marcador de cita
    en adelante (el historial de un reenvío/respuesta, típicamente el
    mensaje original de otra persona), con el prefijo '>' de citado quitado
    de cada línea si corresponde (si no, "> Rit: ..." no matchea la etiqueta
    "rit" que espera `extraer_campos_cuadro`). Cadena vacía si no encuentra
    ningún marcador conocido — un mensaje sin citas no tiene nada que
    devolver acá, a diferencia del recorte "todo lo anterior a la cita" que
    hace `fases/goteo.py`."""
    primer_inicio = min(
        (m.start() for patron in _PATRONES_INICIO_CITA for m in [patron.search(cuerpo_texto)] if m),
        default=None,
    )
    if primer_inicio is None:
        return ""
    return _PREFIJO_CITA_LINEA.sub("", cuerpo_texto[primer_inicio:])


_PATRON_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def dominios_citados(texto: str) -> set[str]:
    """Dominios (en minúsculas, sin la '@') de todas las direcciones de
    correo que aparecen en `texto` — usado sobre el resultado de
    `texto_citado` para saber de qué dominio era originalmente el mensaje
    citado (ej. detectar que un reenvío cita a alguien de @smu.cl)."""
    return {m.group(0).rsplit("@", 1)[1].lower() for m in _PATRON_EMAIL.finditer(texto)}
