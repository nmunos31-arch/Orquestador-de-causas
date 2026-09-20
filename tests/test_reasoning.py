import json
import subprocess
from types import SimpleNamespace

import pytest

from gestion_causas import reasoning
from gestion_causas.reasoning import invocar_skill, preguntar


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
        assert args == [
            "C:\\ruta\\falsa\\claude.CMD", "-p",
            "--disable-slash-commands", "--setting-sources", "",
            "--output-format", "json",
            "--tools", "", "--strict-mcp-config",
        ]
        assert kwargs.get("input") == "un prompt cualquiera"

    def test_lanza_runtimeerror_si_claude_no_esta_en_el_path(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: None)

        with pytest.raises(RuntimeError):
            reasoning_mod._ejecutar_claude("un prompt cualquiera")


class TestEjecutarClaudeErrorIncluyeStdout:
    def test_incluye_stdout_en_el_error_cuando_stderr_esta_vacio(self, monkeypatch):
        """claude -p a veces imprime el motivo del fallo (ej. "Prompt is too
        long") por stdout, no por stderr (confirmado en una corrida real con
        un hilo de correo de ~800KB) — si el error solo mira stderr, el
        mensaje queda vacío y no sirve para diagnosticar nada."""
        from gestion_causas import reasoning as reasoning_mod

        class ResultadoFalso:
            returncode = 1
            stdout = "Prompt is too long\n"
            stderr = ""

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: "C:\\ruta\\falsa\\claude.CMD")
        monkeypatch.setattr(reasoning_mod.subprocess, "run", lambda args, **kwargs: ResultadoFalso())

        with pytest.raises(RuntimeError, match="Prompt is too long"):
            reasoning_mod._ejecutar_claude("un prompt cualquiera")

    def test_prioriza_stderr_cuando_tiene_contenido(self, monkeypatch):
        from gestion_causas import reasoning as reasoning_mod

        class ResultadoFalso:
            returncode = 1
            stdout = "detalle de stdout"
            stderr = "detalle real del error"

        monkeypatch.setattr(reasoning_mod.shutil, "which", lambda nombre: "C:\\ruta\\falsa\\claude.CMD")
        monkeypatch.setattr(reasoning_mod.subprocess, "run", lambda args, **kwargs: ResultadoFalso())

        with pytest.raises(RuntimeError, match="detalle real del error"):
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
            "--disable-slash-commands", "--setting-sources", "",
            "--output-format", "json",
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
        assert "--allowedTools" not in args


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


class TestInvocarSkill:
    def test_devuelve_ok_y_salida_cuando_ejecutar_no_lanza(self, tmp_path):
        llamadas = []

        def ejecutar_falso(prompt, carpeta, *, timeout):
            llamadas.append((prompt, carpeta, timeout))
            return "listo"

        resultado = invocar_skill("/minuta-laboral X", tmp_path, ejecutar=ejecutar_falso)

        assert resultado == {"ok": True, "salida": "listo"}
        assert len(llamadas) == 1
        prompt, carpeta, timeout = llamadas[0]
        assert prompt == "/minuta-laboral X"
        assert carpeta == tmp_path
        from gestion_causas.reasoning import TIMEOUT_SKILL_SEGUNDOS
        assert timeout == TIMEOUT_SKILL_SEGUNDOS

    def test_devuelve_error_sin_lanzar_cuando_ejecutar_falla(self, tmp_path):
        def ejecutar_falso(prompt, carpeta, *, timeout):
            raise RuntimeError("claude -p terminó con código 1: boom")

        resultado = invocar_skill("/minuta-laboral X", tmp_path, ejecutar=ejecutar_falso)

        assert "error" in resultado
        assert "boom" in resultado["error"]

    def test_no_reintenta(self, tmp_path):
        llamadas = []

        def ejecutar_falso(prompt, carpeta, *, timeout):
            llamadas.append(1)
            raise RuntimeError("falla")

        invocar_skill("/minuta-laboral X", tmp_path, ejecutar=ejecutar_falso)

        assert len(llamadas) == 1

    def test_respeta_timeout_explicito(self, tmp_path):
        llamadas = []

        def ejecutar_falso(prompt, carpeta, *, timeout):
            llamadas.append(timeout)
            return "ok"

        invocar_skill("/minuta-laboral X", tmp_path, ejecutar=ejecutar_falso, timeout=42)

        assert llamadas == [42]


class TestEjecutarClaude:
    def _correr_falso(self, salida_stdout, returncode=0):
        def correr(argv, **kwargs):
            self.argv = argv
            return SimpleNamespace(returncode=returncode, stdout=salida_stdout, stderr="")
        return correr

    def test_devuelve_solo_el_texto_de_result(self, monkeypatch, tmp_path):
        envoltorio = json.dumps({
            "type": "result", "is_error": False, "result": '{"ok": true}',
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 100, "output_tokens": 5,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        })
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso(envoltorio))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        assert reasoning._ejecutar_claude("prompt") == '{"ok": true}'
        assert "--output-format" in self.argv
        assert "json" in self.argv

    def test_registra_el_usage_de_la_llamada(self, monkeypatch, tmp_path):
        ruta_uso = tmp_path / "uso.jsonl"
        envoltorio = json.dumps({
            "type": "result", "is_error": False, "result": "{}",
            "total_cost_usd": 0.02,
            "usage": {"input_tokens": 1234, "output_tokens": 7,
                      "cache_creation_input_tokens": 88, "cache_read_input_tokens": 99},
        })
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso(envoltorio))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", ruta_uso)

        reasoning._ejecutar_claude("prompt")

        evento = json.loads(ruta_uso.read_text(encoding="utf-8").strip())
        assert evento["input_tokens"] == 1234
        assert evento["cache_creation_input_tokens"] == 88
        assert evento["cache_read_input_tokens"] == 99
        assert evento["costo_usd"] == 0.02

    def test_stdout_que_no_es_json_se_devuelve_tal_cual(self, monkeypatch, tmp_path):
        """Red de seguridad: si una versión del CLI deja de envolver la
        salida, no se pierde la respuesta — se devuelve el stdout crudo y
        `preguntar` la parsea como siempre."""
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso('{"ok": true}'))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        assert reasoning._ejecutar_claude("prompt") == '{"ok": true}'

    def test_is_error_true_con_exit_code_cero_es_un_fallo(self, monkeypatch, tmp_path):
        envoltorio = json.dumps({
            "type": "result", "subtype": "error_max_turns", "is_error": True,
            "result": "Prompt is too long",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })
        monkeypatch.setattr(reasoning.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(reasoning.subprocess, "run", self._correr_falso(envoltorio))
        monkeypatch.setattr(reasoning.uso_tokens, "RUTA_USO_TOKENS", tmp_path / "uso.jsonl")

        with pytest.raises(RuntimeError, match="Prompt is too long"):
            reasoning._ejecutar_claude("prompt")


class TestEjecutarClaudeSkillResuelveRutaYPermisosAmplios:
    def test_arma_argv_con_allowedtools_read_write_bash_y_add_dir(self, tmp_path, monkeypatch):
        from gestion_causas.reasoning import _ejecutar_claude_skill

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        monkeypatch.setattr("shutil.which", lambda nombre: "/usr/bin/claude")

        capturado = {}

        def run_falso(argv, **kwargs):
            capturado["argv"] = argv
            capturado["kwargs"] = kwargs
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", run_falso)

        salida = _ejecutar_claude_skill("/minuta-laboral X", tmp_path, timeout=60)

        assert salida == "ok"
        argv = capturado["argv"]
        assert argv[0] == "/usr/bin/claude"
        assert "--allowedTools" in argv
        assert argv[argv.index("--allowedTools") + 1] == "Read,Write,Bash"
        assert "--add-dir" in argv
        assert argv[argv.index("--add-dir") + 1] == str(tmp_path)
        assert capturado["kwargs"]["timeout"] == 60

    def test_lanza_runtimeerror_si_exit_code_no_es_cero(self, tmp_path, monkeypatch):
        from gestion_causas.reasoning import _ejecutar_claude_skill

        monkeypatch.setattr("shutil.which", lambda nombre: "/usr/bin/claude")
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **k: subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom"),
        )

        with pytest.raises(RuntimeError, match="boom"):
            _ejecutar_claude_skill("/minuta-laboral X", tmp_path, timeout=60)
