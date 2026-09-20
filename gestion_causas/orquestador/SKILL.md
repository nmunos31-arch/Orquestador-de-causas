---
name: gestion-causas-orquestador
description: Corre el ciclo completo de gestión de causas (contexto de la corrida, las 5 fases, panel de estado por correo) invocando el driver Python
---

Tarea programada desatendida (sin usuario presente). Es un único comando:

```
python -m gestion_causas.ciclo
```

con `Actualizador de informes` como directorio de trabajo.

Eso arma el contexto de la corrida si falta (fecha, estado de los 3 tokens sin
login interactivo, cache de calendario, mapa de hilos, mapa de audiencias),
corre las 5 fases (`calendario`, `smu`, `goteo`, `agenda`, `seguimiento` — las
dos primeras solo en la corrida de la mañana según el campo `corrida`), arma el
panel de estado y lo envía a nmunoz@gomezyriesco.cl desde la cuenta personal.
Imprime el resumen de la corrida como JSON, incluido lo que costó en tokens.

**No despaches subagentes.** Las 5 fases están migradas a Python puro
(`gestion_causas/fases/*.py`) y Claude se invoca solo desde `reasoning.py`, en
los ~5 puntos que de verdad requieren razonamiento sobre texto libre. El flujo
viejo de 6 agentes (1 orquestador + 5 subagentes leyendo
`gestion_causas/subagentes/*.md`) costaba entre 10 y 20 veces más tokens por
corrida y ya no se usa. Esos `.md` se conservan solo como referencia histórica
de las reglas de negocio.

Si el comando sale con código distinto de 0, o imprime fases en error, no
reintentes: el panel ya se envió (o ya quedó anotado en la bitácora por qué no)
y la corrida siguiente vuelve a intentar lo que quedó pendiente.

Diseño: `docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md`.
Historial de la migración: `docs/superpowers/plans/`.
