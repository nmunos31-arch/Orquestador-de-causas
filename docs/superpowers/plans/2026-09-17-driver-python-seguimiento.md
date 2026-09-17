# Driver Python — fase `seguimiento` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar los 5 pasos de `gestion_causas/subagentes/seguimiento.md` a un módulo Python puro `gestion_causas/fases/seguimiento.py`, siguiendo el mismo patrón ya validado en `fases/goteo.py`, `fases/smu.py` y `fases/agenda.py`.

**Architecture:** Toda la mecánica (alta de pedidos nuevos, pedidos abiertos, cadencia, umbrales de días hábiles/horas, cierre/registro de pedidos) ya existe como funciones puras en `registro.py` (`migrar_pedidos_bootstrap`, `pedidos_abiertos`, `registrar_pedido`, `puede_insistir`, `registrar_aviso`) y `seguimiento.py` (`analizar_hilo`, `parece_cierre_sin_pedido`, `destinatarios_de_ultimo_propio`, `extraer_direccion`) — el CLI (`cli.py`) ya las expone como subcomandos, así que `fases/seguimiento.py` llama a estas funciones directamente, sin pasar por `cli.py` ni subprocess, mismo criterio que las demás fases migradas.

Un solo punto queda con Claude: **clasificar un pedido con mensajes posteriores reales** (ya descartados los acuses de recibo por `parece_cierre_sin_pedido`) — decidir si esos mensajes responden completa o parcialmente lo pedido (comparando contra `items_pedidos` para `tipo: documentos`), o si son solo informativos y no cuentan como respuesta real (memoria `gestion_causas_seguimiento_no_insistir_solo_informativo`). Comparar texto libre de un adjunto/mensaje contra una lista de ítems pedidos en español natural no es mecanizable con regex de forma confiable — es el mismo tipo de juicio que ya usa `smu.py`/`agenda.py` para leer una demanda. Se agrega `reasoning.py::preguntar(...)` (ya existente, sin cambios) con un schema nuevo.

Se extrae `_leer_mapa_hilos` de `goteo.py` (privado, duplicaba exactamente lo que necesita `seguimiento.py` paso 3b) a `mapas.py::leer_mapa_hilos` — mismo criterio que `leer_mapa_audiencias`, para que `goteo` y `seguimiento` nunca diverjan en cómo leen el barrido combinado de Gmail.

**Tech Stack:** Python 3, pytest, `gestion_causas.reasoning`, `gestion_causas.gmail_client`, `gestion_causas.registro`, `gestion_causas.seguimiento` (ya existentes).

**Spec:** `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md` y `gestion_causas/subagentes/seguimiento.md` (reglas completas, referencia histórica).

## Global Constraints

- Nunca se envían correos ni se borra nada: solo `crear_borrador` (con de-dupe por hilo/asunto, mismo criterio que `cli.cmd_crear_borrador`).
- El bootstrap (`migrar_pedidos_bootstrap`) es idempotente — se llama sin condición al empezar `correr()`, en vez de intentar detectar "primera corrida" (mismo criterio que sugiere el propio docstring: "se puede correr más de una vez sin duplicar").
- Los borradores de documentos todavía sin enviar (paso 1a, `pendientes`) NO van en `acciones` de este resumen — el orquestador ya los junta por su cuenta (ver `registro.causas_con_borrador_pendiente`, usado en otro paso del orquestador).
- `puede-insistir` reportando "no tiene audiencia agendada" es lo más importante del resumen: va en `acciones` con urgencia alta, y el pedido pasa a `gestion_manual`.
- No se toca `cli.py`, `panel.py` ni las fases ya migradas (salvo el refactor puntual de `_leer_mapa_hilos` a `mapas.py`, que no cambia comportamiento).

## Tasks

### 1. `mapas.leer_mapa_hilos` (refactor, sin cambio de comportamiento)

- [x] Mover `goteo._leer_mapa_hilos` a `mapas.py::leer_mapa_hilos(contexto_corrida)`.
- [x] `goteo.py` usa `mapas_mod.leer_mapa_hilos(...)` en vez de la función privada.
- [x] Tests existentes de `goteo` y `mapas` siguen pasando sin cambios.

### 2. `reasoning` — clasificar pedido con mensajes posteriores reales

- [ ] Schema `SCHEMA_CLASIFICAR_PEDIDO` en `fases/seguimiento.py`: `estado` (enum
  `completo`/`parcial`/`sin_respuesta_real`), `items_recibidos` (lista de strings, solo
  relevante para `tipo: documentos`), `motivo` (string).
- [ ] `_clasificar_pedido(pedido, mensajes_posteriores_reales) -> dict`: arma un contexto
  acotado (tipo, items_pedidos si aplica, y de cada mensaje posterior: remitente, asunto,
  cuerpo_texto, nombres de adjuntos — nunca el hilo completo) y llama a
  `reasoning.preguntar`. Solo se invoca cuando hay al menos un mensaje posterior que no sea
  un acuse de recibo (si no hay ninguno, es 100% mecánico: mirar el umbral de días/horas).

### 3. `fases/seguimiento.py`

- [ ] `correr(contexto_corrida, *, ruta_registro_pedidos=..., ruta_registro_causas=...,
  ruta_registro_seguimiento=...) -> dict`.
- [ ] Paso 1a: `_verificar_borradores_pendientes` (mismo criterio que
  `cli.cmd_verificar_borradores_pendientes`, pero llamando a `registro_mod`/`gmail_client`
  directo).
- [ ] Paso 1b: `_pedidos_desde_etiqueta` (mismo criterio que `cli.cmd_pedidos_desde_etiqueta`).
- [ ] Paso 2: `registro_mod.pedidos_abiertos(...)`.
- [ ] Paso 3 (`_procesar_pedido`): trae el hilo original + cruce por RIT vía
  `mapas_mod.leer_mapa_hilos`, descarta acuses de recibo, clasifica (mecánico si no hay
  mensajes posteriores reales; `_clasificar_pedido` si los hay), aplica cadencia
  (`registro_mod.puede_insistir`), arma destinatarios, crea el borrador (texto A/B según
  corresponda), registra el aviso y actualiza el pedido (`completo`/`parcial`/
  `gestion_manual`/sin cambios).
- [ ] Paso 4: `registro_mod.migrar_pedidos_bootstrap(...)` sin condición, al principio de
  `correr()`.
- [ ] Paso 5: resumen final con el formato exacto de seguimiento.md paso 5.

### 4. Tests

- [ ] `tests/fases/test_seguimiento.py`: casos por rama de `_procesar_pedido` (completo,
  parcial con recordatorio, insistencia por `documentos` y por `acuerdo`, cadencia que
  bloquea, "no tiene audiencia agendada" → `gestion_manual` + acción urgente, mensaje
  posterior solo informativo → no insiste), de-dupe de borrador, y `correr()` de punta a
  punta con mocks de `gmail_client`/`reasoning.preguntar`/`registro_mod`.

### 5. Documentación

- [ ] `README.md`: fila de `seguimiento` a "✅ migrada".
- [ ] `orquestador.py`: agregar `seguimiento` al loop de fases despachadas.
