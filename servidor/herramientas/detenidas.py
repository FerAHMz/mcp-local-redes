"""unidades_detenidas: unidades que llevan más de N minutos sin moverse."""

from datetime import datetime

from servidor.herramientas import comun
from servidor.registro import MAX_FILAS


def ejecutar(db, argumentos):
    comun.exigir_db(db)
    minimo = argumentos.get("minutos_minimos", 30)
    if minimo < 0:
        raise comun.ErrorNegocio("minutos_minimos no puede ser negativo")
    ahora = comun.instante_actual(db)

    # Por unidad: su último reporte y el último momento en que se movió. La
    # diferencia entre ese momento y el instante actual es el tiempo detenida.
    filas = db.execute(
        """
        SELECT v.placa, v.conductor, p.ts AS ultimo_ts, p.lat, p.lon, p.ignicion,
               (SELECT max(ts) FROM posiciones m WHERE m.vehiculo_id = v.id AND m.velocidad > 0) AS ultimo_movimiento,
               (SELECT min(ts) FROM posiciones m WHERE m.vehiculo_id = v.id) AS primer_reporte
        FROM vehiculos v
        JOIN posiciones p ON p.vehiculo_id = v.id
        WHERE v.activo = 1
          AND p.ts = (SELECT max(ts) FROM posiciones u WHERE u.vehiculo_id = v.id)
        """
    ).fetchall()

    detenidas = []
    for f in filas:
        ultimo = datetime.strptime(f["ultimo_ts"], comun.FORMATO_TS)
        if ultimo == datetime.strptime(f["ultimo_movimiento"] or f["primer_reporte"], comun.FORMATO_TS):
            continue
        desde = datetime.strptime(f["ultimo_movimiento"] or f["primer_reporte"], comun.FORMATO_TS)
        minutos = comun.minutos_entre(desde, ahora)
        if minutos < minimo:
            continue
        detenidas.append({
            "placa": f["placa"],
            "conductor": f["conductor"],
            "minutos_detenida": minutos,
            "detenida_desde": f["ultimo_movimiento"] or f["primer_reporte"],
            "estado": "motor encendido" if f["ignicion"] else "apagada",
            "ultimo_reporte": f["ultimo_ts"],
            "ubicacion": comun.referencia_cercana(db, f["lat"], f["lon"]),
            "lat": f["lat"],
            "lon": f["lon"],
        })

    detenidas.sort(key=lambda d: d["minutos_detenida"], reverse=True)
    return comun.a_texto({
        "instante_consulta": ahora.strftime(comun.FORMATO_TS),
        "minutos_minimos": minimo,
        "total": len(detenidas),
        "unidades": detenidas[:MAX_FILAS],
    })


HERRAMIENTA = {
    "name": "unidades_detenidas",
    "description": (
        "Lista las unidades que llevan al menos cierto número de minutos sin moverse, con su "
        "ubicación, desde cuándo están detenidas y si tienen el motor encendido o apagado. "
        "Úsala para '¿qué unidades llevan más de 30 minutos detenidas?' o '¿hay camiones parados?'."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "minutos_minimos": {
                "type": "integer",
                "description": "Tiempo mínimo detenida en minutos para incluir a la unidad. Por defecto 30.",
            },
        },
        "required": [],
    },
    "ejecutar": ejecutar,
}
