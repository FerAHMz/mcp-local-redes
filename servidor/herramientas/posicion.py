"""posicion_actual: último reporte de una unidad."""

from datetime import datetime

from servidor.herramientas import comun


def ejecutar(db, argumentos):
    vehiculo = comun.buscar_vehiculo(db, argumentos["placa"])
    fila = db.execute(
        "SELECT ts, lat, lon, velocidad, rumbo, ignicion, odometro FROM posiciones "
        "WHERE vehiculo_id = ? ORDER BY ts DESC LIMIT 1",
        (vehiculo["id"],),
    ).fetchone()
    if fila is None:
        raise comun.ErrorNegocio(
            f"La unidad {vehiculo['placa']} no tiene reportes de posición"
            + ("; está dada de baja." if not vehiculo["activo"] else ".")
        )

    ts = datetime.strptime(fila["ts"], comun.FORMATO_TS)
    ahora = comun.instante_actual(db)
    return comun.a_texto({
        "placa": vehiculo["placa"],
        "tipo": vehiculo["tipo"],
        "conductor": vehiculo["conductor"],
        "ultimo_reporte": fila["ts"],
        "minutos_desde_ultimo_reporte": comun.minutos_entre(ts, ahora),
        "direccion": comun.referencia_cercana(db, fila["lat"], fila["lon"]),
        "lat": fila["lat"],
        "lon": fila["lon"],
        "velocidad_kmh": fila["velocidad"],
        "rumbo": f"{fila['rumbo']:.0f}° ({comun.punto_cardinal(fila['rumbo'])})",
        "estado": "en movimiento" if fila["velocidad"] > 0 else ("detenida con motor encendido" if fila["ignicion"] else "apagada"),
        "odometro_km": fila["odometro"],
    })


HERRAMIENTA = {
    "name": "posicion_actual",
    "description": (
        "Devuelve la última posición reportada por una unidad de la flota: dirección o "
        "referencia, coordenadas, velocidad, rumbo, estado del motor y hora del último reporte. "
        "Úsala para preguntas como '¿dónde está la P-123BCD?' o '¿se está moviendo la unidad X?'."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "placa": {"type": "string", "description": "Placa de la unidad, por ejemplo P-123BCD"},
        },
        "required": ["placa"],
    },
    "ejecutar": ejecutar,
}
