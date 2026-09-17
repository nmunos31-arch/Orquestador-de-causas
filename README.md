# Orquestador de causas

Driver Python del proyecto "Gestión automática de causas nuevas desde la casilla del
trabajo" — migración del flujo original de subagentes de Claude Code (que sigue viviendo
en el repo `Scripts-varios`, carpeta `Actualizador de informes/gestion_causas/subagentes/`)
a un driver Python puro que invoca Claude solo para los pasos que de verdad requieren
razonamiento sobre texto libre.

Ver `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md` para el
diseño completo, y `docs/superpowers/plans/` para el historial de planes de implementación.

## Estado de la migración

| Fase | Estado |
|---|---|
| `goteo` | ✅ migrada, validada en vivo |
| `smu` | ✅ migrada (ingesta + borrador de documentos), validada en vivo |
| `agenda` | ✅ migrada (Plan A: borrador de ofrecimiento; Plan B: invocación de `/minuta-laboral`) |
| `seguimiento` | ✅ migrada |
| `calendario` | ⏳ pendiente |

La tarea programada real (`gestion-causas-orquestador`) todavía corre el flujo viejo de
subagentes — el corte a este driver es una decisión pendiente, una vez migradas las 5 fases.

## Setup

```bash
pip install -r requirements.txt
```

Requiere Python 3.11+.

### Credenciales y estado en tiempo de ejecución (no van en git)

`gestion_causas/.gitignore` ya excluye lo siguiente — hay que provisionarlo a mano en
cada máquina donde corra esto:

- `token_gmail_trabajo.json`, `token_calendar_trabajo.json`, `token_gmail_personal.json`
  — tokens OAuth de Gmail/Calendar.
- `registro_causas.json`, `registro_ceco.json`, `registro_seguimiento.json`,
  `registro_pedidos.json`, `bitacora.md` — estado real de causas/clientes.

### Dependencia con `actualizar_informe_juicios.py` (repo `Scripts-varios`)

La fase `smu` escribe filas en el Excel "Informe de Juicios Vigentes" reusando
`agregar_causa`/`RUTA_EXCEL_JUICIOS` de `actualizar_informe_juicios.py`, que vive en el
otro repo (`Scripts-varios/Actualizador de informes/`). `gestion_causas/fases/smu.py`
agrega esa carpeta a `sys.path` en vez de duplicar la lógica de escritura de Excel —
por defecto asume la ruta de siempre en esta máquina; en otra máquina, seteá:

```bash
export RUTA_ACTUALIZADOR_INFORMES="/ruta/a/Scripts-varios/Actualizador de informes"
```

## Tests

```bash
pytest -q
```
