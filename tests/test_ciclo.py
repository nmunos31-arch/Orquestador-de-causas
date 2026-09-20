import json

import pytest

from gestion_causas import ciclo


class TestCorrerCiclo:
    def test_corre_goteo_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(tmp_path / "no_existe.json")},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }), encoding="utf-8")

        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = ciclo.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["goteo"]["fase"] == "goteo"
        assert resultado["fases"]["goteo"]["titular"] == "Sin causas activas para revisar"

    def test_falla_de_una_fase_no_interrumpe_el_resultado(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-15"}), encoding="utf-8")

        def goteo_falla(contexto_corrida, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(ciclo.fases_goteo, "correr", goteo_falla)
        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = ciclo.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["goteo"]["fase"] == "goteo"
        assert "boom" in resultado["fases"]["goteo"]["error"]

    def test_falla_si_no_existe_el_contexto_de_corrida(self, tmp_path):
        ruta_contexto = tmp_path / "no_existe.json"

        with pytest.raises(FileNotFoundError):
            ciclo.correr(ruta_contexto=ruta_contexto)


class TestCicloDespachaSmu:
    def test_corre_smu_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-16"}), encoding="utf-8")

        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = ciclo.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["smu"]["fase"] == "smu"
        assert resultado["fases"]["smu"]["titular"] == "Sin correos nuevos"

    def test_smu_recibe_ruta_registro_ceco(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-16"}), encoding="utf-8")

        llamadas = []
        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])
        monkeypatch.setattr(ciclo.fases_smu, "correr", lambda *a, **k: llamadas.append(k) or {"fase": "smu"})

        ciclo.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert llamadas[0]["ruta_registro_ceco"] == tmp_path / "registro_ceco.json"


class TestCicloDespachaAgenda:
    def test_corre_agenda_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-17"}), encoding="utf-8")

        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = ciclo.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["agenda"]["fase"] == "agenda"
        assert resultado["fases"]["agenda"]["titular"] == "Sin causas activas para revisar agenda"


class TestResumenComoLista:
    def test_respeta_el_orden_calendario_smu_goteo_agenda_seguimiento(self):
        fases = {
            "smu": {"fase": "smu"},
            "goteo": {"fase": "goteo"},
            "agenda": {"fase": "agenda"},
            "seguimiento": {"fase": "seguimiento"},
            "calendario": {"fase": "calendario"},
        }
        lista = ciclo._resumen_como_lista(fases, es_corrida_manana=True)
        assert [f["fase"] for f in lista] == ["calendario", "smu", "goteo", "agenda", "seguimiento"]

    def test_completa_seguimiento_y_calendario_como_no_aplica_fuera_de_la_manana(self):
        fases = {"smu": {"fase": "smu"}, "goteo": {"fase": "goteo"}, "agenda": {"fase": "agenda"}}
        lista = ciclo._resumen_como_lista(fases, es_corrida_manana=False)
        por_fase = {f["fase"]: f for f in lista}

        assert por_fase["seguimiento"]["resultado"] == "No aplica: solo corre en la corrida de la mañana."
        assert por_fase["seguimiento"]["error"] is None
        assert por_fase["calendario"]["resultado"] == "No aplica: solo corre en la corrida de la mañana."

    def test_una_fase_que_fallo_se_pasa_tal_cual(self):
        fases = {
            "smu": {"fase": "smu"}, "goteo": {"fase": "goteo", "error": "boom"}, "agenda": {"fase": "agenda"},
        }
        lista = ciclo._resumen_como_lista(fases, es_corrida_manana=False)
        assert next(f for f in lista if f["fase"] == "goteo") == {"fase": "goteo", "error": "boom"}


class TestArmarYEnviarPanel:
    def _mockear_camino_feliz(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ciclo.cli_mod, "verificar_borradores_pendientes", lambda: {
            "pendientes": [{"rit": "M-1-2026"}], "enviados": [], "descartados": [],
        })
        monkeypatch.setattr(ciclo.panel_mod, "generar_panel_html", lambda *a, **k: "<html>panel</html>")
        monkeypatch.setattr(ciclo.gmail_personal_client, "construir_servicio", lambda permitir_login: object())
        llamadas_envio = []
        monkeypatch.setattr(
            ciclo.gmail_personal_client, "enviar_panel_estado",
            lambda asunto, html, servicio=None: llamadas_envio.append((asunto, html)) or {"id": "msg-1"},
        )
        monkeypatch.setattr(ciclo.bitacora_mod, "registrar", lambda *a, **k: None)
        return llamadas_envio

    def test_camino_feliz_genera_y_envia_el_panel(self, tmp_path, monkeypatch):
        llamadas_envio = self._mockear_camino_feliz(monkeypatch, tmp_path)

        resultado = ciclo._armar_y_enviar_panel(
            {"smu": {"fase": "smu"}}, "2026-09-18", False, ruta_registro_causas=tmp_path / "registro_causas.json"
        )

        assert resultado["panel_generado"] is True
        assert resultado["correo_enviado"] is True
        assert resultado["error"] is None
        assert resultado["borradores"]["pendientes"] == [{"rit": "M-1-2026"}]
        assert llamadas_envio[0][0] == "Panel de gestión de causas - 2026-09-18"

    def test_pasa_los_pendientes_al_generar_el_panel(self, tmp_path, monkeypatch):
        self._mockear_camino_feliz(monkeypatch, tmp_path)
        llamadas_panel = []
        monkeypatch.setattr(
            ciclo.panel_mod, "generar_panel_html",
            lambda resumen, **k: llamadas_panel.append(k) or "<html></html>",
        )

        ciclo._armar_y_enviar_panel(
            {}, "2026-09-18", False, ruta_registro_causas=tmp_path / "registro_causas.json"
        )

        assert llamadas_panel[0]["borradores_pendientes"] == [{"rit": "M-1-2026"}]

    def test_fallo_al_revisar_borradores_no_bloquea_el_panel(self, tmp_path, monkeypatch):
        llamadas_envio = self._mockear_camino_feliz(monkeypatch, tmp_path)
        monkeypatch.setattr(
            ciclo.cli_mod, "verificar_borradores_pendientes",
            lambda: (_ for _ in ()).throw(RuntimeError("token vencido")),
        )

        resultado = ciclo._armar_y_enviar_panel(
            {}, "2026-09-18", False, ruta_registro_causas=tmp_path / "registro_causas.json"
        )

        assert "token vencido" in resultado["borradores"]["error"]
        assert resultado["panel_generado"] is True
        assert resultado["correo_enviado"] is True
        assert len(llamadas_envio) == 1

    def test_fallo_al_generar_el_panel_no_intenta_enviar_correo(self, tmp_path, monkeypatch):
        llamadas_envio = self._mockear_camino_feliz(monkeypatch, tmp_path)
        monkeypatch.setattr(
            ciclo.panel_mod, "generar_panel_html",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        resultado = ciclo._armar_y_enviar_panel(
            {}, "2026-09-18", False, ruta_registro_causas=tmp_path / "registro_causas.json"
        )

        assert resultado["panel_generado"] is False
        assert resultado["correo_enviado"] is False
        assert "boom" in resultado["error"]
        assert llamadas_envio == []

    def test_token_personal_no_listo_no_bloquea_el_resultado(self, tmp_path, monkeypatch):
        self._mockear_camino_feliz(monkeypatch, tmp_path)
        monkeypatch.setattr(
            ciclo.gmail_personal_client, "construir_servicio",
            lambda permitir_login: (_ for _ in ()).throw(RuntimeError("sin token")),
        )

        resultado = ciclo._armar_y_enviar_panel(
            {}, "2026-09-18", False, ruta_registro_causas=tmp_path / "registro_causas.json"
        )

        assert resultado["panel_generado"] is True
        assert resultado["correo_enviado"] is False
        assert "sin token" in resultado["error"]


class TestCorrerYEnviarPanel:
    def test_corre_las_fases_arma_el_panel_y_borra_el_contexto(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-18", "corrida": "resto"}), encoding="utf-8")
        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])
        monkeypatch.setattr(ciclo.cli_mod, "verificar_borradores_pendientes", lambda: {"pendientes": []})
        monkeypatch.setattr(ciclo.panel_mod, "generar_panel_html", lambda *a, **k: "<html></html>")
        monkeypatch.setattr(ciclo.gmail_personal_client, "construir_servicio", lambda permitir_login: object())
        monkeypatch.setattr(
            ciclo.gmail_personal_client, "enviar_panel_estado", lambda *a, **k: {"id": "msg-1"}
        )

        resultado = ciclo.correr_y_enviar_panel(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["goteo"]["fase"] == "goteo"
        assert resultado["panel"]["correo_enviado"] is True
        assert not ruta_contexto.exists()


class TestAsegurarContexto:
    def test_no_hace_nada_si_el_contexto_ya_existe(self, tmp_path, monkeypatch):
        ruta = tmp_path / "_contexto_corrida.json"
        ruta.write_text(json.dumps({"listo": True, "fecha_hoy": "2026-09-20"}), encoding="utf-8")

        llamadas = []
        monkeypatch.setattr(ciclo.cli_mod, "main", lambda argv: llamadas.append(argv) or 0)

        assert ciclo._asegurar_contexto(ruta) is True
        assert llamadas == []

    def test_arma_el_contexto_si_falta(self, tmp_path, monkeypatch):
        ruta = tmp_path / "_contexto_corrida.json"
        llamadas = []

        def main_falso(argv):
            llamadas.append(argv)
            ruta.write_text(json.dumps({"listo": True}), encoding="utf-8")
            return 0

        monkeypatch.setattr(ciclo.cli_mod, "main", main_falso)

        assert ciclo._asegurar_contexto(ruta) is True
        assert llamadas == [["contexto-corrida", "--salida", str(ruta)]]

    def test_devuelve_false_si_contexto_corrida_sale_con_codigo_1(self, tmp_path, monkeypatch):
        ruta = tmp_path / "_contexto_corrida.json"

        def main_falso(argv):
            ruta.write_text(json.dumps({"listo": False}), encoding="utf-8")
            return 1

        monkeypatch.setattr(ciclo.cli_mod, "main", main_falso)

        assert ciclo._asegurar_contexto(ruta) is False


class TestCicloDespachaSeguimientoYCalendarioSoloEnLaManana:
    def test_no_despacha_seguimiento_ni_calendario_fuera_de_la_manana(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(
            json.dumps({"fecha_hoy": "2026-09-18", "corrida": "resto"}), encoding="utf-8"
        )
        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = ciclo.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert "seguimiento" not in resultado["fases"]
        assert "calendario" not in resultado["fases"]

    def test_despacha_seguimiento_y_calendario_en_la_manana(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(
            json.dumps({"fecha_hoy": "2026-09-21", "corrida": "manana", "es_lunes": True}), encoding="utf-8"
        )
        monkeypatch.setattr(ciclo.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])
        monkeypatch.setattr(ciclo.fases_seguimiento, "correr", lambda *a, **k: {"fase": "seguimiento"})
        monkeypatch.setattr(ciclo.fases_calendario, "correr", lambda *a, **k: {"fase": "calendario"})

        resultado = ciclo.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["seguimiento"]["fase"] == "seguimiento"
        assert resultado["fases"]["calendario"]["fase"] == "calendario"
