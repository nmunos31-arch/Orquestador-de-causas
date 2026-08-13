#!/usr/bin/env python3
"""
CLI mecánica para la gestión de causas nuevas desde nmunoz@gomezyriesco.cl
(Fase 1). La IA que corre la tarea programada orquesta estos subcomandos con
Bash/PowerShell y toma las decisiones que requieren leer prosa libre (qué
dice el cuadro resumen, cómo redactar el Resumen); cada subcomando aquí hace
una sola cosa mecánica y determinística, e imprime JSON a stdout para que la
IA lo lea.

Ningún subcomando envía correos ni borra nada — ver gestion_causas/gmail_client.py.

USO (ver también SKILL.md de la tarea "gestion-causas-smu"):
    python -m gestion_causas.cli diagnostico
    python -m gestion_causas.cli buscar-hilos --query "..."
    python -m gestion_causas.cli leer-hilo --thread-id <id>
    python -m gestion_causas.cli guardar-adjunto --message-id <id> --attachment-id <id> --carpeta <ruta> --nombre-archivo <nombre>
    python -m gestion_causas.cli etiquetar-empresa --thread-id <id> --empresa "Rendic Hermanos"
    python -m gestion_causas.cli marcar-procesado --thread-id <id>
    python -m gestion_causas.cli crear-carpeta --apellido <ap> --empresa <emp> --rit <rit>
    python -m gestion_causas.cli registrar-causa --rit <rit> --datos-json <ruta.json>
    python -m gestion_causas.cli bitacora --mensaje "..." [--rit <rit>]
"""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from . import agenda as agenda_mod
from . import bitacora as bitacora_mod
from . import calendar_client
from . import carpetas as carpetas_mod
from . import gmail_client
from . import ics as ics_mod
from . import registro as registro_mod


def _imprimir_json(datos) -> None:
    print(json.dumps(datos, ensure_ascii=False, default=str))


def cmd_diagnostico(args) -> int:
    resultado = gmail_client.diagnostico()
    _imprimir_json(resultado)
    if resultado["email"] != "nmunoz@gomezyriesco.cl":
        print(
            f"ADVERTENCIA: la cuenta autenticada es '{resultado['email']}', "
            "no 'nmunoz@gomezyriesco.cl'. Deten la tarea y revisa el token.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_buscar_hilos(args) -> int:
    hilos = gmail_client.buscar_hilos(args.query, max_resultados=args.max_resultados)
    _imprimir_json({"hilos": hilos, "total": len(hilos)})
    return 0


def cmd_leer_hilo(args) -> int:
    hilo = gmail_client.obtener_hilo(args.thread_id)
    mensajes = []
    for mensaje_crudo in hilo.get("messages", []):
        headers = {h["name"].lower(): h["value"] for h in mensaje_crudo["payload"].get("headers", [])}
        mensajes.append({
            "id": mensaje_crudo["id"],
            "thread_id": mensaje_crudo["threadId"],
            "subject": headers.get("subject", ""),
            "sender": headers.get("from", ""),
            "date": headers.get("date", ""),
            "cuerpo_texto": gmail_client._extraer_texto_plano(mensaje_crudo["payload"]),
            "adjuntos": gmail_client._listar_adjuntos(mensaje_crudo["payload"]),
        })
    _imprimir_json({"thread_id": args.thread_id, "mensajes": mensajes})
    return 0


def cmd_guardar_adjunto(args) -> int:
    contenido = gmail_client.descargar_adjunto(args.message_id, args.attachment_id)
    if carpetas_mod.es_adjunto_firma(args.nombre_archivo, len(contenido)) and not args.forzar:
        _imprimir_json({"guardado": False, "motivo": "parece firma/logo, se omite"})
        return 0
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "guardar-adjunto", "carpeta": args.carpeta, "nombre_archivo": args.nombre_archivo})
        return 0
    resultado = carpetas_mod.guardar_adjunto(Path(args.carpeta), args.nombre_archivo, contenido)
    _imprimir_json({"guardado": resultado["guardado"], "ruta": str(resultado["ruta"])})
    return 0


def cmd_etiquetar_empresa(args) -> int:
    color = gmail_client.COLOR_POR_EMPRESA.get(args.empresa)
    if color is None:
        print(f"Empresa sin color configurado: '{args.empresa}'", file=sys.stderr)
        return 1
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "etiquetar-empresa", "thread_id": args.thread_id, "empresa": args.empresa})
        return 0
    label_id = gmail_client.obtener_o_crear_etiqueta(args.empresa, color=color)
    gmail_client.aplicar_etiqueta_a_hilo(args.thread_id, label_id)
    _imprimir_json({"thread_id": args.thread_id, "etiqueta": args.empresa, "label_id": label_id})
    return 0


def cmd_marcar_procesado(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "marcar-procesado", "thread_id": args.thread_id})
        return 0
    label_id = gmail_client.obtener_o_crear_etiqueta(gmail_client.ETIQUETA_PROCESADO)
    gmail_client.aplicar_etiqueta_a_hilo(args.thread_id, label_id)
    _imprimir_json({"thread_id": args.thread_id, "etiqueta": gmail_client.ETIQUETA_PROCESADO})
    return 0


def cmd_crear_carpeta(args) -> int:
    existente = carpetas_mod.buscar_carpeta_existente_por_rit(args.rit)
    if args.dry_run:
        destino = existente or carpetas_mod.ruta_carpeta_causa(args.apellido, args.empresa, args.rit)
        _imprimir_json({
            "simulado": True, "accion": "crear-carpeta", "carpeta": str(destino),
            "reusada": existente is not None,
        })
        return 0
    carpeta = carpetas_mod.crear_carpeta_causa(args.apellido, args.empresa, args.rit)
    _imprimir_json({"carpeta": str(carpeta), "reusada": existente is not None})
    return 0


def cmd_registrar_causa(args) -> int:
    with open(args.datos_json, "r", encoding="utf-8") as f:
        datos = json.load(f)
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "registrar-causa", "rit": args.rit, "datos": datos})
        return 0
    entrada = registro_mod.registrar_causa(args.rit, datos)
    _imprimir_json(entrada)
    return 0


def cmd_causa_ya_registrada(args) -> int:
    existe = registro_mod.causa_ya_registrada(args.rit)
    _imprimir_json({"rit": args.rit, "ya_registrada": existe})
    return 0


def cmd_obtener_causa(args) -> int:
    entrada = registro_mod.obtener_causa(args.rit)
    _imprimir_json({"rit": args.rit, "causa": entrada})
    return 0


def cmd_bitacora(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "bitacora", "mensaje": args.mensaje})
        return 0
    bitacora_mod.registrar(args.mensaje, rit=args.rit)
    return 0


def cmd_crear_borrador(args) -> int:
    if args.dry_run:
        _imprimir_json({
            "simulado": True, "accion": "crear-borrador",
            "destinatario": args.destinatario, "asunto": args.asunto, "thread_id": args.thread_id,
        })
        return 0
    if args.thread_id:
        existentes = gmail_client.listar_borradores_de_hilo(args.thread_id)
        if existentes:
            _imprimir_json({"creado": False, "motivo": "ya existe un borrador en esta cadena, no se sobrescribe"})
            return 0
    else:
        # Sin thread_id (ej. el borrador de ofrecimiento de la Fase 4, que es
        # un correo nuevo): se busca duplicado por el asunto completo, que
        # siempre trae el RIT.
        existentes = gmail_client.buscar_borrador_por_asunto(args.asunto)
        if existentes:
            _imprimir_json({"creado": False, "motivo": "ya existe un borrador con este asunto, no se sobrescribe"})
            return 0
    with open(args.cuerpo_archivo, "r", encoding="utf-8") as f:
        cuerpo = f.read()
    borrador = gmail_client.crear_borrador(args.destinatario, args.asunto, cuerpo, thread_id=args.thread_id)
    _imprimir_json({"creado": True, "draft_id": borrador.get("id")})
    return 0


def cmd_buscar_eerr_reusable(args) -> int:
    reusable = registro_mod.buscar_eerr_reusable(
        args.ceco, args.fecha_despido, dias_tolerancia=args.dias_tolerancia
    )
    _imprimir_json({"reusable": reusable})
    return 0


def cmd_parece_eerr(args) -> int:
    _imprimir_json({"nombre_archivo": args.nombre_archivo, "parece_eerr": carpetas_mod.parece_eerr(args.nombre_archivo)})
    return 0


def cmd_registrar_eerr(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "registrar-eerr", "ceco": args.ceco, "rit": args.rit})
        return 0
    registro_mod.registrar_eerr_recibido(args.ceco, args.fecha_despido, args.rit)
    _imprimir_json({"registrado": True, "ceco": args.ceco, "rit": args.rit})
    return 0


def cmd_copiar_archivo(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "copiar-archivo", "carpeta_destino": args.carpeta_destino, "nombre_archivo": args.nombre_archivo})
        return 0
    resultado = carpetas_mod.copiar_archivo_local(Path(args.origen), Path(args.carpeta_destino), args.nombre_archivo)
    _imprimir_json({"copiado": resultado["copiado"], "ruta": str(resultado["ruta"])})
    return 0


def cmd_listar_carpeta(args) -> int:
    archivos = carpetas_mod.listar_archivos_carpeta(Path(args.carpeta))
    _imprimir_json({"carpeta": args.carpeta, "archivos": archivos})
    return 0


def cmd_causas_activas(args) -> int:
    causas = registro_mod.causas_para_goteo(dias_ventana_post_audiencia=args.dias_ventana)
    _imprimir_json({"causas": causas, "total": len(causas)})
    return 0


def cmd_dias_habiles_antes(args) -> int:
    fecha = agenda_mod.dias_habiles_antes(args.fecha, args.n)
    _imprimir_json({"fecha": str(fecha)})
    return 0


def cmd_dias_corridos_antes(args) -> int:
    fecha = agenda_mod.dias_corridos_antes(args.fecha, args.n)
    _imprimir_json({"fecha": str(fecha)})
    return 0


def cmd_diagnostico_calendario(args) -> int:
    resultado = calendar_client.diagnostico()
    _imprimir_json(resultado)
    if resultado["email"] != "nmunoz@gomezyriesco.cl":
        print(
            f"ADVERTENCIA: la cuenta autenticada es '{resultado['email']}', "
            "no 'nmunoz@gomezyriesco.cl'. Deten la tarea y revisa el token.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_buscar_audiencia_por_rit(args) -> int:
    if args.ics:
        eventos = ics_mod.buscar_audiencia_por_rit(args.ics, args.rit)
    else:
        eventos = calendar_client.buscar_audiencia_por_rit(args.rit, dias_adelante=args.dias_adelante)
    _imprimir_json({"rit": args.rit, "eventos": eventos, "total": len(eventos)})
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="No escribe nada (ni Gmail ni disco); solo informa qué haría",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("diagnostico", help="Verifica qué cuenta y scopes tiene el token guardado")
    p.set_defaults(func=cmd_diagnostico)

    p = sub.add_parser("buscar-hilos", help="Busca hilos con sintaxis de búsqueda de Gmail")
    p.add_argument("--query", required=True)
    p.add_argument("--max-resultados", type=int, default=50)
    p.set_defaults(func=cmd_buscar_hilos)

    p = sub.add_parser("leer-hilo", help="Trae todos los mensajes de un hilo, con cuerpo y adjuntos")
    p.add_argument("--thread-id", required=True)
    p.set_defaults(func=cmd_leer_hilo)

    p = sub.add_parser("guardar-adjunto", help="Descarga un adjunto y lo guarda en una carpeta (sin pisar)")
    p.add_argument("--message-id", required=True)
    p.add_argument("--attachment-id", required=True)
    p.add_argument("--carpeta", required=True)
    p.add_argument("--nombre-archivo", required=True)
    p.add_argument("--forzar", action="store_true", help="Guardar aunque parezca firma/logo")
    p.set_defaults(func=cmd_guardar_adjunto)

    p = sub.add_parser("etiquetar-empresa", help="Aplica la etiqueta de color de la empresa al hilo")
    p.add_argument("--thread-id", required=True)
    p.add_argument("--empresa", required=True, choices=sorted(gmail_client.COLOR_POR_EMPRESA))
    p.set_defaults(func=cmd_etiquetar_empresa)

    p = sub.add_parser("marcar-procesado", help=f"Aplica la etiqueta '{gmail_client.ETIQUETA_PROCESADO}' al hilo")
    p.add_argument("--thread-id", required=True)
    p.set_defaults(func=cmd_marcar_procesado)

    p = sub.add_parser("crear-carpeta", help="Crea (si no existe) la carpeta de la causa en Minutas")
    p.add_argument("--apellido", required=True)
    p.add_argument("--empresa", required=True)
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_crear_carpeta)

    p = sub.add_parser("registrar-causa", help="Da de alta o actualiza la causa en el registro local")
    p.add_argument("--rit", required=True)
    p.add_argument("--datos-json", required=True, help="Ruta a un JSON con los campos a guardar/actualizar")
    p.set_defaults(func=cmd_registrar_causa)

    p = sub.add_parser("causa-ya-registrada", help="Consulta si un RIT ya está en el registro")
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_causa_ya_registrada)

    p = sub.add_parser("obtener-causa", help="Trae los datos guardados de una causa (carpeta, ceco, thread_id, etc.)")
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_obtener_causa)

    p = sub.add_parser("bitacora", help="Agrega una línea a la bitácora")
    p.add_argument("--mensaje", required=True)
    p.add_argument("--rit", default=None)
    p.set_defaults(func=cmd_bitacora)

    p = sub.add_parser("crear-borrador", help="Crea un borrador (NUNCA lo envía). No sobrescribe uno ya existente en la cadena.")
    p.add_argument("--destinatario", required=True)
    p.add_argument("--asunto", required=True)
    p.add_argument("--cuerpo-archivo", required=True, help="Ruta a un .txt con el cuerpo del borrador")
    p.add_argument("--thread-id", default=None, help="Si se indica, el borrador queda como respuesta en esa cadena")
    p.set_defaults(func=cmd_crear_borrador)

    p = sub.add_parser("buscar-eerr-reusable", help="Fase 2: busca si ya hay un EERR recibido reusable para este CECO/fecha")
    p.add_argument("--ceco", required=True)
    p.add_argument("--fecha-despido", required=True, help="AAAA-MM-DD")
    p.add_argument("--dias-tolerancia", type=int, default=90)
    p.set_defaults(func=cmd_buscar_eerr_reusable)

    p = sub.add_parser("parece-eerr", help="Fase 3: heurística de nombre para saber si un archivo parece el Estado de Resultados")
    p.add_argument("--nombre-archivo", required=True)
    p.set_defaults(func=cmd_parece_eerr)

    p = sub.add_parser("registrar-eerr", help="Fase 3: anota que se recibió el EERR de un CECO para esta causa")
    p.add_argument("--ceco", required=True)
    p.add_argument("--fecha-despido", required=True, help="AAAA-MM-DD")
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_registrar_eerr)

    p = sub.add_parser("copiar-archivo", help="Fase 2: copia un archivo local (ej. EERR reusado) a la carpeta de otra causa, sin pisar")
    p.add_argument("--origen", required=True)
    p.add_argument("--carpeta-destino", required=True)
    p.add_argument("--nombre-archivo", required=True)
    p.set_defaults(func=cmd_copiar_archivo)

    p = sub.add_parser("listar-carpeta", help="Fase 3: lista los archivos que ya tiene guardados la carpeta de una causa")
    p.add_argument("--carpeta", required=True)
    p.set_defaults(func=cmd_listar_carpeta)

    p = sub.add_parser("causas-activas", help="Fase 3: causas a revisar por goteo de documentos (audiencia no muy pasada o sin fecha)")
    p.add_argument("--dias-ventana", type=int, default=60)
    p.set_defaults(func=cmd_causas_activas)

    p = sub.add_parser("dias-habiles-antes", help="Fase 4: fecha N días hábiles antes de una fecha (salta fin de semana y feriados)")
    p.add_argument("--fecha", required=True, help="AAAA-MM-DD")
    p.add_argument("--n", type=int, required=True)
    p.set_defaults(func=cmd_dias_habiles_antes)

    p = sub.add_parser("dias-corridos-antes", help="Fase 4: fecha N días corridos antes de una fecha")
    p.add_argument("--fecha", required=True, help="AAAA-MM-DD")
    p.add_argument("--n", type=int, required=True)
    p.set_defaults(func=cmd_dias_corridos_antes)

    p = sub.add_parser("diagnostico-calendario", help="Verifica qué cuenta tiene el token de Calendar guardado")
    p.set_defaults(func=cmd_diagnostico_calendario)

    p = sub.add_parser(
        "buscar-audiencia-por-rit",
        help="Fase 4: busca eventos que mencionan este RIT en el calendario de nmunoz@gomezyriesco.cl (API directa; --ics fuerza el modo antiguo por archivo exportado)",
    )
    p.add_argument("--rit", required=True)
    p.add_argument("--dias-adelante", type=int, default=200, help="Ventana de búsqueda hacia adelante desde hoy (API)")
    p.add_argument("--ics", default=None, help="Ruta a un .ics exportado a mano; si se indica, se usa en vez de la API")
    p.set_defaults(func=cmd_buscar_audiencia_por_rit)

    return parser


def main(argv=None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error ({type(e).__name__}): {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
