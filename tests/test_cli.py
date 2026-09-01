"""Smoke tests del CLI de gestion_causas: que el parser esté bien armado y
que los subcomandos que no requieren red (dry-run, bitácora, carpetas,
registro) funcionen de punta a punta."""

import html
import json

from gestion_causas import calendar_client, gmail_client, gmail_personal_client
from gestion_causas.cli import _cuerpo_con_lista, _texto_a_lista_html, _texto_plano_a_html, construir_parser, main


class TestParser:
    def test_ayuda_no_falla(self):
        parser = construir_parser()
        assert parser is not None

    def test_todos_los_subcomandos_esperados_existen(self):
        parser = construir_parser()
        accion_sub = [a for a in parser._actions if a.dest == "comando"][0]
        esperados = {
            "diagnostico", "buscar-hilos", "leer-hilo", "guardar-adjunto",
            "etiquetar-empresa", "marcar-procesado", "crear-carpeta",
            "registrar-causa", "causa-ya-registrada", "bitacora", "crear-borrador",
            "buscar-eerr-reusable", "registrar-eerr", "copiar-archivo",
            "listar-carpeta", "causas-activas", "dias-habiles-antes",
            "dias-corridos-antes", "obtener-causa", "parece-eerr",
            "buscar-audiencia-por-rit", "diagnostico-calendario", "eventos-calendario",
            "cache-eventos-calendario",
            "verificar-borradores-pendientes",
            "hilos-sin-respuesta", "puede-insistir", "registrar-aviso", "dias-habiles-entre",
            "panel-html", "enviar-panel", "diagnostico-personal",
            "contexto-corrida",
        }
        assert esperados.issubset(set(accion_sub.choices.keys()))


class TestSubcomandosSinRed:
    def test_crear_carpeta_dry_run_no_escribe_en_disco(self, capsys):
        # dry-run: no debe tocar la carpeta real de Minutas durante los tests.
        codigo = main(["--dry-run", "crear-carpeta", "--apellido", "Soto", "--empresa", "Alvi", "--rit", "M-1-2026"])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True

    def test_registrar_causa_dry_run_no_escribe_en_disco(self, tmp_path, capsys):
        # dry-run: no debe tocar el registro real durante los tests.
        datos_json = tmp_path / "datos.json"
        datos_json.write_text(json.dumps({"empresa": "Alvi"}), encoding="utf-8")

        codigo = main(["--dry-run", "registrar-causa", "--rit", "M-1-2026", "--datos-json", str(datos_json)])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True

    def test_bitacora_dry_run_no_escribe_en_disco(self, capsys):
        codigo = main(["--dry-run", "bitacora", "--mensaje", "prueba de bitácora"])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True

    def test_cache_eventos_calendario_dry_run_no_llama_a_la_api(self, capsys):
        codigo = main(["--dry-run", "cache-eventos-calendario"])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True

    def test_buscar_audiencia_por_rit_desde_cache_no_llama_a_la_api(self, tmp_path, capsys):
        ruta = tmp_path / "cache.json"
        ruta.write_text(json.dumps({
            "generado_en": "2026-08-28T09:00:00",
            "eventos": [{"fecha": "2026-08-21", "resumen": "Audiencia Unica M-643-2026 Iturriaga"}],
        }), encoding="utf-8")

        codigo = main(["buscar-audiencia-por-rit", "--rit", "M-643-2026", "--desde-cache", str(ruta)])

        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["total"] == 1
        assert salida["eventos"][0]["fecha"] == "2026-08-21"

    def test_comando_desconocido_falla_argparse(self):
        import pytest

        with pytest.raises(SystemExit):
            main(["no-existe"])

    def test_crear_borrador_dry_run_acepta_flag_lista(self, capsys):
        codigo = main([
            "--dry-run", "crear-borrador",
            "--destinatario", "prueba@sb.cl", "--asunto", "Re: prueba",
            "--cuerpo-archivo", "no-se-lee-en-dry-run.txt", "--lista",
        ])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True

    def test_crear_borrador_dry_run_acepta_cc_y_lista_archivo(self, capsys):
        codigo = main([
            "--dry-run", "crear-borrador",
            "--destinatario", "prueba@sb.cl", "--asunto", "Re: prueba",
            "--cuerpo-archivo", "no-se-lee-en-dry-run.txt",
            "--cc", "otro@sb.cl", "--lista-archivo", "no-se-lee.txt",
        ])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True
        assert salida["cc"] == "otro@sb.cl"

    def test_registrar_aviso_dry_run_no_escribe_en_disco(self, capsys):
        codigo = main(["--dry-run", "registrar-aviso", "--thread-id", "t1", "--tipo", "documentos"])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True

    def test_dias_habiles_entre(self, capsys):
        # Caso real O-348-2026: 4 días hábiles entre el pedido y la insistencia.
        codigo = main(["dias-habiles-entre", "--desde", "2026-07-28", "--hasta", "2026-08-03"])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["dias_habiles"] == 4

    def test_puede_insistir_sin_avisos_previos(self, capsys):
        # thread_id inventado y único: no puede tener avisos previos en el
        # registro real (operación de solo lectura, no escribe nada).
        codigo = main(["puede-insistir", "--thread-id", "t-test-cli-inexistente-xyz", "--hoy", "2026-08-19"])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["puede"] is True
        assert salida["n_aviso"] == 1


class TestTextoAListaHtml:
    def test_quita_numeracion_manual_y_arma_ol(self):
        texto = "1. Contrato de trabajo\n2. Finiquito\n3. Testigos\n"
        assert _texto_a_lista_html(texto) == (
            "<ol><li>Contrato de trabajo</li><li>Finiquito</li><li>Testigos</li></ol>"
        )

    def test_funciona_sin_numeracion_previa(self):
        texto = "Contrato de trabajo\nFiniquito"
        assert _texto_a_lista_html(texto) == "<ol><li>Contrato de trabajo</li><li>Finiquito</li></ol>"

    def test_ignora_lineas_vacias(self):
        texto = "1. Contrato\n\n2. Finiquito\n\n"
        assert _texto_a_lista_html(texto) == "<ol><li>Contrato</li><li>Finiquito</li></ol>"

    def test_escapa_html_para_evitar_inyeccion(self):
        texto = "1. Antecedentes de <script>alert(1)</script> & otros"
        assert "<script>" not in _texto_a_lista_html(texto)
        assert "&amp;" in _texto_a_lista_html(texto)


class TestTextoPlanoAHtml:
    def test_preserva_una_linea_larga_sin_partirla(self):
        """Regresión: Gmail reflowea texto plano largo que llega crudo por la
        API drafts().create() (confirmado en la práctica, agosto 2026) — al
        mandarlo como HTML con <br> explícitos, ese reflow del lado del
        servidor ya no puede alterar la estructura de párrafos."""
        linea = "Si ves este mensaje junto con el mensaje 1 en la misma conversacion, el encadenado funciona."
        assert _texto_plano_a_html(linea) == html.escape(linea)

    def test_convierte_saltos_de_linea_reales_en_br(self):
        texto = "Estimada Daniela:\n\nJunto con saludar, ruego tener presente el correo anterior.\n\nAtentamente,"
        resultado = _texto_plano_a_html(texto)
        assert resultado == (
            "Estimada Daniela:<br><br>"
            "Junto con saludar, ruego tener presente el correo anterior.<br><br>"
            "Atentamente,"
        )

    def test_escapa_html(self):
        texto = "Antecedentes de <script>alert(1)</script> & otros"
        resultado = _texto_plano_a_html(texto)
        assert "<script>" not in resultado
        assert "&amp;" in resultado


class TestCuerpoConLista:
    def test_reemplaza_marcador_por_lista_conservando_saludo_y_despedida(self):
        cuerpo = "Estimada Daniela:\n\nJunto con saludar, ruego tener presente lo siguiente:\n\n[[LISTA]]\n\nAtentamente,"
        resultado = _cuerpo_con_lista(cuerpo, "Contrato de trabajo\nFiniquito")
        assert resultado.startswith("Estimada Daniela:")
        assert "<ol><li>Contrato de trabajo</li><li>Finiquito</li></ol>" in resultado
        assert resultado.endswith("Atentamente,")

    def test_falla_si_no_hay_marcador(self):
        import pytest

        with pytest.raises(ValueError):
            _cuerpo_con_lista("Sin marcador aquí", "item 1")

    def test_falla_si_hay_mas_de_un_marcador(self):
        import pytest

        with pytest.raises(ValueError):
            _cuerpo_con_lista("[[LISTA]] y otra vez [[LISTA]]", "item 1")

    def test_escapa_html_del_texto_alrededor_de_la_lista(self):
        cuerpo = "Hola & <b>:\n\n[[LISTA]]\n\nFin"
        resultado = _cuerpo_con_lista(cuerpo, "item")
        assert "&amp;" in resultado
        assert "<b>" not in resultado.split("<ol>")[0]


class TestPanel:
    def test_panel_html_escribe_archivo(self, tmp_path, capsys):
        resumen_json = tmp_path / "resumen.json"
        resumen_json.write_text(
            json.dumps([{"fase": "smu", "resultado": "sin novedades", "error": None}]),
            encoding="utf-8",
        )
        salida_html = tmp_path / "panel.html"
        registro_vacio = tmp_path / "registro_causas.json"
        registro_vacio.write_text("{}", encoding="utf-8")

        codigo = main([
            "panel-html",
            "--resumen-json", str(resumen_json),
            "--salida", str(salida_html),
            "--hoy", "2026-08-27",
            "--ruta-registro", str(registro_vacio),
        ])

        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["escrito"] is True
        assert salida_html.exists()
        assert "sin novedades" in salida_html.read_text(encoding="utf-8")

    def test_panel_html_dry_run_no_escribe_en_disco(self, tmp_path, capsys):
        resumen_json = tmp_path / "resumen.json"
        resumen_json.write_text(
            json.dumps([{"fase": "smu", "resultado": "sin novedades", "error": None}]),
            encoding="utf-8",
        )
        salida_html = tmp_path / "panel.html"

        codigo = main([
            "--dry-run", "panel-html",
            "--resumen-json", str(resumen_json),
            "--salida", str(salida_html),
            "--hoy", "2026-08-27",
        ])

        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True
        assert not salida_html.exists()

    def test_enviar_panel_dry_run_no_envia(self, tmp_path, capsys):
        html_file = tmp_path / "panel.html"
        html_file.write_text("<html>contenido</html>", encoding="utf-8")

        codigo = main([
            "--dry-run", "enviar-panel",
            "--html-file", str(html_file),
            "--asunto", "Panel de prueba",
        ])
        assert codigo == 0
        salida = json.loads(capsys.readouterr().out)
        assert salida["simulado"] is True


class TestContextoCorrida:
    """Paso 0 del orquestador: resuelve una sola vez lo que las 4 fases
    comparten (fecha, tokens, cache de calendario). Sin red: los tres
    diagnósticos y el cache se simulan."""

    def _preparar(self, monkeypatch, *, gmail=True, calendar=True, personal=True):
        def diagnostico(email):
            def _fn(permitir_login=True, **_):
                return {"email": email, "scopes": []}
            return _fn

        def caido(permitir_login=True, **_):
            raise RuntimeError("token vencido; requiere login interactivo")

        monkeypatch.setattr(
            gmail_client, "diagnostico",
            diagnostico("nmunoz@gomezyriesco.cl") if gmail else caido)
        monkeypatch.setattr(
            calendar_client, "diagnostico",
            diagnostico("nmunoz@gomezyriesco.cl") if calendar else caido)
        monkeypatch.setattr(
            gmail_personal_client, "diagnostico",
            diagnostico("nmunos31@gmail.com") if personal else caido)
        monkeypatch.setattr(
            calendar_client, "guardar_cache_eventos",
            lambda ruta, dias_adelante: {
                "total": 12, "ruta": str(ruta),
                "desde": "2026-09-01", "hasta": "2027-03-20",
            })

    def test_con_todo_ok_escribe_el_contexto_y_sale_cero(self, tmp_path, monkeypatch, capsys):
        self._preparar(monkeypatch)
        salida = tmp_path / "_contexto_corrida.json"

        codigo = main(["contexto-corrida", "--salida", str(salida),
                       "--ruta-cache", str(tmp_path / "cache.json")])

        assert codigo == 0
        contexto = json.loads(salida.read_text(encoding="utf-8"))
        assert contexto["listo"] is True
        assert contexto["fecha_hoy"] and contexto["dia_semana"]
        assert contexto["es_lunes"] == (contexto["dia_semana"] == "lunes")
        assert all(contexto["tokens"][t]["ok"] for t in ("gmail_trabajo", "calendar", "personal"))
        assert contexto["cache_calendario"]["total"] == 12
        # También lo imprime a stdout, para que el orquestador no tenga que leer el archivo.
        assert json.loads(capsys.readouterr().out)["listo"] is True

    def test_calendar_caido_sale_uno_y_no_deja_cache(self, tmp_path, monkeypatch, capsys):
        self._preparar(monkeypatch, calendar=False)
        salida = tmp_path / "_contexto_corrida.json"

        codigo = main(["contexto-corrida", "--salida", str(salida),
                       "--ruta-cache", str(tmp_path / "cache.json")])

        assert codigo == 1
        contexto = json.loads(salida.read_text(encoding="utf-8"))
        assert contexto["listo"] is False
        assert contexto["cache_calendario"] is None
        assert "login interactivo" in contexto["tokens"]["calendar"]["error"]
        capsys.readouterr()

    def test_solo_el_token_personal_caido_no_aborta_la_corrida(self, tmp_path, monkeypatch, capsys):
        # El token personal solo se usa para enviar el panel al final; que falte
        # no es motivo para no correr las 4 fases.
        self._preparar(monkeypatch, personal=False)
        salida = tmp_path / "_contexto_corrida.json"

        codigo = main(["contexto-corrida", "--salida", str(salida),
                       "--ruta-cache", str(tmp_path / "cache.json")])

        assert codigo == 0
        contexto = json.loads(salida.read_text(encoding="utf-8"))
        assert contexto["listo"] is True
        assert contexto["tokens"]["personal"]["ok"] is False
        capsys.readouterr()

    def test_token_atado_a_la_cuenta_equivocada_no_esta_ok(self, tmp_path, monkeypatch, capsys):
        self._preparar(monkeypatch)
        monkeypatch.setattr(
            gmail_client, "diagnostico",
            lambda permitir_login=True, **_: {"email": "otra@cuenta.cl", "scopes": []})
        salida = tmp_path / "_contexto_corrida.json"

        codigo = main(["contexto-corrida", "--salida", str(salida),
                       "--ruta-cache", str(tmp_path / "cache.json")])

        assert codigo == 1
        contexto = json.loads(salida.read_text(encoding="utf-8"))
        assert contexto["tokens"]["gmail_trabajo"]["ok"] is False
        assert "otra@cuenta.cl" in contexto["tokens"]["gmail_trabajo"]["error"]
        capsys.readouterr()

    def test_dry_run_no_escribe_nada(self, tmp_path, capsys):
        salida = tmp_path / "_contexto_corrida.json"
        codigo = main(["--dry-run", "contexto-corrida", "--salida", str(salida)])
        assert codigo == 0
        assert not salida.exists()
        assert json.loads(capsys.readouterr().out)["simulado"] is True
