import json
import subprocess

import pytest

from gestion_causas.reasoning import preguntar


SCHEMA_SIMPLE = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


class TestPreguntar:
    def test_devuelve_json_parseado_cuando_la_respuesta_es_valida(self):
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        resultado = preguntar("tarea de prueba", {"dato": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert resultado == {"ok": True}
        assert len(llamadas) == 1
        assert "tarea de prueba" in llamadas[0]
        assert '"dato": 1' in llamadas[0]

    def test_ignora_bloque_de_codigo_markdown(self):
        def ejecutar_falso(prompt):
            return "```json\n" + json.dumps({"ok": True}) + "\n```"

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)
        assert resultado == {"ok": True}

    def test_reintenta_una_vez_si_la_primera_respuesta_no_es_json(self):
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            if len(llamadas) == 1:
                return "esto no es JSON"
            return json.dumps({"ok": True})

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert resultado == {"ok": True}
        assert len(llamadas) == 2
        assert "no era JSON válido" in llamadas[1]

    def test_devuelve_error_si_falla_dos_veces(self):
        def ejecutar_falso(prompt):
            return "esto tampoco es JSON"

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert "error" in resultado
        assert isinstance(resultado["error"], str)

    def test_devuelve_error_en_vez_de_propagar_si_ejecutar_lanza_excepcion(self):
        def ejecutar_falso(prompt):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=120)

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert "error" in resultado
        assert isinstance(resultado["error"], str)


class TestEjecutarClaudeResuelveRutaCompleta:
    def test_usa_shutil_which_para_resolver_el_ejecutable(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        llamadas_which = []
        llamadas_run = []

        def which_falso(nombre):
            llamadas_which.append(nombre)
            return "C:\\ruta\\falsa\\claude.CMD"

        class ResultadoFalso:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def run_falso(args, **kwargs):
            llamadas_run.append((args, kwargs))
            return ResultadoFalso()

        monkeypatch.setattr(reasoning_mod.shutil, "which", which_falso)
        monkeypatch.setattr(reasoning_mod.subprocess, "run", run_falso)

        resultado = reasoning_mod._ejecutar_claude("un prompt cualquiera")

        assert resultado == "ok"
        assert llamadas_which == ["claude"]
        args, kwargs = llamadas_run[0]
        assert args == ["C:\\ruta\\falsa\\claude.CMD", "-p"]
        assert kwargs.get("input") == "un prompt cualquiera"

    def test_lanza_runtimeerror_si_claude_no_esta_en_el_path(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: None)

        with pytest.raises(RuntimeError):
            reasoning_mod._ejecutar_claude("un prompt cualquiera")


class TestEjecutarClaudePasaPromptPorStdin:
    def test_no_pasa_el_prompt_como_argumento_de_linea_de_comandos(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        prompt_largo = "x" * 100_000  # simula un contexto grande (ej. un hilo de correo largo)
        llamadas = []

        class ResultadoFalso:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def which_falso(nombre):
            return "C:\\ruta\\falsa\\claude.CMD"

        def run_falso(args, **kwargs):
            llamadas.append((args, kwargs))
            return ResultadoFalso()

        monkeypatch.setattr(reasoning_mod.shutil, "which", which_falso)
        monkeypatch.setattr(reasoning_mod.subprocess, "run", run_falso)

        reasoning_mod._ejecutar_claude(prompt_largo)

        args, kwargs = llamadas[0]
        assert prompt_largo not in args
        assert kwargs.get("input") == prompt_largo
