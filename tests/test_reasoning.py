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


class TestEjecutarClaudeUsaUtf8:
    def test_pasa_encoding_utf8_a_subprocess_run(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        llamadas = []

        class ResultadoFalso:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def which_falso(nombre):
            return "C:\\ruta\\falsa\\claude.CMD"

        def run_falso(args, **kwargs):
            llamadas.append(kwargs)
            return ResultadoFalso()

        monkeypatch.setattr(reasoning_mod.shutil, "which", which_falso)
        monkeypatch.setattr(reasoning_mod.subprocess, "run", run_falso)

        reasoning_mod._ejecutar_claude("prompt con acentos: ñ, á, é, y una flecha →")

        assert llamadas[0].get("encoding") == "utf-8"


class TestEjecutarClaudeConRutaArchivo:
    def test_agrega_allowedtools_read_y_add_dir_de_la_carpeta_del_archivo(self, monkeypatch, tmp_path):
        from gestion_causas import reasoning as reasoning_mod

        carpeta = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        carpeta.mkdir(parents=True)
        ruta_demanda = carpeta / "demanda.pdf"

        llamadas = []

        class ResultadoFalso:
            returncode = 0
            stdout = "ok"
            stderr = ""

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: "C:\\ruta\\falsa\\claude.CMD")
        monkeypatch.setattr(reasoning_mod.subprocess, "run", lambda args, **kwargs: llamadas.append((args, kwargs)) or ResultadoFalso())

        reasoning_mod._ejecutar_claude("un prompt", ruta_archivo=ruta_demanda)

        args, kwargs = llamadas[0]
        settings_esperados = json.dumps({"permissions": {"deny": ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]}})
        assert args == [
            "C:\\ruta\\falsa\\claude.CMD", "-p",
            "--allowedTools", "Read",
            "--add-dir", str(carpeta),
            "--settings", settings_esperados,
            "--strict-mcp-config",
        ]
        assert kwargs.get("input") == "un prompt"

    def test_sin_ruta_archivo_no_agrega_allowedtools(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        llamadas = []

        class ResultadoFalso:
            returncode = 0
            stdout = "ok"
            stderr = ""

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: "C:\\ruta\\falsa\\claude.CMD")
        monkeypatch.setattr(reasoning_mod.subprocess, "run", lambda args, **kwargs: llamadas.append((args, kwargs)) or ResultadoFalso())

        reasoning_mod._ejecutar_claude("un prompt")

        args, kwargs = llamadas[0]
        assert args == ["C:\\ruta\\falsa\\claude.CMD", "-p"]


class TestPreguntarConRutaArchivo:
    def test_pasa_ruta_archivo_a_ejecutar_y_lo_menciona_en_el_prompt(self, tmp_path):
        from gestion_causas.reasoning import preguntar

        ruta_demanda = tmp_path / "demanda.pdf"
        llamadas = []

        def ejecutar_falso(prompt, ruta_archivo=None):
            llamadas.append((prompt, ruta_archivo))
            return json.dumps({"ok": True})

        resultado = preguntar(
            "tarea de prueba", {"dato": 1}, SCHEMA_SIMPLE,
            ejecutar=ejecutar_falso, ruta_archivo=ruta_demanda,
        )

        assert resultado == {"ok": True}
        prompt, ruta_recibida = llamadas[0]
        assert ruta_recibida == ruta_demanda
        assert str(ruta_demanda) in prompt

    def test_sin_ruta_archivo_ejecutar_se_llama_solo_con_el_prompt(self):
        from gestion_causas.reasoning import preguntar

        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert len(llamadas) == 1


class TestTimeoutSubidoA180:
    def test_timeout_segundos_es_180(self):
        from gestion_causas.reasoning import TIMEOUT_SEGUNDOS
        assert TIMEOUT_SEGUNDOS == 180
