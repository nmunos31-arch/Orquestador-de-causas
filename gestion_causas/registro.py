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
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

RUTA_REGISTRO_CAUSAS = Path(__file__).parent / "registro_causas.json"
RUTA_REGISTRO_CECO = Path(__file__).parent / "registro_ceco.json"
RUTA_REGISTRO_SEGUIMIENTO = Path(__file__).parent / "registro_seguimiento.json"
RUTA_REGISTRO_PEDIDOS = Path(__file__).parent / "registro_pedidos.json"


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


# Segundos que se espera por el lock antes de rendirse, y edad a partir de la
# cual un .lock se considera huerfano (un proceso que murio sin liberarlo).
LOCK_TIMEOUT_SEG = 30.0
LOCK_EDAD_MAXIMA_SEG = 120.0


@contextmanager
def _lock(ruta: Path):
    """Serializa el ciclo leer-modificar-escribir de un registro entre
    procesos distintos.

    Existe porque el orquestador corre los subagentes `goteo` y `agenda` en
    paralelo y los dos actualizan `registro_causas.json` (campos distintos,
    pero el archivo se reescribe entero en cada `registrar_causa`, asi que sin
    esto una escritura pisa a la otra). Cada llamada del CLI es un proceso
    corto y separado, asi que el lock es un archivo centinela creado con
    O_EXCL — no sirve un lock en memoria.

    Un `.lock` mas viejo que LOCK_EDAD_MAXIMA_SEG se considera huerfano y se
    borra, para que un proceso muerto no bloquee para siempre las corridas
    siguientes.
    """
    ruta_lock = Path(str(ruta) + ".lock")
    limite = time.monotonic() + LOCK_TIMEOUT_SEG
    descriptor = None
    while True:
        try:
            descriptor = os.open(str(ruta_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                edad = time.time() - ruta_lock.stat().st_mtime
            except FileNotFoundError:
                continue  # lo liberaron entre el open y el stat: reintenta ya
            if edad > LOCK_EDAD_MAXIMA_SEG:
                try:
                    ruta_lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= limite:
                raise TimeoutError(
                    f"No se pudo tomar el lock de '{ruta}' en {LOCK_TIMEOUT_SEG}s "
                    f"(existe '{ruta_lock}'). Si ningun proceso lo esta usando, borralo."
                )
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.close(descriptor)
        finally:
            try:
                ruta_lock.unlink()
            except FileNotFoundError:
                pass


def _cargar(ruta: Path) -> dict:
    if not ruta.exists():
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar(ruta: Path, datos: dict) -> None:
    """Escritura atomica: se escribe a un temporal al lado y se reemplaza de
    una sola vez, para que un corte a mitad no deje el registro truncado."""
    ruta = Path(ruta)
    temporal = Path(str(ruta) + ".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(temporal, ruta)


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
    with _lock(ruta):
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
    seguir llegando un tiempo después, ej. por una reprogramación), o cuyo
    `estado_acuerdo` es "pendiente_pago" o "pago_recibido_pendiente_confirmar"
    (el pago de un acuerdo puede demorar meses, más allá de la ventana normal
    post-audiencia). Acota el barrido para que no crezca sin límite a medida
    que se acumulan causas viejas ya cerradas. Las causas con
    `causa_cerrada: true` se excluyen siempre, sin importar lo anterior.

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
        if entrada.get("estado_acuerdo") in ("pendiente_pago", "pago_recibido_pendiente_confirmar"):
            resultado.append(entrada)
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
    with _lock(ruta):
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
    with _lock(ruta):
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
    ruta_causas: Path = RUTA_REGISTRO_CAUSAS,
) -> dict:
    """Aplica la cadencia acordada con el usuario: el 1er aviso siempre
    procede; el 2do solo si pasaron al menos 2 dias habiles desde el 1ro.

    Del 3er aviso en adelante ya no hay tope: la cadencia se recalcula en
    cada llamada segun cuanto falta (en dias corridos) para la
    `fecha_audiencia` de la causa asociada (via el `rit` guardado en la
    entrada de seguimiento):
    - Sin `rit`, o el `rit` no tiene `fecha_audiencia` registrada en
      `registro_causas.json`: no hay como elegir cadencia, se reporta motivo
      distinto ("causa no tiene audiencia agendada") para no confundirlo con
      un simple "todavia no toca".
    - Faltan mas de 14 dias corridos: tier "lejano" — repite en bucle 4 dias
      habiles / 2 dias habiles desde el aviso anterior (3er aviso exige 4,
      4to exige 2, 5to vuelve a exigir 4, etc.).
    - Faltan entre 8 y 14 dias corridos: tier "medio" — exige 2 dias habiles
      desde el aviso anterior.
    - Faltan 7 dias corridos o menos (incluida audiencia ya pasada): tier
      "cercano" — exige 1 dia habil desde el aviso anterior.

    Devuelve {"puede": bool, "n_aviso": int, "motivo": str}, donde
    `n_aviso` es el numero de aviso que correspondería crear a continuacion.
    """
    from . import agenda as agenda_mod

    if hoy is None:
        hoy = date.today()
    else:
        hoy = _parsear_fecha(hoy)

    entrada = obtener_seguimiento(thread_id, ruta)
    avisos = entrada["avisos"] if entrada else []
    kwargs_feriados = {} if ruta_feriados is None else {"ruta_feriados": ruta_feriados}

    if len(avisos) == 0:
        return {"puede": True, "n_aviso": 1, "motivo": "sin avisos previos"}

    if len(avisos) == 1:
        transcurridos = agenda_mod.dias_habiles_entre(avisos[0]["fecha"], hoy, **kwargs_feriados)
        if transcurridos >= 2:
            return {"puede": True, "n_aviso": 2, "motivo": f"pasaron {transcurridos} dias habiles desde el 1er aviso"}
        return {
            "puede": False, "n_aviso": 2,
            "motivo": f"solo pasaron {transcurridos} dias habiles desde el 1er aviso (se requieren 2)",
        }

    n_aviso = len(avisos) + 1
    rit = entrada.get("rit") if entrada else None
    causa = obtener_causa(rit, ruta_causas) if rit else None
    fecha_audiencia = causa.get("fecha_audiencia") if causa else None
    if not fecha_audiencia:
        return {
            "puede": False, "n_aviso": n_aviso,
            "motivo": "causa no tiene audiencia agendada, requiere revision manual",
        }

    dias_hasta_audiencia = (_parsear_fecha(fecha_audiencia) - hoy).days
    if dias_hasta_audiencia > 14:
        tier = "lejano"
        posicion = (len(avisos) - 2) % 2
        umbral = 4 if posicion == 0 else 2
    elif dias_hasta_audiencia >= 8:
        tier = "medio"
        umbral = 2
    else:
        tier = "cercano"
        umbral = 1

    transcurridos = agenda_mod.dias_habiles_entre(avisos[-1]["fecha"], hoy, **kwargs_feriados)
    if transcurridos >= umbral:
        return {
            "puede": True, "n_aviso": n_aviso,
            "motivo": f"pasaron {transcurridos} dias habiles desde el ultimo aviso (tier {tier}, exige {umbral})",
        }
    return {
        "puede": False, "n_aviso": n_aviso,
        "motivo": f"solo pasaron {transcurridos} dias habiles desde el ultimo aviso (tier {tier}, se requieren {umbral})",
    }


# ── Registro de pedidos (Fase "seguimiento": documentos y propuestas de
# acuerdo esperando respuesta) ─────────────────────────────────────────────
# Estados abiertos vs. cerrados de un pedido. "gestion_manual" sigue abierto
# a efectos de reporte (aparece en la bandeja de acciones del panel) pero ya
# no se le crean mas borradores de insistencia (agoto los 2 avisos).
ESTADOS_PEDIDO_ABIERTO = {"esperando", "parcial", "gestion_manual"}


def cargar_registro_pedidos(ruta: Path = RUTA_REGISTRO_PEDIDOS) -> dict:
    return _cargar(ruta)


def obtener_pedido(thread_id: str, ruta: Path = RUTA_REGISTRO_PEDIDOS) -> dict | None:
    return cargar_registro_pedidos(ruta).get(thread_id)


def registrar_pedido(thread_id: str, datos: dict, ruta: Path = RUTA_REGISTRO_PEDIDOS) -> dict:
    """Da de alta un pedido nuevo o actualiza (merge) uno existente — mismo
    criterio que `registrar_causa`: los campos nuevos de `datos` pisan a los
    viejos, los que no vienen se conservan.

    `datos` trae, entre otros: rit, tipo ("documentos"|"acuerdo"),
    message_id, fecha_envio (AAAA-MM-DD), destinatario, items_pedidos
    (lista), items_recibidos (lista), estado
    ("esperando"|"parcial"|"completo"|"gestion_manual"), origen
    ("borrador_enviado"|"etiqueta"|"manual"), label_id (si vino por
    etiqueta, para poder quitarla al cerrar el pedido).

    Devuelve la entrada final guardada.
    """
    with _lock(ruta):
        registro = cargar_registro_pedidos(ruta)
        existente = registro.get(thread_id, {})
        fusionada = {**existente, **datos}
        fusionada["thread_id"] = thread_id
        fusionada.setdefault("estado", "esperando")
        fusionada.setdefault("items_recibidos", [])
        fusionada.setdefault("primera_vez_registrado", datetime.now().isoformat())
        fusionada["ultima_revision"] = datetime.now().isoformat()
        registro[thread_id] = fusionada
        _guardar(ruta, registro)
    return fusionada


def pedidos_abiertos(
    ruta: Path = RUTA_REGISTRO_PEDIDOS, ruta_causas: Path = RUTA_REGISTRO_CAUSAS
) -> list:
    """Pedidos que siguen requiriendo seguimiento (ver ESTADOS_PEDIDO_ABIERTO)
    — es lo que recorre la fase "seguimiento" en cada corrida, en vez de
    salir a buscar en Gmail cada vez. Excluye los pedidos cuyo `rit`
    corresponde a una causa con `causa_cerrada: true` en registro_causas.json
    — mismo criterio que `causas_para_goteo` — para no seguir insistiendo (ni
    mostrando en el panel) por una causa que Nico ya cerró a mano, sin
    depender de que alguien revise cada pedido uno por uno."""
    rits_cerrados = {
        entrada["rit"]
        for entrada in cargar_registro_causas(ruta_causas).values()
        if entrada.get("causa_cerrada") and entrada.get("rit")
    }
    return [
        entrada for entrada in cargar_registro_pedidos(ruta).values()
        if entrada.get("estado", "esperando") in ESTADOS_PEDIDO_ABIERTO
        and entrada.get("rit") not in rits_cerrados
    ]


def migrar_pedidos_bootstrap(
    ruta_pedidos: Path = RUTA_REGISTRO_PEDIDOS,
    ruta_seguimiento: Path = RUTA_REGISTRO_SEGUIMIENTO,
    ruta_causas: Path = RUTA_REGISTRO_CAUSAS,
) -> dict:
    """Siembra `registro_pedidos.json` una sola vez, con el backlog que ya
    existia antes de que este registro existiera (ver diseno, Etapa 1.3):

    - cada entrada de `registro_seguimiento.json` (13 al momento de
      disenarlo) entra como pedido "esperando", con su RIT y tipo (traducido
      de "acuerdo-daniela"/"causa-laboral" a "acuerdo", y "documentos" queda
      igual) y `fecha_envio` tomada del primer aviso registrado — para que la
      cadencia (que sigue viviendo en registro_seguimiento.json) seguir
      contando desde donde iba;
    - cada causa de `registro_causas.json` con `borrador_documentos_draft_id`
      vigente entra como pedido "pendiente_envio" (todavia no se mando, asi
      que no es "esperando" respuesta todavia).

    No pisa entradas que ya existan en `registro_pedidos.json` (thread_id
    repetido) — se puede correr mas de una vez sin duplicar. Devuelve
    {"creados": [...thread_id...], "ya_existian": [...thread_id...]}.
    """
    _TIPO_SEGUIMIENTO_A_PEDIDO = {
        "acuerdo-daniela": "acuerdo",
        "causa-laboral": "acuerdo",
        "documentos": "documentos",
    }
    creados = []
    ya_existian = []
    with _lock(ruta_pedidos):
        pedidos = cargar_registro_pedidos(ruta_pedidos)

        for thread_id, entrada in cargar_registro_seguimiento(ruta_seguimiento).items():
            if thread_id in pedidos:
                ya_existian.append(thread_id)
                continue
            avisos = entrada.get("avisos") or []
            fecha_envio = avisos[0]["fecha"] if avisos else None
            pedidos[thread_id] = {
                "thread_id": thread_id,
                "rit": entrada.get("rit"),
                "tipo": _TIPO_SEGUIMIENTO_A_PEDIDO.get(entrada.get("tipo"), entrada.get("tipo")),
                "fecha_envio": fecha_envio,
                "items_pedidos": [],
                "items_recibidos": [],
                "estado": "esperando",
                "origen": "bootstrap_seguimiento",
                "primera_vez_registrado": datetime.now().isoformat(),
                "ultima_revision": datetime.now().isoformat(),
            }
            creados.append(thread_id)

        for rit, causa in cargar_registro_causas(ruta_causas).items():
            draft_id = causa.get("borrador_documentos_draft_id")
            if not draft_id:
                continue
            clave = f"borrador:{draft_id}"
            if clave in pedidos:
                ya_existian.append(clave)
                continue
            pedidos[clave] = {
                "thread_id": causa.get("thread_id"),
                "rit": causa.get("rit", rit),
                "tipo": "documentos",
                "draft_id": draft_id,
                "items_pedidos": [],
                "items_recibidos": [],
                "estado": "pendiente_envio",
                "origen": "bootstrap_borrador",
                "primera_vez_registrado": datetime.now().isoformat(),
                "ultima_revision": datetime.now().isoformat(),
            }
            creados.append(clave)

        _guardar(ruta_pedidos, pedidos)
    return {"creados": creados, "ya_existian": ya_existian}
