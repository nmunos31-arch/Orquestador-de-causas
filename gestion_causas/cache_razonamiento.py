"""Caché de respuestas de razonamiento entre corridas.

El orquestador corre 3 veces al día y `cli._generar_mapa_hilos_por_rit`
guarda TODOS los mensajes de cada hilo activo (no solo los nuevos), así que
una causa cuyo hilo no cambió produce un prompt idéntico byte por byte en
las 3 corridas. Este módulo cachea el resultado por hash del par
(tarea, contexto): si el prompt es el mismo, la respuesta también, y no hay
que volver a pagarla.

La clave se calcula sobre el contenido real que se le manda al modelo, no
sobre un identificador externo (thread_id, RIT): así un mensaje nuevo en el
hilo, un cambio en el texto de la tarea o un ítem agregado al pedido
invalidan la entrada solos, sin que ningún llamador tenga que acordarse de
invalidarla a mano.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from gestion_causas.registro import _lock

RUTA_CACHE = Path(__file__).parent / "cache_razonamiento.json"

# Una respuesta sobre un hilo que no cambió sigue siendo válida
# indefinidamente (la clave ya depende del contenido), pero el archivo no
# puede crecer para siempre: 30 días cubre de sobra el ciclo de vida de una
# causa activa en goteo/seguimiento.
DIAS_VIGENCIA = 30


def clave(tarea: str, contexto: dict) -> str:
    """sha256 del par (tarea, contexto). `sort_keys=True` para que el orden
    en que un llamador arme el dict no produzca claves distintas para el
    mismo contenido."""
    material = json.dumps(
        {"tarea": tarea, "contexto": contexto},
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cargar(ruta: Path) -> dict:
    """Un caché ilegible (JSON truncado por una corrida interrumpida) se
    trata como caché vacío: se pierde el ahorro de esa corrida, nunca la
    corrida."""
    try:
        contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return contenido if isinstance(contenido, dict) else {}


def _vigente(entrada: dict) -> bool:
    try:
        guardado = datetime.fromisoformat(entrada["guardado_en"])
    except (KeyError, TypeError, ValueError):
        return False
    return datetime.now() - guardado <= timedelta(days=DIAS_VIGENCIA)


def obtener(clave_buscada: str, ruta: Path = RUTA_CACHE) -> dict | None:
    """La respuesta cacheada, o None si no está, venció o el archivo no se
    puede leer."""
    entrada = _cargar(ruta).get(clave_buscada)
    if not isinstance(entrada, dict) or not _vigente(entrada):
        return None
    resultado = entrada.get("resultado")
    return resultado if isinstance(resultado, dict) else None


def guardar(clave_nueva: str, resultado: dict, ruta: Path = RUTA_CACHE) -> None:
    """Guarda `resultado` y poda de paso las entradas vencidas. Nunca lanza:
    no poder cachear es perder el ahorro de la próxima corrida, no un motivo
    para tumbar esta."""
    try:
        with _lock(Path(ruta)):
            contenido = {
                k: v for k, v in _cargar(ruta).items()
                if isinstance(v, dict) and _vigente(v)
            }
            contenido[clave_nueva] = {
                "guardado_en": datetime.now().isoformat(),
                "resultado": resultado,
            }
            Path(ruta).write_text(
                json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception:  # noqa: BLE001 - el caché nunca tumba una corrida
        pass
