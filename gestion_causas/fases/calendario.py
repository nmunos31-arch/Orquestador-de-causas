"""Driver Python de la fase 'calendario' (Fase 0 — ver plan de implementación
docs/superpowers/plans/2026-09-18-driver-python-calendario.md): los 3 pasos
de subagentes/calendario.md.

Red de seguridad semanal (solo corre los lunes): barre los próximos 90 días
del calendario en busca de audiencias de las 6 empresas de interés que
nunca llegaron a registrarse por correo, y las da de alta con lo que se
pueda reconstruir del hilo de origen. El calendario se usa en modo SOLO
LECTURA — nunca crea, modifica ni borra eventos, ni envía correos."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import calendar_client
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import registro as registro_mod
from gestion_causas.cuadro_resumen import buscar_ceco_en_mensajes, cuadro_completo, extraer_campos_cuadro
from gestion_causas.gmail_client import COLOR_POR_EMPRESA, EMPRESAS_SIN_EXCEL
from gestion_causas.seguimiento import extraer_direccion, parsear_fecha

DIAS_ADELANTE = 90
TIPOS_CON_CARPETA = {"Única", "Preparatoria"}
DOMINIOS_ORIGEN = ("smu.cl", "sb.cl")


def _es_lunes(contexto_corrida: dict) -> bool:
    if "es_lunes" in contexto_corrida:
        return bool(contexto_corrida["es_lunes"])
    return date.today().weekday() == 0


def _eventos_candidatos(contexto_corrida: dict) -> list[dict]:
    """Paso 1: usa el cache de calendario que el ciclo ya trajo para
    toda la corrida (contiene el rango de 90 días que necesita esta fase);
    si no hay contexto, no hay cache, o la lectura falla por cualquier
    motivo (archivo corrupto, rango insuficiente), cae a la llamada en vivo
    de siempre — mismo criterio de fallback que usan `goteo`/`agenda` con
    sus propios caches."""
    hoy = date.today()
    hasta = hoy + timedelta(days=DIAS_ADELANTE)
    ruta_cache = (contexto_corrida.get("cache_calendario") or {}).get("ruta")
    if ruta_cache:
        try:
            return calendar_client.eventos_empresas_interes_desde_cache(hoy, hasta, ruta_cache)
        except Exception:
            pass
    return calendar_client.eventos_empresas_interes(hoy, hasta)


def _buscar_mensaje_origen(rit: str) -> tuple[str, dict] | None:
    """Busca, entre los hilos que mencionan `rit`, el mensaje más antiguo
    cuyo remitente sea de dominio smu.cl o sb.cl — mismo criterio de origen
    que usa `fases/smu.py` para causas nuevas por correo. Devuelve
    (thread_id, mensaje) o None si no encuentra ninguno; en ese caso la
    causa se registra igual con lo que traiga el evento, sin thread_id ni
    demanda (calendario.md paso 2d)."""
    mejor: tuple[str, dict] | None = None
    for hilo in gmail_client.buscar_hilos(rit):
        for mensaje in gmail_client.leer_hilo(hilo["id"]):
            dominio = extraer_direccion(mensaje.get("sender", "")).rsplit("@", 1)[-1].lower()
            if dominio not in DOMINIOS_ORIGEN:
                continue
            if mejor is None or parsear_fecha(mensaje["date"]) < parsear_fecha(mejor[1]["date"]):
                mejor = (hilo["id"], mensaje)
    return mejor


def _guardar_demanda_si_hay(mensaje_origen: dict, carpeta: Path) -> bool:
    """Mismo criterio que `fases/smu.py`: el primer adjunto PDF que no
    parezca una firma/logo se guarda como demanda.pdf."""
    for adjunto in mensaje_origen.get("adjuntos", []):
        if not adjunto["filename"].lower().endswith(".pdf"):
            continue
        contenido = gmail_client.descargar_adjunto(mensaje_origen["id"], adjunto["attachment_id"])
        if carpetas_mod.es_adjunto_firma(adjunto["filename"], len(contenido)):
            continue
        resultado = carpetas_mod.guardar_adjunto(carpeta, "demanda.pdf", contenido)
        return resultado["guardado"]
    return False


def _agregar_fila_excel(rit: str, campos: dict, cuerpo_texto: str, acciones: list[dict]) -> bool:
    """Paso 2h: reusa `_generar_resumen_narrativo`/`agregar_causa` de
    `fases/smu.py` (mismo "Resumen" que ya redacta Claude para el Excel de
    Juicios Vigentes) — a diferencia de lo que anticipaba el spec general,
    este paso sí necesita ese único punto de razonamiento; el resto de la
    fase es mecánico. Import diferido a este punto (no a nivel de módulo,
    y solo si el cuadro está completo — nunca antes de saber que hace
    falta): `fases/smu.py` engancha `actualizar_informe_juicios.py` (repo
    aparte, ver su propio docstring) apenas se importa, y `calendario.py`
    no debe depender de esa máquina para el resto de la fase, que no toca
    el Excel."""
    if not cuadro_completo(campos):
        return False
    from gestion_causas.fases.smu import RUTA_EXCEL_JUICIOS, _generar_resumen_narrativo, agregar_causa

    deteccion = _generar_resumen_narrativo(campos, cuerpo_texto)
    if deteccion.get("error"):
        acciones.append({
            "rit": rit,
            "que": f"No se pudo redactar el Resumen del Excel automáticamente: {deteccion['error']}",
            "urgencia": "media",
        })
        return False
    datos_excel = {
        "juzgado": campos.get("tribunal", ""), "materia": campos.get("materia", ""),
        "causa": rit, "cuantia": campos.get("cuantia", ""), "resumen": deteccion.get("resumen", ""),
    }
    try:
        agregar_causa(RUTA_EXCEL_JUICIOS, datos_excel)
        return True
    except PermissionError:
        acciones.append({
            "rit": rit,
            "que": "El Excel de Juicios Vigentes está abierto/bloqueado — no se pudo escribir la fila. Nico debe agregarla a mano.",
            "urgencia": "alta",
        })
        return False


def _procesar_evento(
    rit: str, evento: dict, ruta_registro_causas: Path, acciones: list[dict], notas: list[dict]
) -> dict | None:
    """Ejecuta el paso 2 completo para un evento con RIT reconocible que
    todavía no está registrado. Devuelve el `item` del resumen si dio de
    alta una causa nueva, o None si se saltó (ya registrada, o el evento no
    es una audiencia real)."""
    if registro_mod.causa_ya_registrada(rit, ruta=ruta_registro_causas):
        return None

    resumen_evento = evento["resumen"]
    if calendar_client.es_evento_no_audiencia(resumen_evento):
        notas.append({
            "tipo": "evento_no_es_audiencia",
            "detalle": f"{rit}: {resumen_evento} (plazo procesal o reunión informativa, no una audiencia).",
        })
        return None

    tipo = calendar_client.clasificar_tipo_audiencia(resumen_evento)
    if tipo == "Ambiguo":
        notas.append({
            "tipo": "evento_no_es_audiencia",
            "detalle": f"{rit}: {resumen_evento} (tipo de audiencia no reconocible en el título).",
        })
        return None

    empresa = evento["empresa_detectada"]
    fecha_audiencia = str(evento["fecha"])

    origen = _buscar_mensaje_origen(rit)
    thread_id, mensaje_origen = origen if origen else (None, None)
    if mensaje_origen is None:
        notas.append({
            "tipo": "sin_hilo_origen",
            "detalle": f"{rit}: no se encontró el hilo de origen de la demanda — revisar a mano.",
        })

    campos = extraer_campos_cuadro(mensaje_origen.get("cuerpo_texto", "")) if mensaje_origen else {}
    ceco = buscar_ceco_en_mensajes([mensaje_origen]) if mensaje_origen else None
    apellido = campos.get("demandante", "").split()[-1].title() if campos.get("demandante") else rit

    carpeta = None
    demanda_guardada = False
    if tipo in TIPOS_CON_CARPETA:
        carpeta = carpetas_mod.buscar_carpeta_existente_por_rit(rit) or carpetas_mod.crear_carpeta_causa(
            apellido, empresa, rit
        )
        if mensaje_origen:
            demanda_guardada = _guardar_demanda_si_hay(mensaje_origen, carpeta)
        if not demanda_guardada:
            notas.append({
                "tipo": "sin_demanda",
                "detalle": f"{rit}: no se encontró demanda para guardar — súbela a mano.",
            })

    registro_mod.registrar_causa(rit, {
        "empresa": empresa,
        "demandante": campos.get("demandante", ""),
        "thread_id": thread_id,
        "carpeta": str(carpeta) if carpeta else None,
        "ceco": ceco,
        "fecha_audiencia": fecha_audiencia,
        "tiene_demanda": demanda_guardada,
        "aplica_excel": empresa not in EMPRESAS_SIN_EXCEL,
    }, ruta=ruta_registro_causas)

    if thread_id:
        label_id = gmail_client.obtener_o_crear_etiqueta(empresa, color=COLOR_POR_EMPRESA.get(empresa))
        gmail_client.aplicar_etiqueta_a_hilo(thread_id, label_id)

    excel_actualizado = False
    if empresa not in EMPRESAS_SIN_EXCEL and mensaje_origen:
        excel_actualizado = _agregar_fila_excel(rit, campos, mensaje_origen.get("cuerpo_texto", ""), acciones)

    detalle = f"Audiencia {tipo} el {fecha_audiencia}"
    if tipo in TIPOS_CON_CARPETA:
        detalle += "; demanda guardada" if demanda_guardada else "; falta demanda"
    detalle += "; Excel no aplica" if empresa in EMPRESAS_SIN_EXCEL else (
        "; Excel actualizado" if excel_actualizado else "; Excel pendiente"
    )

    bitacora_mod.registrar(
        f"Fase 0 (barrido de calendario): causa detectada por audiencia del {fecha_audiencia}, "
        f"no estaba registrada. {detalle}",
        rit=rit,
    )

    return {
        "rit": rit,
        "titulo": f"{campos.get('demandante', '')} con {empresa}".strip(),
        "detalle": detalle,
    }


def _armar_titular(items: list[dict]) -> str:
    if not items:
        return "Sin causas nuevas detectadas por calendario"
    if len(items) == 1:
        return f"1 causa nueva detectada por calendario ({items[0]['titulo']})"
    return f"{len(items)} causas nuevas detectadas por calendario"


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
) -> dict:
    if not _es_lunes(contexto_corrida):
        return {
            "fase": "calendario",
            "resultado": "No corresponde hoy (Fase 0 solo corre los lunes).",
            "error": None,
        }

    eventos = _eventos_candidatos(contexto_corrida)

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = []
    sin_rit = 0

    for evento in eventos:
        rit = evento.get("rit_detectado")
        if rit is None:
            sin_rit += 1
            notas.append({
                "tipo": "evento_sin_rit",
                "detalle": f"{evento['fecha']}: {evento['resumen']} — sin RIT reconocible, revisar a mano.",
            })
            continue
        item = _procesar_evento(rit, evento, ruta_registro_causas, acciones, notas)
        if item:
            items.append(item)

    return {
        "fase": "calendario",
        "titular": _armar_titular(items) if eventos else "Sin eventos nuevos de las empresas de interés",
        "metricas": [
            {"etiqueta": "Eventos revisados", "valor": len(eventos)},
            {"etiqueta": "Causas nuevas dadas de alta", "valor": len(items)},
            {"etiqueta": "Eventos sin RIT reconocible", "valor": sin_rit},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
