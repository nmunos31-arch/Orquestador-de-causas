#!/usr/bin/env python3
"""
Bitácora acumulativa en texto plano de todo lo que hace la gestión automática
de causas nuevas — una línea por acción, para que el usuario pueda auditar el
historial completo sin depender de los resúmenes de cada corrida (que solo
viven en la conversación de la tarea programada).
"""

from datetime import datetime
from pathlib import Path

RUTA_BITACORA_DEFAULT = Path(__file__).parent / "bitacora.md"


def registrar(mensaje: str, rit: str | None = None, ruta: Path = RUTA_BITACORA_DEFAULT) -> None:
    """Agrega una línea a la bitácora con timestamp y, si se indica, el RIT de
    la causa a la que se refiere la acción. No falla si el archivo no existe
    aún — lo crea con un encabezado."""
    if not ruta.exists():
        ruta.write_text(
            "# Bitácora de gestión de causas nuevas\n\n"
            "Registro automático de acciones (fila en Excel, carpeta creada, "
            "documento guardado, etiqueta aplicada, borrador creado). "
            "Ninguna de estas acciones incluye envío de correo ni borrado.\n\n",
            encoding="utf-8",
        )

    marca = datetime.now().strftime("%Y-%m-%d %H:%M")
    prefijo = f"[{marca}]"
    if rit:
        prefijo += f" [{rit}]"

    with open(ruta, "a", encoding="utf-8") as f:
        f.write(f"{prefijo} {mensaje}\n")
