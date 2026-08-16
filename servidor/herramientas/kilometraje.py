"""reporte_kilometraje: ranking de unidades por kilómetros recorridos en un rango de fechas."""

from servidor.herramientas import comun
from servidor.registro import MAX_FILAS


def ejecutar(db, argumentos):
    comun.exigir_db(db)
    inicio, fin = comun.rango_fechas(argumentos["fecha_inicio"], argumentos["fecha_fin"])
    ts_inicio, _ = comun.rango_dia(inicio)
    _, ts_fin = comun.rango_dia(fin)

    # El odómetro es acumulativo por dispositivo, así que el kilometraje del
    # rango es el último valor menos el primero dentro de la ventana.
    filas = db.execute(
        """
        SELECT v.placa, v.tipo, v.conductor,
               max(p.odometro) - min(p.odometro) AS km,
               count(DISTINCT substr(p.ts, 1, 10)) AS dias_operados,
               count(*) AS reportes
        FROM vehiculos v
        JOIN posiciones p ON p.vehiculo_id = v.id
        WHERE p.ts >= ? AND p.ts < ?
        GROUP BY v.id
        ORDER BY km DESC
        LIMIT ?
        """,
        (ts_inicio, ts_fin, MAX_FILAS),
    ).fetchall()
    if not filas:
        raise comun.ErrorNegocio(f"Ninguna unidad reportó entre {inicio} y {fin}")

    ranking = []
    for posicion, f in enumerate(filas, start=1):
        ranking.append({
            "puesto": posicion,
            "placa": f["placa"],
            "tipo": f["tipo"],
            "conductor": f["conductor"],
            "kilometros": round(f["km"], 1),
            "dias_operados": f["dias_operados"],
            "promedio_diario_km": round(f["km"] / f["dias_operados"], 1),
        })

    return comun.a_texto({
        "fecha_inicio": str(inicio),
        "fecha_fin": str(fin),
        "total_flota_km": round(sum(r["kilometros"] for r in ranking), 1),
        "ranking": ranking,
    })


HERRAMIENTA = {
    "name": "reporte_kilometraje",
    "description": (
        "Ranking de las unidades por kilómetros recorridos en un rango de fechas inclusivo, con días "
        "operados y promedio diario. Úsala para '¿cuál unidad recorrió más esta semana?' o "
        "'kilometraje de la flota del mes'. Fechas en formato AAAA-MM-DD."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "fecha_inicio": {"type": "string", "description": "Primer día del rango, AAAA-MM-DD"},
            "fecha_fin": {"type": "string", "description": "Último día del rango (inclusive), AAAA-MM-DD"},
        },
        "required": ["fecha_inicio", "fecha_fin"],
    },
    "ejecutar": ejecutar,
}
