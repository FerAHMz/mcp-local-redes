"""resumen_recorrido: resumen de la jornada de una unidad en un día."""

from servidor.herramientas import comun

MAX_PARADAS_DETALLE = 15
# Un hueco mayor a esto entre dos reportes consecutivos se considera pérdida de señal.
MINUTOS_HUECO = 2


def segmentos(df, columna):
    """Agrupa filas consecutivas con el mismo valor booleano en `columna`; devuelve (valor, inicio, fin)."""
    cambios = (df[columna] != df[columna].shift()).cumsum()
    for _, grupo in df.groupby(cambios):
        yield bool(grupo[columna].iloc[0]), grupo.iloc[0], grupo.iloc[-1]


def ejecutar(db, argumentos):
    vehiculo = comun.buscar_vehiculo(db, argumentos["placa"])
    fecha = comun.parsear_fecha(argumentos["fecha"])
    df = comun.posiciones_del_dia(db, vehiculo["id"], fecha)
    if df.empty:
        raise comun.ErrorNegocio(f"La unidad {vehiculo['placa']} no tiene reportes el {fecha}")

    en_movimiento = df[df.velocidad > 0]
    if en_movimiento.empty:
        raise comun.ErrorNegocio(f"La unidad {vehiculo['placa']} no se movió el {fecha}")

    salida = en_movimiento.ts.iloc[0]
    retorno = en_movimiento.ts.iloc[-1]
    jornada = df[(df.ts >= salida) & (df.ts <= retorno)].copy()
    jornada["quieta"] = jornada.velocidad == 0

    paradas = []
    for quieta, primera, ultima in segmentos(jornada, "quieta"):
        minutos = comun.minutos_entre(primera.ts, ultima.ts)
        if quieta and minutos >= comun.MINUTOS_PARADA:
            paradas.append({
                "inicio": primera.ts.strftime("%H:%M"),
                "fin": ultima.ts.strftime("%H:%M"),
                "minutos": minutos,
                "lugar": comun.referencia_cercana(db, primera.lat, primera.lon),
            })

    huecos = []
    brechas = df.ts.diff().dt.total_seconds().div(60)
    for i in brechas[brechas > MINUTOS_HUECO].index:
        huecos.append({
            "desde": df.ts[i - 1].strftime("%H:%M"),
            "hasta": df.ts[i].strftime("%H:%M"),
            "minutos": round(brechas[i]),
        })

    # El odómetro lo lleva el dispositivo, así que la diferencia es el kilometraje del día.
    km = round(df.odometro.iloc[-1] - df.odometro.iloc[0], 1)
    horas_movimiento = len(en_movimiento) * 15 / 3600

    return comun.a_texto({
        "placa": vehiculo["placa"],
        "conductor": vehiculo["conductor"],
        "fecha": str(fecha),
        "kilometros": km,
        "hora_salida": salida.strftime("%H:%M"),
        "hora_retorno": retorno.strftime("%H:%M"),
        "duracion_jornada_min": comun.minutos_entre(salida, retorno),
        "velocidad_maxima_kmh": float(df.velocidad.max()),
        "velocidad_promedio_kmh": round(km / horas_movimiento, 1) if horas_movimiento else 0.0,
        "numero_paradas": len(paradas),
        "minutos_total_paradas": sum(p["minutos"] for p in paradas),
        "paradas": sorted(paradas, key=lambda p: p["minutos"], reverse=True)[:MAX_PARADAS_DETALLE],
        "perdidas_de_senal": huecos[:MAX_PARADAS_DETALLE],
        "reportes_recibidos": len(df),
    })


HERRAMIENTA = {
    "name": "resumen_recorrido",
    "description": (
        "Resume el recorrido de una unidad en una fecha: kilómetros, hora de salida y de retorno, "
        "número y duración de las paradas (las más largas con su ubicación), velocidad máxima y "
        "promedio, y huecos de señal. Úsala para 'dame el recorrido de la P-456DEF de ayer' o "
        "'¿cuánto paró la unidad X el lunes?'. La fecha va en formato AAAA-MM-DD."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "placa": {"type": "string", "description": "Placa de la unidad, por ejemplo P-456DEF"},
            "fecha": {"type": "string", "description": "Día a resumir, formato AAAA-MM-DD"},
        },
        "required": ["placa", "fecha"],
    },
    "ejecutar": ejecutar,
}
