#!/usr/bin/env python3
"""
Cliente Calendar propio (OAuth de escritorio) para el calendario del trabajo
nmunoz@gomezyriesco.cl.

Existe porque el conector de Calendar de Claude está autenticado como la
cuenta personal (nmunos31@gmail.com), y el calendario de trabajo le aparece
compartido con accessRole "freeBusyReader" (ve ocupado/libre, pero no el
título de los eventos) — no sirve para encontrar el RIT ni el tipo de
audiencia. Reemplaza al mecanismo anterior de exportar el .ics a mano por
navegador (gestion_causas/ics.py, que se mantiene como referencia/respaldo).

Mismo client_secret.json (proyecto informe-semanal-501614) que usa
gmail_client.py, pero con un token SEPARADO (token_calendar_trabajo.json)
porque el scope es distinto.

GARANTÍA DE SEGURIDAD: scope calendar.readonly únicamente. Este módulo NO
expone ninguna función que cree, modifique o borre eventos — ver el plan del
proyecto: la automatización solo lee el calendario, nunca lo toca.
"""

import json
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from .ics import buscar_eventos_por_rit
from .registro import extraer_rit

# Alias por los que se reconoce a cada empresa en el texto de un evento de
# calendario (títulos como "Audiencia Unica RIT M-643-2026 Iturriaga con
# Rendic" o "Audiencia única "Rebolledo con Salcobrand" M-637-2026"). Usado
# por el barrido de calendario (Fase 0) para detectar causas de las 6
# empresas de interés que no llegaron a registrarse por correo (ver
# gmail_client.COLOR_POR_EMPRESA para los nombres canónicos).
EMPRESAS_ALIAS = {
    "Rendic Hermanos": ["rendic"],
    "Alvi": ["alvi"],
    "Super 10": ["super 10"],
    "Servicios Logísticos Santiago": ["servicios logisticos santiago", "ssll"],
    "Preunic": ["preunic"],
    "Salcobrand": ["salcobrand"],
}


def _normalizar_texto(valor: str) -> str:
    """Minúsculas y sin tildes, para comparar alias sin depender de acentos
    ("única" vs "unica", "Súper" vs "Super")."""
    sin_tildes = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("ascii")
    return sin_tildes.lower()


def detectar_empresa(texto: str) -> str | None:
    """Devuelve el nombre canónico de la empresa (una de las 6) si `texto`
    menciona alguno de sus alias, o None si no reconoce ninguna."""
    normalizado = _normalizar_texto(texto)
    for empresa, alias in EMPRESAS_ALIAS.items():
        if any(_normalizar_texto(a) in normalizado for a in alias):
            return empresa
    return None

CLIENT_SECRET_PATH = str(
    Path(__file__).parent.parent.parent / "Automatizacion Informe Semanal" / "client_secret.json"
)
TOKEN_PATH = str(Path(__file__).parent / "token_calendar_trabajo.json")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

RUTA_CACHE_EVENTOS_CALENDARIO = Path(__file__).parent / "cache_eventos_calendario.json"


def log(msg):
    print(f"[calendar_client] {msg}", file=sys.stderr)


def obtener_credenciales(permitir_login: bool = True):
    """Mismo patrón que gmail_client.obtener_credenciales()."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if Path(TOKEN_PATH).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        necesita_login = True
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                necesita_login = False
            except RefreshError as e:
                log(f"El token guardado ya no sirve ({e}); pidiendo login de nuevo...")

        if necesita_login:
            if not permitir_login:
                # Corrida desatendida (ver contexto-corrida): el flujo de
                # InstalledAppFlow abre un navegador y NUNCA vuelve si no hay
                # nadie para completarlo, asi que se falla rapido en vez de
                # colgar la tarea programada.
                raise RuntimeError(
                    "El token de Calendar de trabajo (nmunoz@gomezyriesco.cl) no existe o ya no sirve, y se pidio "
                    "no abrir el login interactivo. Corre "
                    "`python -m gestion_causas.cli diagnostico-calendario` una vez a mano para autorizarlo."
                )
            if not Path(CLIENT_SECRET_PATH).exists():
                sys.exit(
                    f"Falta '{CLIENT_SECRET_PATH}'. Descárgalo desde Google Cloud "
                    f"Console (credenciales OAuth de tipo Aplicación de escritorio)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            log("Abriendo navegador para iniciar sesión — usa la cuenta nmunoz@gomezyriesco.cl.")
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return creds


def construir_servicio(credenciales=None, permitir_login: bool = True):
    from googleapiclient.discovery import build

    if credenciales is None:
        credenciales = obtener_credenciales(permitir_login=permitir_login)
    return build("calendar", "v3", credentials=credenciales)


def diagnostico(servicio=None, permitir_login: bool = True) -> dict:
    """Devuelve {"email": ..., "scopes": [...]} de la cuenta autenticada, para
    verificar ANTES de operar que el token quedó atado a nmunoz@gomezyriesco.cl."""
    if servicio is None:
        servicio = construir_servicio(permitir_login=permitir_login)
    calendario = servicio.calendarList().get(calendarId="primary").execute()
    return {"email": calendario.get("id"), "scopes": SCOPES}


def _fecha_de_evento(evento: dict):
    inicio = evento.get("start", {})
    if "date" in inicio:
        return datetime.strptime(inicio["date"], "%Y-%m-%d").date()
    if "dateTime" in inicio:
        # dateTime trae offset (ej. 2026-08-21T10:40:00-04:00); tomamos solo
        # la fecha en la hora local del evento, sin convertir zona horaria.
        return datetime.fromisoformat(inicio["dateTime"]).date()
    return None


def listar_eventos(desde: date, hasta: date, servicio=None) -> list[dict]:
    """Trae los eventos del calendario primario entre `desde` y `hasta`
    (inclusive), devueltos como {"fecha": date, "resumen": str}, ordenados
    por fecha ascendente. Eventos sin fecha o sin título se omiten."""
    if servicio is None:
        servicio = construir_servicio()

    time_min = datetime.combine(desde, datetime.min.time()).isoformat() + "Z"
    time_max = datetime.combine(hasta + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

    eventos = []
    page_token = None
    while True:
        resultado = servicio.events().list(
            calendarId="primary", timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy="startTime", pageToken=page_token,
        ).execute()
        for crudo in resultado.get("items", []):
            fecha = _fecha_de_evento(crudo)
            resumen = crudo.get("summary")
            if fecha and resumen:
                eventos.append({"fecha": fecha, "resumen": resumen})
        page_token = resultado.get("nextPageToken")
        if not page_token:
            break

    return eventos


def guardar_cache_eventos(
    ruta: Path = RUTA_CACHE_EVENTOS_CALENDARIO, dias_adelante: int = 200, servicio=None
) -> dict:
    """Trae TODOS los eventos del calendario primario en el rango de
    `dias_adelante` días desde hoy (misma consulta que hace
    `buscar_audiencia_por_rit` por cada RIT) y los guarda en `ruta` como JSON.
    Existe para que una corrida que consulta muchas causas seguidas (goteo,
    agenda) traiga el calendario una sola vez en vez de una vez por causa —
    ver `buscar_audiencia_por_rit_desde_cache`. Devuelve {"total", "ruta"}."""
    hoy = date.today()
    hasta = hoy + timedelta(days=dias_adelante)
    eventos = listar_eventos(hoy, hasta, servicio=servicio)
    contenido = {
        "generado_en": datetime.now().isoformat(),
        # `desde`/`hasta` dejan constancia de que rango cubre este archivo, para
        # que un consumidor que necesita otro rango (ej. eventos-calendario con
        # --dias-atras) sepa que el cache no le sirve, en vez de devolver un
        # resultado parcial en silencio.
        "desde": str(hoy),
        "hasta": str(hasta),
        "eventos": [{"fecha": str(e["fecha"]), "resumen": e["resumen"]} for e in eventos],
    }
    ruta = Path(ruta)
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"total": len(eventos), "ruta": str(ruta), "desde": str(hoy), "hasta": str(hasta)}


def cargar_cache_eventos(ruta: Path = RUTA_CACHE_EVENTOS_CALENDARIO) -> dict:
    """Lee un cache generado por `guardar_cache_eventos` y devuelve
    {"eventos": [{"fecha": date, "resumen": str}], "desde": date|None,
    "hasta": date|None}. Lanza FileNotFoundError si `ruta` no existe (el
    llamador decide si cae de vuelta a la API)."""
    contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
    eventos = [
        {"fecha": datetime.strptime(e["fecha"], "%Y-%m-%d").date(), "resumen": e["resumen"]}
        for e in contenido["eventos"]
    ]

    def _fecha(clave):
        valor = contenido.get(clave)
        return datetime.strptime(valor, "%Y-%m-%d").date() if valor else None

    return {"eventos": eventos, "desde": _fecha("desde"), "hasta": _fecha("hasta")}


def buscar_audiencia_por_rit_desde_cache(rit: str, ruta: Path = RUTA_CACHE_EVENTOS_CALENDARIO) -> list[dict]:
    """Igual que `buscar_audiencia_por_rit` pero filtrando eventos ya
    guardados en `ruta` (ver `guardar_cache_eventos`) en vez de llamar a la
    API — para no repetir la misma consulta de 200 días por cada causa
    dentro de una misma corrida. Lanza FileNotFoundError si `ruta` no
    existe (el llamador decide si cae de vuelta a `buscar_audiencia_por_rit`
    en ese caso)."""
    return buscar_eventos_por_rit(cargar_cache_eventos(ruta)["eventos"], rit)


def clasificar_tipo_audiencia(resumen: str) -> str:
    """Determina el tipo de audiencia a partir del título del evento de
    calendario — mismo criterio que usaban por separado goteo.md (paso 3a) y
    agenda.md (paso 2), unificado acá para que no vuelvan a divergir. "Única"
    y "Juicio" comparten palabra ("audiencia de juicio" contiene "audiencia"),
    así que el orden de los chequeos importa: Juicio primero. Si el título no
    menciona ninguno de los tres, devuelve "Ambiguo" — nunca se adivina."""
    texto = _normalizar_texto(resumen).replace(".", "")
    if "audiencia de juicio" in texto or "aud de juicio" in texto:
        return "Juicio"
    if "audiencia unica" in texto or "aud unica" in texto:
        return "Unica"
    if "audiencia preparatoria" in texto or "aud preparatoria" in texto:
        return "Preparatoria"
    if "reunion preparatoria" in texto:
        # Alias real observado en el calendario (ej. 'Reunión preparatoria
        # "Tiznado con Salcobrand" M-744-2026') — el tribunal la agenda así
        # aunque procesalmente es la audiencia preparatoria. Confirmado
        # 2026-09-01: 16 de 24 audiencias activas usaban esta redacción.
        return "Preparatoria"
    return "Ambiguo"


def primer_evento_futuro(eventos: list[dict], hoy: date | None = None) -> dict | None:
    """De una lista de eventos ya filtrados por RIT, se queda con el primero
    de hoy en adelante (ordena por fecha antes de elegir, por si el llamador
    no los trae ya ordenados). None si todos son pasados o la lista está
    vacía — "no hay audiencia próxima todavía" para ese RIT."""
    if hoy is None:
        hoy = date.today()
    futuros = sorted((e for e in eventos if e["fecha"] >= hoy), key=lambda e: e["fecha"])
    return futuros[0] if futuros else None


def mapa_audiencias_por_rit(rits: list[str], eventos: list[dict], hoy: date | None = None) -> dict:
    """Para cada RIT en `rits`, busca sus eventos en `eventos` (ya cargados,
    ej. desde el cache de calendario), se queda con el primero de hoy en
    adelante y clasifica su tipo. Reemplaza a `goteo.md` paso 3a y
    `agenda.md` paso 2 resolviendo cada uno lo mismo por separado con
    criterios que ya habían divergido (goteo solo distinguía Juicio/no-Juicio;
    agenda distinguía las 3 variantes).

    Los RIT sin audiencia próxima no aparecen en el resultado — mismo
    criterio de "sáltala" que usaban ambas fases. Devuelve
    `{rit: {"fecha": "YYYY-MM-DD", "resumen": str, "tipo": str}}`."""
    resultado = {}
    for rit in rits:
        evento = primer_evento_futuro(buscar_eventos_por_rit(eventos, rit), hoy=hoy)
        if evento is None:
            continue
        resultado[rit] = {
            "fecha": str(evento["fecha"]),
            "resumen": evento["resumen"],
            "tipo": clasificar_tipo_audiencia(evento["resumen"]),
        }
    return resultado


def filtrar_empresas_interes(eventos: list[dict]) -> list[dict]:
    """Se queda con los eventos cuyo resumen menciona alguna de las 6 empresas
    de interés, agregándoles "empresa_detectada" y "rit_detectado" (o None si
    el resumen no trae un RIT reconocible — ver registro.extraer_rit).

    Vive aparte de `eventos_empresas_interes` para que la variante que lee el
    cache en disco aplique exactamente el mismo criterio que la que llama a la
    API, sin duplicarlo."""
    resultado = []
    for evento in eventos:
        empresa = detectar_empresa(evento["resumen"])
        if empresa is None:
            continue
        rit = extraer_rit(evento["resumen"])
        if rit is not None and rit.startswith("I-"):
            # RIT "I-" es de Inspección del Trabajo (trámite administrativo), no
            # una causa judicial laboral — fuera del alcance de este proceso.
            continue
        resultado.append({
            **evento,
            "empresa_detectada": empresa,
            "rit_detectado": rit,
        })
    return resultado


def eventos_empresas_interes(desde: date, hasta: date, servicio=None) -> list[dict]:
    """Fase 0 (barrido de calendario): eventos entre `desde` y `hasta` cuyo
    resumen menciona alguna de las 6 empresas de interés. Existe para
    encontrar causas con audiencia fijada que nunca se registraron por
    correo (ej. correspondencia anterior a la automatización, o fuera de la
    ventana de backlog de gestion-causas-smu)."""
    return filtrar_empresas_interes(listar_eventos(desde, hasta, servicio=servicio))


def eventos_empresas_interes_desde_cache(
    desde: date, hasta: date, ruta: Path = RUTA_CACHE_EVENTOS_CALENDARIO
) -> list[dict]:
    """Igual que `eventos_empresas_interes` pero filtrando el cache que dejó
    `guardar_cache_eventos` al principio de la corrida, en vez de llamar a la
    API — el rango de la Fase 0 (90 días hacia adelante) está contenido en el
    de ese cache (200 días), así que la corrida entera necesita una sola
    llamada a Calendar.

    Lanza FileNotFoundError si el cache no existe y ValueError si no cubre el
    rango pedido (ej. --dias-atras > 0, o un --dias-adelante mayor al del
    cache): devolver un resultado parcial en silencio sería peor que caer de
    vuelta a la API."""
    cache = cargar_cache_eventos(ruta)
    if cache["desde"] is None or cache["hasta"] is None:
        raise ValueError(
            f"El cache '{ruta}' no declara el rango que cubre (lo generó una versión "
            "anterior); regeneralo con `cache-eventos-calendario`."
        )
    if desde < cache["desde"] or hasta > cache["hasta"]:
        raise ValueError(
            f"El cache '{ruta}' cubre {cache['desde']}..{cache['hasta']} y se pidió "
            f"{desde}..{hasta}; no alcanza."
        )
    en_rango = [e for e in cache["eventos"] if desde <= e["fecha"] <= hasta]
    return filtrar_empresas_interes(en_rango)


def buscar_audiencia_por_rit(rit: str, dias_adelante: int = 200, servicio=None) -> list[dict]:
    """Atajo para la Fase 4: busca eventos que mencionen `rit` entre hoy y
    `dias_adelante` días hacia adelante, ordenados por fecha ascendente (la
    más próxima primero)."""
    hoy = date.today()
    eventos = listar_eventos(hoy, hoy + timedelta(days=dias_adelante), servicio=servicio)
    return buscar_eventos_por_rit(eventos, rit)
