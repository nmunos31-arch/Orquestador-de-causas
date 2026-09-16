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


class TestDeteccionDeAcuerdoYPago:
    def test_registra_estado_acuerdo_pendiente_pago_cuando_claude_confirma_cierre(self, tmp_path, monkeypatch):
        ruta_registro = _registrar_causa_activa(tmp_path, carpeta=str(tmp_path / "Perez con Alvi"))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl",
                    "subject": "Re: Acuerdo", "cuerpo_texto": "Se aprobó el acuerdo por $500.000", "adjuntos": [],
                }],
            },
        }), encoding="utf-8")

        llamadas = []

        def preguntar_falso(tarea, contexto, schema):
            llamadas.append(contexto)
            return {"acuerdo_cerrado": True, "pago_confirmado": False, "justificacion": "Acta de conciliación aprobada"}

        monkeypatch.setattr(goteo.reasoning, "preguntar", preguntar_falso)

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["estado_acuerdo"] == "pendiente_pago"
        assert len(llamadas) == 1
        assert resumen["acciones"] == [{
            "rit": "M-1-2026", "que": "Acuerdo alcanzado, pendiente de pago", "urgencia": "alta",
        }]

    def test_no_llama_a_claude_si_la_causa_no_tiene_hilos_nuevos(self, tmp_path, monkeypatch):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_hilos_vacio(tmp_path)

        llamadas = []
        monkeypatch.setattr(goteo.reasoning, "preguntar", lambda *a, **k: llamadas.append(1))

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        _correr_goteo(contexto, tmp_path)

        assert llamadas == []

    def test_anota_accion_si_reasoning_devuelve_error(self, tmp_path, monkeypatch):
        _registrar_causa_activa(tmp_path, carpeta=str(tmp_path / "Perez con Alvi"))

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {"thread-1": [{
                "id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl",
                "subject": "Re: Acuerdo", "cuerpo_texto": "algo", "adjuntos": [],
            }]},
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.reasoning, "preguntar", lambda *a, **k: {"error": "Claude no devolvió JSON válido"})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert resumen["acciones"] == [{
            "rit": "M-1-2026",
            "que": "No se pudo evaluar acuerdo/pago automáticamente: Claude no devolvió JSON válido",
            "urgencia": "media",
        }]


class TestDeteccionDeEerr:
    def test_registra_eerr_cuando_el_nombre_del_adjunto_calza_y_hay_ceco_y_fecha_despido(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(
            tmp_path, carpeta=str(carpeta_causa), ceco="1234", fecha_despido="2026-01-15",
        )
        ruta_ceco = tmp_path / "registro_ceco.json"

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {"thread-1": [{
                "id": "msg-1", "thread_id": "thread-1", "sender": "nombre@sb.cl",
                "subject": "EERR", "cuerpo_texto": "",
                "adjuntos": [{"filename": "EERR 2026.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 900}],
            }]},
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido")
        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path, ruta_registro_ceco=ruta_ceco)

        reusable = registro_mod.buscar_eerr_reusable("1234", "2026-01-15", ruta=ruta_ceco)
        assert reusable == {"fecha_despido": "2026-01-15", "rit_causa": "M-1-2026"}
        assert any(m["etiqueta"] == "Identificados como EERR" and m["valor"] == 1 for m in resumen["metricas"])

    def test_no_registra_eerr_si_falta_ceco_o_fecha_despido(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Perez con Alvi"
        _registrar_causa_activa(tmp_path, carpeta=str(carpeta_causa))  # sin ceco ni fecha_despido
        ruta_ceco = tmp_path / "registro_ceco.json"

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {"thread-1": [{
                "id": "msg-1", "thread_id": "thread-1", "sender": "nombre@sb.cl",
                "subject": "EERR", "cuerpo_texto": "",
                "adjuntos": [{"filename": "EERR 2026.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 900}],
            }]},
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido")
        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path, ruta_registro_ceco=ruta_ceco)

        assert any(m["etiqueta"] == "Identificados como EERR" and m["valor"] == 0 for m in resumen["metricas"])
        assert not ruta_ceco.exists()


class TestCausaSinCarpeta:
    def test_no_falla_si_la_causa_no_tiene_carpeta_y_lo_anota_en_notas(self, tmp_path):
        ruta_registro = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("T-10-2026", {
            "empresa": "Salcobrand", "demandante": "Amengual", "thread_id": "thread-x",
        }, ruta=ruta_registro)  # sin carpeta

        ruta_mapa = _mapa_hilos_vacio(tmp_path)

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = goteo.correr(
            contexto,
            ruta_registro_causas=ruta_registro,
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resumen["items"] == []
        assert any("T-10-2026" in n["detalle"] for n in resumen["notas"])
        entrada = registro_mod.obtener_causa("T-10-2026", ruta=ruta_registro)
        assert entrada["goteo_ultima_revision"] == "2026-09-15"

    def test_otra_causa_con_carpeta_se_procesa_normalmente_aunque_otra_no_tenga(self, tmp_path, monkeypatch):
        ruta_registro = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("T-10-2026", {
            "empresa": "Salcobrand", "demandante": "Amengual", "thread_id": "thread-x",
        }, ruta=ruta_registro)  # sin carpeta
        carpeta_causa_2 = tmp_path / "Perez con Alvi"
        registro_mod.registrar_causa("M-1-2026", {
            "empresa": "Alvi", "demandante": "Perez", "carpeta": str(carpeta_causa_2),
            "thread_id": "thread-y",
        }, ruta=ruta_registro)

        ruta_mapa = tmp_path / "mapa_hilos.json"
        ruta_mapa.write_text(json.dumps({
            "rit_a_hilos": {"M-1-2026": ["thread-1"]},
            "hilos": {
                "thread-1": [{
                    "id": "msg-1", "thread_id": "thread-1", "sender": "nombre@sb.cl",
                    "subject": "Documentos", "cuerpo_texto": "",
                    "adjuntos": [{"filename": "contrato.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 1000}],
                }],
            },
        }), encoding="utf-8")

        monkeypatch.setattr(goteo.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido")
        monkeypatch.setattr(goteo, "_detectar_acuerdo_y_pago", lambda mensajes: {"acuerdo_cerrado": False, "pago_confirmado": False, "justificacion": ""})

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = goteo.correr(
            contexto,
            ruta_registro_causas=ruta_registro,
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert (carpeta_causa_2 / "contrato.pdf").exists()
        assert any(item["rit"] == "M-1-2026" for item in resumen["items"])
        assert any("T-10-2026" in n["detalle"] for n in resumen["notas"])
