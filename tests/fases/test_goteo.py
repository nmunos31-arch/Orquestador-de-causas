import json

from gestion_causas import registro as registro_mod
from gestion_causas.fases import goteo


def _registrar_causa_activa(tmp_path, rit="M-1-2026", **extra):
    ruta_registro = tmp_path / "registro_causas.json"
    datos = {
        "empresa": "Alvi", "demandante": "Perez", "carpeta": str(tmp_path / "Perez con Alvi"),
        "thread_id": "thread-original-1", **extra,
    }
    registro_mod.registrar_causa(rit, datos, ruta=ruta_registro)
    return ruta_registro


def _mapa_hilos_vacio(tmp_path):
    ruta = tmp_path / "mapa_hilos.json"
    ruta.write_text(json.dumps({"rit_a_hilos": {}, "hilos": {}}), encoding="utf-8")
    return ruta


def _correr_goteo(contexto, tmp_path, **kwargs):
    kwargs.setdefault("ruta_registro_causas", tmp_path / "registro_causas.json")
    kwargs.setdefault("ruta_registro_ceco", tmp_path / "registro_ceco.json")
    return goteo.correr(contexto, **kwargs)


class TestCorrerSinCausasActivas:
    def test_devuelve_resumen_sin_novedades(self, tmp_path):
        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(tmp_path / "no_existe.json")},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = goteo.correr(
            contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resumen["fase"] == "goteo"
        assert resumen["titular"] == "Sin causas activas para revisar"
        assert resumen["items"] == []
        assert resumen["acciones"] == []


class TestCorrerCausaSinNovedades:
    def test_causa_activa_sin_hilos_en_el_mapa_no_genera_items(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_hilos_vacio(tmp_path)

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert resumen["items"] == []
        assert any(m["etiqueta"] == "Causas revisadas" and m["valor"] == 1 for m in resumen["metricas"])


class TestGuardaAdjuntosDeRemitenteConfiable:
    def test_guarda_adjunto_de_dominio_confiable_y_lo_reporta_en_items(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(tmp_path, carpeta=str(carpeta_causa))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "Daniela <sorostica@unimarc.cl>",
                    "subject": "RV: Documentos", "cuerpo_texto": "Adjunto el contrato",
                    "adjuntos": [{"filename": "contrato.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 1000}],
                }],
            },
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido falso")
        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert (carpeta_causa / "contrato.pdf").exists()
        assert resumen["items"] == [{
            "rit": "M-1-2026", "titulo": "Perez con Alvi",
            "detalle": "1 documentos nuevos: contrato.pdf",
        }]

    def test_ignora_adjunto_de_dominio_no_confiable(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(tmp_path, carpeta=str(carpeta_causa))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl",
                    "subject": "Re: Documentos", "cuerpo_texto": "",
                    "adjuntos": [{"filename": "borrador.docx", "attachment_id": "att-1", "mime_type": "application/msword", "size": 500}],
                }],
            },
        }), encoding="utf-8")

        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert not (carpeta_causa / "borrador.docx").exists()
        assert resumen["items"] == []

    def test_excluye_invite_ics_aunque_sea_dominio_confiable(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(tmp_path, carpeta=str(carpeta_causa))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "nombre@sb.cl",
                    "subject": "Aceptado: Reunión preparatoria", "cuerpo_texto": "",
                    "adjuntos": [{"filename": "invite.ics", "attachment_id": "att-1", "mime_type": "text/calendar", "size": 300}],
                }],
            },
        }), encoding="utf-8")

        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert not (carpeta_causa / "invite.ics").exists()
        assert resumen["items"] == []
