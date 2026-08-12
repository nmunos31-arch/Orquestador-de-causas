"""Smoke tests del CLI de gestion_causas: que el parser esté bien armado y
que los subcomandos que no requieren red (dry-run, bitácora, carpetas,
registro) funcionen de punta a punta."""

import json

from gestion_causas.cli import construir_parser, main


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

    def test_comando_desconocido_falla_argparse(self):
        import pytest

        with pytest.raises(SystemExit):
            main(["no-existe"])
