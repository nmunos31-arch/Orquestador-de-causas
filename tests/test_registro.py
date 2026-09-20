import os
import threading
import time
from datetime import date

import pytest

from gestion_causas import registro as registro_mod

from gestion_causas.registro import (
    buscar_eerr_reusable,
    causa_ya_registrada,
    causas_con_borrador_pendiente,
    causas_para_goteo,
    extraer_rit,
    normalizar_rit,
    obtener_causa,
    obtener_seguimiento,
    puede_insistir,
    registrar_aviso,
    registrar_causa,
    registrar_eerr_recibido,
)


def _feriados_sin_feriados(tmp_path):
    import json

    ruta = tmp_path / "feriados.json"
    ruta.write_text(json.dumps({"2026": []}), encoding="utf-8")
    return ruta


class TestNormalizarRit:
    def test_quita_espacios_y_normaliza_guion(self):
        assert normalizar_rit(" O‑348‑2026 ") == "O-348-2026"

    def test_ignora_mayusculas(self):
        assert normalizar_rit("o-348-2026") == normalizar_rit("O-348-2026")


class TestExtraerRit:
    def test_encuentra_rit_en_texto_libre(self):
        assert extraer_rit('Audiencia única "Rebolledo con Salcobrand" M-637-2026') == "M-637-2026"

    def test_encuentra_rit_con_guion_no_separable(self):
        assert extraer_rit("Audiencia Unica RIT M‑643‑2026 Iturriaga con Rendic") == "M-643-2026"

    def test_devuelve_none_si_no_hay_rit(self):
        assert extraer_rit("Reunión equipo semanal") is None

    def test_normaliza_letra_a_mayuscula(self):
        assert extraer_rit("causa m-637-2026") == "M-637-2026"


class TestRegistrarCausa:
    def test_alta_causa_nueva(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        assert not causa_ya_registrada("O-348-2026", ruta)

        registrar_causa("O-348-2026", {"empresa": "Servicios Logísticos Santiago"}, ruta)

        assert causa_ya_registrada("O-348-2026", ruta)
        entrada = obtener_causa("O-348-2026", ruta)
        assert entrada["empresa"] == "Servicios Logísticos Santiago"
        assert entrada["rit"] == "O-348-2026"

    def test_rit_duplicado_no_crea_dos_entradas(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("O-88-2026", {"empresa": "Rendic Hermanos"}, ruta)
        registrar_causa("o‑88‑2026", {"empresa": "Rendic Hermanos"}, ruta)

        import json

        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        assert len(contenido) == 1

    def test_ceco_que_llega_tarde_actualiza_sin_perder_lo_anterior(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-6-2026", {"empresa": "Rendic Hermanos", "tiene_ceco": False}, ruta)
        registrar_causa("M-6-2026", {"ceco": "1234", "tiene_ceco": True}, ruta)

        entrada = obtener_causa("M-6-2026", ruta)
        assert entrada["empresa"] == "Rendic Hermanos"
        assert entrada["ceco"] == "1234"
        assert entrada["tiene_ceco"] is True

    def test_causa_inexistente_devuelve_none(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        assert obtener_causa("M-9999-2026", ruta) is None


class TestCausasConBorradorPendiente:
    def test_incluye_causa_con_draft_id_seteado(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"empresa": "Alvi", "borrador_documentos_draft_id": "d1"}, ruta)

        pendientes = causas_con_borrador_pendiente(ruta)

        assert len(pendientes) == 1
        assert pendientes[0]["rit"] == "M-1-2026"

    def test_excluye_causa_sin_draft_id(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-2-2026", {"empresa": "Alvi"}, ruta)

        assert causas_con_borrador_pendiente(ruta) == []

    def test_excluye_causa_con_draft_id_limpiado_a_none(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-3-2026", {"empresa": "Alvi", "borrador_documentos_draft_id": "d1"}, ruta)
        registrar_causa("M-3-2026", {"borrador_documentos_draft_id": None}, ruta)

        assert causas_con_borrador_pendiente(ruta) == []


class TestReusoEerr:
    def test_reusa_dentro_de_3_meses(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 15), "M-8-2026", ruta)

        reusable = buscar_eerr_reusable("1234", date(2026, 3, 1), dias_tolerancia=90, ruta=ruta)
        assert reusable is not None
        assert reusable["rit_causa"] == "M-8-2026"

    def test_no_reusa_fuera_de_3_meses(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 1), "M-8-2026", ruta)

        reusable = buscar_eerr_reusable("1234", date(2026, 8, 1), dias_tolerancia=90, ruta=ruta)
        assert reusable is None

    def test_ceco_distinto_no_se_confunde(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 15), "M-8-2026", ruta)

        reusable = buscar_eerr_reusable("5678", date(2026, 1, 20), dias_tolerancia=90, ruta=ruta)
        assert reusable is None

    def test_ceco_sin_registro_devuelve_none(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        assert buscar_eerr_reusable(None, date(2026, 1, 1), ruta=ruta) is None

    def test_elige_el_mas_cercano_si_hay_varios(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 1), "M-1-2026", ruta)
        registrar_eerr_recibido("1234", date(2026, 3, 1), "M-2-2026", ruta)

        reusable = buscar_eerr_reusable("1234", date(2026, 3, 10), dias_tolerancia=90, ruta=ruta)
        assert reusable["rit_causa"] == "M-2-2026"


class TestCausasParaGoteo:
    def test_incluye_causa_sin_fecha_audiencia(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"empresa": "Alvi"}, ruta)

        activas = causas_para_goteo(hoy=date(2026, 8, 12), ruta=ruta)
        assert len(activas) == 1
        assert activas[0]["rit"] == "M-1-2026"

    def test_incluye_causa_con_audiencia_futura(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"fecha_audiencia": "2026-09-01"}, ruta)

        activas = causas_para_goteo(hoy=date(2026, 8, 12), ruta=ruta)
        assert len(activas) == 1

    def test_incluye_causa_con_audiencia_reciente_dentro_de_la_ventana(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"fecha_audiencia": "2026-07-01"}, ruta)  # 42 días antes

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 1

    def test_excluye_causa_con_audiencia_muy_antigua(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"fecha_audiencia": "2026-01-01"}, ruta)  # muy pasada

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 0

    def test_incluye_causa_con_acuerdo_pendiente_pago_aunque_audiencia_muy_antigua(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa(
            "M-1-2026",
            {"fecha_audiencia": "2026-01-01", "estado_acuerdo": "pendiente_pago"},
            ruta,
        )  # audiencia muy pasada, pero con acuerdo pendiente de pago

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 1
        assert activas[0]["rit"] == "M-1-2026"

    def test_incluye_causa_con_pago_recibido_pendiente_confirmar_aunque_audiencia_muy_antigua(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa(
            "M-2-2026",
            {"fecha_audiencia": "2026-01-01", "estado_acuerdo": "pago_recibido_pendiente_confirmar"},
            ruta,
        )

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 1
        assert activas[0]["rit"] == "M-2-2026"

    def test_excluye_causa_cerrada_aunque_no_tenga_fecha_audiencia(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"causa_cerrada": True}, ruta)

        activas = causas_para_goteo(hoy=date(2026, 8, 12), ruta=ruta)
        assert len(activas) == 0


class TestRegistrarAviso:
    def test_primer_aviso_crea_entrada_con_un_aviso(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        entrada = registrar_aviso("t1", "acuerdo-daniela", "2026-08-19", rit="O-348-2026", draft_id="d1", ruta=ruta)

        assert entrada["tipo"] == "acuerdo-daniela"
        assert entrada["rit"] == "O-348-2026"
        assert len(entrada["avisos"]) == 1
        assert entrada["avisos"][0] == {"n": 1, "fecha": "2026-08-19", "draft_id": "d1"}

    def test_segundo_aviso_se_acumula_sin_perder_el_primero(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)
        entrada = registrar_aviso("t1", "documentos", "2026-08-21", draft_id="d2", ruta=ruta)

        assert len(entrada["avisos"]) == 2
        assert entrada["avisos"][1] == {"n": 2, "fecha": "2026-08-21", "draft_id": "d2"}

    def test_obtener_seguimiento_de_hilo_inexistente_es_none(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        assert obtener_seguimiento("no-existe", ruta) is None


class TestPuedeInsistir:
    def test_sin_avisos_previos_siempre_puede(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        resultado = puede_insistir("t1", hoy=date(2026, 8, 19), ruta=ruta)
        assert resultado == {"puede": True, "n_aviso": 1, "motivo": "sin avisos previos"}

    def test_segundo_aviso_bloqueado_antes_de_2_dias_habiles(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)  # miércoles

        resultado = puede_insistir("t1", hoy=date(2026, 8, 20), ruta=ruta, ruta_feriados=ruta_feriados)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 2

    def test_segundo_aviso_permitido_a_los_2_dias_habiles(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)  # miércoles

        resultado = puede_insistir("t1", hoy=date(2026, 8, 21), ruta=ruta, ruta_feriados=ruta_feriados)  # viernes: 2 hábiles después
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 2

    def test_tercer_aviso_sin_rit_reporta_causa_no_agendada(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)

        resultado = puede_insistir("t1", hoy=date(2026, 9, 1), ruta=ruta, ruta_feriados=ruta_feriados)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 3
        assert "no tiene audiencia agendada" in resultado["motivo"]

    def test_tercer_aviso_con_rit_pero_sin_fecha_audiencia_reporta_causa_no_agendada(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_causa("O-1-2026", {}, ruta=ruta_causas)
        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)

        resultado = puede_insistir(
            "t1", hoy=date(2026, 9, 1), ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas
        )
        assert resultado["puede"] is False
        assert "no tiene audiencia agendada" in resultado["motivo"]

    def test_tier_lejano_repite_ciclo_4_y_2_dias_habiles_en_bucle(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_causa("O-1-2026", {"fecha_audiencia": "2026-12-01"}, ruta=ruta_causas)
        kwargs = dict(ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas)

        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)  # miércoles
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)  # viernes, 1er->2do: 2 hábiles

        # 3er aviso exige 4 dias habiles desde el 2do (2026-08-21 -> 2026-08-27)
        resultado = puede_insistir("t1", hoy=date(2026, 8, 26), **kwargs)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 3
        resultado = puede_insistir("t1", hoy=date(2026, 8, 27), **kwargs)
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 3
        registrar_aviso("t1", "documentos", "2026-08-27", ruta=ruta)

        # 4to aviso exige 2 dias habiles desde el 3ro (2026-08-27 -> 2026-08-31)
        resultado = puede_insistir("t1", hoy=date(2026, 8, 28), **kwargs)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 4
        resultado = puede_insistir("t1", hoy=date(2026, 8, 31), **kwargs)
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 4
        registrar_aviso("t1", "documentos", "2026-08-31", ruta=ruta)

        # 5to aviso vuelve a exigir 4 dias habiles (confirma el bucle, no solo 2 pasos)
        resultado = puede_insistir("t1", hoy=date(2026, 9, 3), **kwargs)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 5
        resultado = puede_insistir("t1", hoy=date(2026, 9, 4), **kwargs)
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 5

    def test_tier_medio_exige_2_dias_habiles_entre_avisos(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        # A 10 y 9 dias corridos de las fechas "hoy" usadas abajo: tier medio (8-14 dias)
        registrar_causa("O-1-2026", {"fecha_audiencia": "2026-09-03"}, ruta=ruta_causas)
        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)  # viernes
        kwargs = dict(ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas)

        # 3er aviso: solo 1 dia habil desde el 2do (2026-08-21 -> 2026-08-24, lunes);
        # faltan 10 dias corridos para la audiencia (tier medio, exige 2): no alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 24), **kwargs)
        assert resultado["puede"] is False
        assert "tier medio" in resultado["motivo"]

        # 2 dias habiles (2026-08-21 -> 2026-08-25, martes); faltan 9 dias corridos
        # (tier medio sigue): si alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 25), **kwargs)
        assert resultado["puede"] is True
        assert "tier medio" in resultado["motivo"]

    def test_tier_cercano_exige_1_dia_habil_entre_avisos(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        # 2026-08-21 (viernes) + 5 dias corridos = 2026-08-26: tier cercano (<=7 dias)
        registrar_causa("O-1-2026", {"fecha_audiencia": "2026-08-26"}, ruta=ruta_causas)
        registrar_aviso("t1", "documentos", "2026-08-19", rit="O-1-2026", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)  # viernes
        kwargs = dict(ruta=ruta, ruta_feriados=ruta_feriados, ruta_causas=ruta_causas)

        # mismo dia habil que el 2do aviso: no alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 21), **kwargs)
        assert resultado["puede"] is False
        assert "tier cercano" in resultado["motivo"]

        # 1 dia habil despues (lunes 2026-08-24): alcanza
        resultado = puede_insistir("t1", hoy=date(2026, 8, 24), **kwargs)
        assert resultado["puede"] is True
        assert "tier cercano" in resultado["motivo"]


class TestEscrituraConcurrente:
    """El ciclo corre los subagentes `goteo` y `agenda` en paralelo y los
    dos actualizan registro_causas.json (campos distintos, pero el archivo se
    reescribe entero). Sin el lock de registro._lock, la escritura de uno pisa
    la del otro."""

    def test_dos_escrituras_simultaneas_conservan_ambas_causas(self, tmp_path, monkeypatch):
        ruta = tmp_path / "registro_causas.json"

        # Fuerza el entrelazado: sin lock, los dos hilos leen el archivo vacío
        # antes de que ninguno escriba, y el segundo pisa al primero.
        original = registro_mod._guardar

        def guardar_lento(destino, datos):
            time.sleep(0.05)
            original(destino, datos)

        monkeypatch.setattr(registro_mod, "_guardar", guardar_lento)

        listos = threading.Barrier(2)

        def escribir(rit, campo):
            listos.wait()
            registro_mod.registrar_causa(rit, {campo: True}, ruta=ruta)

        hilos = [
            threading.Thread(target=escribir, args=("M-1-2026", "goteo_ultima_revision")),
            threading.Thread(target=escribir, args=("M-2-2026", "minuta_ejecutada")),
        ]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=30)

        registro = registro_mod.cargar_registro_causas(ruta)
        assert set(registro.keys()) == {"M-1-2026", "M-2-2026"}

    def test_lock_huerfano_viejo_no_bloquea_para_siempre(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        lock = tmp_path / "registro_causas.json.lock"
        lock.write_text("", encoding="utf-8")
        # Un proceso que murió sin liberar el lock hace horas.
        viejo = time.time() - (registro_mod.LOCK_EDAD_MAXIMA_SEG + 60)
        os.utime(lock, (viejo, viejo))

        registro_mod.registrar_causa("M-3-2026", {"empresa": "Alvi"}, ruta=ruta)

        assert registro_mod.obtener_causa("M-3-2026", ruta=ruta)["empresa"] == "Alvi"
        assert not lock.exists()

    def test_lock_reciente_de_otro_proceso_hace_expirar_la_espera(self, tmp_path, monkeypatch):
        monkeypatch.setattr(registro_mod, "LOCK_TIMEOUT_SEG", 0.2)
        ruta = tmp_path / "registro_causas.json"
        (tmp_path / "registro_causas.json.lock").write_text("", encoding="utf-8")

        with pytest.raises(TimeoutError):
            registro_mod.registrar_causa("M-4-2026", {"empresa": "Alvi"}, ruta=ruta)

    def test_no_deja_archivos_temporales_ni_lock(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("M-5-2026", {"empresa": "Alvi"}, ruta=ruta)
        assert [f.name for f in tmp_path.iterdir()] == ["registro_causas.json"]


class TestRegistroPedidos:
    def test_registrar_pedido_nuevo_aplica_defaults(self, tmp_path):
        ruta = tmp_path / "registro_pedidos.json"
        entrada = registro_mod.registrar_pedido(
            "t1", {"rit": "M-1-2026", "tipo": "documentos", "fecha_envio": "2026-08-19"}, ruta=ruta
        )
        assert entrada["thread_id"] == "t1"
        assert entrada["estado"] == "esperando"
        assert entrada["items_recibidos"] == []
        assert entrada["primera_vez_registrado"]
        assert entrada["ultima_revision"]

    def test_registrar_pedido_existente_hace_merge_sin_perder_campos(self, tmp_path):
        ruta = tmp_path / "registro_pedidos.json"
        registro_mod.registrar_pedido(
            "t1",
            {"rit": "M-1-2026", "tipo": "documentos", "items_pedidos": ["Contrato", "Finiquito"]},
            ruta=ruta,
        )
        entrada = registro_mod.registrar_pedido(
            "t1", {"items_recibidos": ["Contrato"], "estado": "parcial"}, ruta=ruta
        )
        assert entrada["rit"] == "M-1-2026"
        assert entrada["items_pedidos"] == ["Contrato", "Finiquito"]
        assert entrada["items_recibidos"] == ["Contrato"]
        assert entrada["estado"] == "parcial"

    def test_obtener_pedido_inexistente_es_none(self, tmp_path):
        ruta = tmp_path / "registro_pedidos.json"
        assert registro_mod.obtener_pedido("no-existe", ruta=ruta) is None

    def test_pedidos_abiertos_excluye_completos_y_pendientes_de_envio(self, tmp_path):
        ruta = tmp_path / "registro_pedidos.json"
        ruta_causas = tmp_path / "registro_causas.json"
        registro_mod.registrar_pedido("t1", {"rit": "M-1-2026", "estado": "esperando"}, ruta=ruta)
        registro_mod.registrar_pedido("t2", {"rit": "M-2-2026", "estado": "parcial"}, ruta=ruta)
        registro_mod.registrar_pedido("t3", {"rit": "M-3-2026", "estado": "gestion_manual"}, ruta=ruta)
        registro_mod.registrar_pedido("t4", {"rit": "M-4-2026", "estado": "completo"}, ruta=ruta)
        registro_mod.registrar_pedido("t5", {"rit": "M-5-2026", "estado": "pendiente_envio"}, ruta=ruta)

        abiertos = {p["thread_id"] for p in registro_mod.pedidos_abiertos(ruta=ruta, ruta_causas=ruta_causas)}
        assert abiertos == {"t1", "t2", "t3"}

    def test_pedidos_abiertos_excluye_causa_cerrada(self, tmp_path):
        ruta = tmp_path / "registro_pedidos.json"
        ruta_causas = tmp_path / "registro_causas.json"
        registro_mod.registrar_pedido("t1", {"rit": "M-1-2026", "estado": "esperando"}, ruta=ruta)
        registro_mod.registrar_pedido("t2", {"rit": "M-2-2026", "estado": "esperando"}, ruta=ruta)
        registro_mod.registrar_causa("M-1-2026", {"causa_cerrada": True}, ruta=ruta_causas)

        abiertos = {p["thread_id"] for p in registro_mod.pedidos_abiertos(ruta=ruta, ruta_causas=ruta_causas)}
        assert abiertos == {"t2"}


class TestMigrarPedidosBootstrap:
    def test_siembra_desde_seguimiento_y_borradores(self, tmp_path):
        ruta_pedidos = tmp_path / "registro_pedidos.json"
        ruta_seguimiento = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"

        registro_mod.registrar_aviso("t1", "documentos", "2026-08-19", rit="M-744-2026", ruta=ruta_seguimiento)
        registro_mod.registrar_aviso("t2", "acuerdo-daniela", "2026-08-19", rit="O-348-2026", ruta=ruta_seguimiento)
        registro_mod.registrar_causa(
            "M-556-2026",
            {"borrador_documentos_draft_id": "d1", "thread_id": "t3"},
            ruta=ruta_causas,
        )
        registro_mod.registrar_causa("M-699-2026", {}, ruta=ruta_causas)  # sin borrador, no se siembra

        resultado = registro_mod.migrar_pedidos_bootstrap(
            ruta_pedidos=ruta_pedidos, ruta_seguimiento=ruta_seguimiento, ruta_causas=ruta_causas
        )
        assert len(resultado["creados"]) == 3
        assert resultado["ya_existian"] == []

        pedidos = registro_mod.cargar_registro_pedidos(ruta_pedidos)
        assert pedidos["t1"]["rit"] == "M-744-2026"
        assert pedidos["t1"]["tipo"] == "documentos"
        assert pedidos["t1"]["estado"] == "esperando"
        assert pedidos["t1"]["fecha_envio"] == "2026-08-19"
        assert pedidos["t2"]["tipo"] == "acuerdo"
        assert pedidos["borrador:d1"]["rit"] == "M-556-2026"
        assert pedidos["borrador:d1"]["estado"] == "pendiente_envio"

    def test_correr_dos_veces_no_duplica(self, tmp_path):
        ruta_pedidos = tmp_path / "registro_pedidos.json"
        ruta_seguimiento = tmp_path / "registro_seguimiento.json"
        ruta_causas = tmp_path / "registro_causas.json"
        registro_mod.registrar_aviso("t1", "documentos", "2026-08-19", rit="M-744-2026", ruta=ruta_seguimiento)

        registro_mod.migrar_pedidos_bootstrap(
            ruta_pedidos=ruta_pedidos, ruta_seguimiento=ruta_seguimiento, ruta_causas=ruta_causas
        )
        resultado = registro_mod.migrar_pedidos_bootstrap(
            ruta_pedidos=ruta_pedidos, ruta_seguimiento=ruta_seguimiento, ruta_causas=ruta_causas
        )
        assert resultado["creados"] == []
        assert resultado["ya_existian"] == ["t1"]
        assert len(registro_mod.cargar_registro_pedidos(ruta_pedidos)) == 1
