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


def log(msg):
    print(f"[calendar_client] {msg}", file=sys.stderr)


def obtener_credenciales():
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


def construir_servicio(credenciales=None):
    from googleapiclient.discovery import build

    if credenciales is None:
        credenciales = obtener_credenciales()
    return build("calendar", "v3", credentials=credenciales)


def diagnostico(servicio=None) -> dict:
    """Devuelve {"email": ..., "scopes": [...]} de la cuenta autenticada, para
    verificar ANTES de operar que el token quedó atado a nmunoz@gomezyriesco.cl."""
    if servicio is None:
        servicio = construir_servicio()
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


def eventos_empresas_interes(desde: date, hasta: date, servicio=None) -> list[dict]:
    """Fase 0 (barrido de calendario): eventos entre `desde` y `hasta` cuyo
    resumen menciona alguna de las 6 empresas de interés, cada uno con
    "empresa_detectada" agregado y "rit_detectado" (o None si el resumen no
    trae un RIT reconocible — ver registro.extraer_rit). Existe para
    encontrar causas con audiencia fijada que nunca se registraron por
    correo (ej. correspondencia anterior a la automatización, o fuera de la
    ventana de backlog de gestion-causas-smu)."""
    eventos = listar_eventos(desde, hasta, servicio=servicio)
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


def buscar_audiencia_por_rit(rit: str, dias_adelante: int = 200, servicio=None) -> list[dict]:
    """Atajo para la Fase 4: busca eventos que mencionen `rit` entre hoy y
    `dias_adelante` días hacia adelante, ordenados por fecha ascendente (la
    más próxima primero)."""
    hoy = date.today()
    eventos = listar_eventos(hoy, hoy + timedelta(days=dias_adelante), servicio=servicio)
    return buscar_eventos_por_rit(eventos, rit)
