"""alertas: eventos registrados por la plataforma en un rango de fechas."""

import json

from servidor.herramientas import comun
from servidor.registro import MAX_FILAS

TIPOS = ["exceso_velocidad", "parada_prolongada", "perdida_senal", "geocerca_entrada", "geocerca_salida"]
MAX_DETALLE = 25


def gravedad(evento):
    """Orden de severidad dentro de cada tipo: más velocidad o más minutos primero."""
    d = evento["detalle"]
    return d.get("velocidad_max", 0) + d.get("minutos", 0)


def ejecutar(db, argumentos):
    comun.exigir_db(db)
    inicio, fin = comun.rango_fechas(argumentos["fecha_inicio"], argumentos["fecha_fin"])
    ts_inicio, _ = comun.rango_dia(inicio)
    _, ts_fin = comun.rango_dia(fin)
    tipo = argumentos.get("tipo")

    sql = (
        "SELECT v.placa, e.ts, e.tipo, e.lat, e.lon, e.detalle FROM eventos e "
        "JOIN vehiculos v ON v.id = e.vehiculo_id WHERE e.ts >= ? AND e.ts < ?"
    )
    params = [ts_inicio, ts_fin]
    if tipo:
        sql += " AND e.tipo = ?"
        params.append(tipo)
    filas = db.execute(sql + " ORDER BY e.ts", params).fetchall()
    if not filas:
        que = f"alertas de tipo {tipo}" if tipo else "alertas"
        raise comun.ErrorNegocio(f"No hay {que} entre {inicio} y {fin}")

    eventos = [{"placa": f["placa"], "ts": f["ts"], "tipo": f["tipo"], "lat": f["lat"], "lon": f["lon"],
                "detalle": json.loads(f["detalle"])} for f in filas]

    conteo = {}
    for e in eventos:
        por_unidad = conteo.setdefault(e["placa"], {"total": 0})
        por_unidad["total"] += 1
        por_unidad[e["tipo"]] = por_unidad.get(e["tipo"], 0) + 1
    ranking = sorted(
        ({"placa": placa, **c} for placa, c in conteo.items()),
        key=lambda c: c["total"], reverse=True,
    )

    # Las entradas y salidas de geocerca son operación normal; solo van al
    # detalle si se pidieron explícitamente.
    candidatos = eventos if tipo else [e for e in eventos if not e["tipo"].startswith("geocerca_")]
    graves = sorted(candidatos, key=gravedad, reverse=True)[:MAX_DETALLE]
    for e in graves:
        e["ubicacion"] = comun.referencia_cercana(db, e.pop("lat"), e.pop("lon"))

    return comun.a_texto({
        "fecha_inicio": str(inicio),
        "fecha_fin": str(fin),
        "tipo": tipo or "todos",
        "total_eventos": len(eventos),
        "por_tipo": {t: sum(1 for e in eventos if e["tipo"] == t) for t in TIPOS if any(e["tipo"] == t for e in eventos)},
        "por_unidad": ranking[:MAX_FILAS - MAX_DETALLE],
        "eventos_mas_graves": graves,
    })


HERRAMIENTA = {
    "name": "alertas",
    "description": (
        "Alertas registradas en un rango de fechas, con conteo por unidad y el detalle de los eventos "
        "más graves. Tipos: exceso_velocidad, parada_prolongada, perdida_senal, geocerca_entrada, "
        "geocerca_salida; si no se indica tipo devuelve todas. Úsala para '¿hubo excesos de "
        "velocidad esta semana?' o '¿qué unidad tuvo más alertas ayer?'. Fechas en AAAA-MM-DD."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "tipo": {"type": "string", "enum": TIPOS, "description": "Tipo de alerta a filtrar. Opcional."},
            "fecha_inicio": {"type": "string", "description": "Primer día del rango, AAAA-MM-DD"},
            "fecha_fin": {"type": "string", "description": "Último día del rango (inclusive), AAAA-MM-DD"},
        },
        "required": ["fecha_inicio", "fecha_fin"],
    },
    "ejecutar": ejecutar,
}
