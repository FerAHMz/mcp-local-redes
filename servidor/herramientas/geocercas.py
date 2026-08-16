"""verificar_geocerca: si una unidad entró a una geocerca en un día y cuánto estuvo dentro."""

from shapely import contains_xy

from servidor.herramientas import comun

# Reportes consecutivos necesarios para confirmar un cambio de lado del
# polígono; el ruido del GPS en el borde produce cambios espurios de un punto.
HISTERESIS = 4


def buscar_geocerca(db, nombre):
    """Acepta el nombre exacto o una parte (sin distinguir mayúsculas)."""
    todas = comun.geocercas(db)
    nombre_n = nombre.strip().lower()
    exactas = [g for g in todas if g[0].lower() == nombre_n]
    parciales = [g for g in todas if nombre_n in g[0].lower()]
    if exactas:
        return exactas[0]
    if len(parciales) == 1:
        return parciales[0]
    nombres = ", ".join(g[0] for g in todas)
    if len(parciales) > 1:
        raise comun.ErrorNegocio(f"'{nombre}' es ambiguo; coincide con: {', '.join(g[0] for g in parciales)}")
    raise comun.ErrorNegocio(f"No existe la geocerca '{nombre}'. Geocercas definidas: {nombres}")


def visitas(df, poligono):
    """Periodos [entrada, salida] dentro del polígono, con histéresis contra el ruido."""
    dentro = contains_xy(poligono, df.lon.values, df.lat.values)
    periodos, estado, racha, inicio = [], False, 0, None
    for k, esta in enumerate(dentro):
        if esta == estado:
            racha = 0
            continue
        racha += 1
        if racha < HISTERESIS:
            continue
        momento = df.ts.iloc[k - racha + 1]
        if esta:
            inicio = momento
        else:
            periodos.append((inicio, momento, False))
        estado, racha = bool(esta), 0
    if estado:
        periodos.append((inicio, df.ts.iloc[-1], True))
    return periodos


def ejecutar(db, argumentos):
    vehiculo = comun.buscar_vehiculo(db, argumentos["placa"])
    nombre, tipo, poligono = buscar_geocerca(db, argumentos["nombre_geocerca"])
    fecha = comun.parsear_fecha(argumentos["fecha"])
    df = comun.posiciones_del_dia(db, vehiculo["id"], fecha)
    if df.empty:
        raise comun.ErrorNegocio(f"La unidad {vehiculo['placa']} no tiene reportes el {fecha}")

    periodos = visitas(df, poligono)
    detalle = [{
        "entrada": entrada.strftime("%H:%M"),
        "salida": None if sigue else salida.strftime("%H:%M"),
        "minutos_dentro": comun.minutos_entre(entrada, salida),
        "sigue_dentro": sigue,
    } for entrada, salida, sigue in periodos]

    return comun.a_texto({
        "placa": vehiculo["placa"],
        "geocerca": nombre,
        "tipo_geocerca": tipo,
        "fecha": str(fecha),
        "entro": bool(periodos),
        "numero_visitas": len(periodos),
        "minutos_total_dentro": sum(v["minutos_dentro"] for v in detalle),
        "visitas": detalle,
    })


HERRAMIENTA = {
    "name": "verificar_geocerca",
    "description": (
        "Verifica si una unidad entró a una geocerca (bodega, centro de distribución o zona) en una "
        "fecha, con hora de entrada, hora de salida y minutos dentro por cada visita. Úsala para "
        "'¿la P-123BCD entró a la bodega hoy?' o '¿a qué hora llegó la unidad X al CEDIS?'. "
        "Acepta el nombre completo de la geocerca o una parte."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "placa": {"type": "string", "description": "Placa de la unidad"},
            "nombre_geocerca": {"type": "string", "description": "Nombre de la geocerca, por ejemplo 'CEDIS Zona 12' o 'Mixco'"},
            "fecha": {"type": "string", "description": "Día a verificar, AAAA-MM-DD"},
        },
        "required": ["placa", "nombre_geocerca", "fecha"],
    },
    "ejecutar": ejecutar,
}
