# Driver Python — fase `calendario` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar los 3 pasos de `gestion_causas/subagentes/calendario.md` (Fase 0, la red de seguridad semanal que detecta causas con audiencia agendada que nunca se registraron por correo) a un módulo Python puro `gestion_causas/fases/calendario.py` — la última de las 5 fases.

**Architecture:** Barre los eventos de calendario de las 6 empresas de interés vía `calendar_client.eventos_empresas_interes(_desde_cache)` (ya existente), y por cada evento sin causa registrada busca el hilo de origen (mensaje más antiguo de dominio `smu.cl`/`sb.cl`, mismo criterio que `fases/smu.py`), crea la carpeta y guarda la demanda solo para audiencias Única/Preparatoria, y agrega la fila del Excel de Juicios Vigentes reusando `fases/smu.py::agregar_causa`/`RUTA_EXCEL_JUICIOS` (en vez de repetir el `sys.path` hack hacia `actualizar_informe_juicios.py`).

A diferencia de lo que anticipaba el spec general ("probablemente no necesita ningún punto de razonamiento"), el paso 2h (fila del Excel) sí necesita el mismo párrafo "Resumen" narrativo que ya redacta Claude en `smu.py` (`_generar_resumen_narrativo`, plantilla de `docs/2026-07-07-informe-juicios-email-design.md`) — se reusa esa función tal cual en vez de duplicarla o inventar un resumen mecánico. El resto de la fase (detectar tipo de audiencia, decidir si crear carpeta, decidir si aplica Excel) es 100% mecánico con lo que ya expone `calendar_client.py`.

Se extrae `_buscar_ceco_en_mensajes`/`_PATRON_CECO` de `smu.py` (privado) a `cuadro_resumen.py::buscar_ceco_en_mensajes` (público) — lo necesitan tanto `smu` como `calendario` y es exactamente el mismo criterio (best-effort por regex sobre el cuerpo de los mensajes del hilo).

**Bug encontrado de paso, corregido en este plan (no forma parte del alcance original pero bloquea la corrección de `agenda`):** `calendar_client.clasificar_tipo_audiencia` devolvía `"Unica"` (sin tilde) mientras que `fases/agenda.py` compara contra `"Única"` (con tilde) — el ofrecimiento y la minuta nunca se disparaban para una audiencia Única real proveniente del mapa de audiencias real (los tests existentes no lo detectaban porque mockean el mapa directamente con el valor "correcto" en vez de pasar por `clasificar_tipo_audiencia`). Se normaliza a `"Única"` (con tilde, consistente con `agenda.py` y con el texto de los `.md`) y se actualizan los tests que dependían del valor sin tilde.

**Tech Stack:** Python 3, pytest, `gestion_causas.calendar_client`, `gestion_causas.carpetas`, `gestion_causas.gmail_client`, `gestion_causas.registro`, `gestion_causas.cuadro_resumen`, `gestion_causas.fases.smu` (solo para reusar `agregar_causa`/`RUTA_EXCEL_JUICIOS`/`_generar_resumen_narrativo`).

**Spec:** `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md` y `gestion_causas/subagentes/calendario.md` (reglas completas, referencia histórica).

## Global Constraints

- Calendario en modo **SOLO LECTURA** — nunca crea, modifica ni borra eventos (esto ya lo garantiza `calendar_client.py`, que no expone ninguna función de escritura).
- Solo actúa los lunes (`contexto_corrida["es_lunes"]`, o `date.today().weekday() == 0` si se corre suelta sin contexto) — si no es lunes, el único resultado es el mensaje corto de `calendario.md` paso 0a, sin ejecutar nada más.
- RITs que empiezan con "I-" (trámites ante la Inspección del Trabajo) ya quedan excluidos por `calendar_client.filtrar_empresas_interes` — no hay que volver a filtrarlos acá.
- Un evento cuyo `rit_detectado` es `None`, o cuyo tipo de audiencia no se puede determinar (incluye "vence plazo"/"reunión informativa", que `es_evento_no_audiencia` ya distingue de "Ambiguo"), se saltea y se anota en `notas` — nunca se inventa un tipo.
- La carpeta y la demanda solo se crean/guardan para audiencias Única o Preparatoria (Juicio: se registra la causa igual, pero sin carpeta — caso raro para que Nico revise a mano).
- El Excel solo aplica a Rendic Hermanos/Alvi/Super 10/Servicios Logísticos Santiago (`EMPRESAS_SIN_EXCEL`, ya existente) y solo si se encontró el mensaje de origen con campos suficientes (`cuadro_completo`) — nunca se escribe una fila con datos incompletos o inventados.
- No se toca `cli.py`, `panel.py` ni las fases ya migradas (salvo el refactor de `_buscar_ceco_en_mensajes` a `cuadro_resumen.py`, sin cambio de comportamiento, y la corrección de tilde en `clasificar_tipo_audiencia`).

## Tasks

### 1. Corrección de tilde (bloqueante para el resto)

- [x] `calendar_client.clasificar_tipo_audiencia` devuelve `"Única"` (con tilde) en vez de `"Unica"`.
- [x] Tests actualizados: `tests/test_calendar_client.py` (`TestClasificarTipoAudiencia`, `TestMapaAudienciasPorRit`) y `tests/test_cli.py::TestMapaAudiencias`.

### 2. `cuadro_resumen.buscar_ceco_en_mensajes` (refactor, sin cambio de comportamiento)

- [x] Mover `smu._PATRON_CECO`/`smu._buscar_ceco_en_mensajes` a `cuadro_resumen.py` como símbolos públicos.
- [x] `smu.py` importa `buscar_ceco_en_mensajes as _buscar_ceco_en_mensajes` (mantiene su API interna intacta para no romper `tests/fases/test_smu.py`).
- [x] Tests movidos a `tests/test_cuadro_resumen.py` (corren siempre; `test_smu.py` no se puede importar en este entorno por la dependencia externa `actualizar_informe_juicios`).

### 3. `fases/calendario.py`

- [ ] `correr(contexto_corrida, *, ruta_registro_causas=...) -> dict`.
- [ ] Autoevaluación de turno (paso 0a): si no es lunes, devuelve
  `{"fase": "calendario", "resultado": "No corresponde hoy (Fase 0 solo corre los lunes).", "error": None}`
  tal cual, sin ejecutar nada más.
- [ ] Paso 1: `_eventos_candidatos(contexto_corrida)` — usa `cache_calendario.ruta` del contexto con
  `eventos_empresas_interes_desde_cache`; si no hay contexto/cache o la llamada falla por cualquier
  motivo, cae a `eventos_empresas_interes` en vivo (mismo criterio que el resto de las fases con
  `--desde-cache`).
- [ ] Paso 2 (`_procesar_evento`): descarta eventos sin RIT o cuyo tipo no es una audiencia real
  (`es_evento_no_audiencia` o `clasificar_tipo_audiencia` devuelve "Ambiguo"); si ya está registrada,
  no hace nada; busca el mensaje de origen (`_buscar_mensaje_origen`, dominio `smu.cl`/`sb.cl`, el más
  antiguo); registra la causa con lo que se pueda extraer (`cuadro_resumen.extraer_campos_cuadro`,
  `buscar_ceco_en_mensajes`); crea carpeta + guarda demanda solo si Única/Preparatoria; etiqueta el
  hilo si se encontró; agrega la fila del Excel si aplica y hay datos suficientes; anota en bitácora.
- [ ] Paso 3: resumen final con el formato exacto de `calendario.md` paso 3.

### 4. Tests

- [ ] `tests/fases/test_calendario.py`: autoevaluación de turno (lunes/no lunes), fallback de cache a
  API en vivo, clasificación de eventos (sin RIT, no-audiencia, ambiguo, ya registrada), carpeta +
  demanda solo para Única/Preparatoria (no para Juicio), Excel solo cuando aplica y hay datos
  suficientes (y no se rompe si `agregar_causa` lanza `PermissionError`), `correr()` de punta a punta
  con mocks de `calendar_client`/`gmail_client`/`registro_mod`/`_generar_resumen_narrativo`.

### 5. Documentación

- [ ] `README.md`: fila de `calendario` a "✅ migrada" — completa las 5 fases.
- [ ] `orquestador.py`: agrega `calendario` al loop, junto con la corrección de que `calendario` y
  `seguimiento` solo deben despacharse en la corrida de la mañana (`contexto_corrida["corrida"] ==
  "manana"`, campo que YA existe en el contexto real armado por `cli.cmd_contexto_corrida` — la nota
  anterior en `orquestador.py` decía, por error, que este campo no existía todavía).
