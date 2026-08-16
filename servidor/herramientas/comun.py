"""Consultas y utilidades que comparten varias herramientas."""

import json
from datetime import date, datetime, timedelta

import pandas as pd
from geopy.distance import great_circle
from shapely.wkt import loads as cargar_wkt

from servidor.registro import ErrorNegocio

FORMATO_TS = "%Y-%m-%d %H:%M:%S"
# Una parada cuenta como tal a partir de esta duración; por debajo es un semáforo o tráfico.
MINUTOS_PARADA = 3


def exigir_db(db):
    if db is None:
        raise ErrorNegocio("La base de datos no está generada. Hay que correr datos/generador.py primero.")


def buscar_vehiculo(db, placa):
    """Devuelve la fila del vehículo o lanza ErrorNegocio con la lista de placas válidas."""
    exigir_db(db)
    fila = db.execute("SELECT * FROM vehiculos WHERE upper(placa) = upper(?)", (placa.strip(),)).fetchone()
    if fila is None:
        placas = [r[0] for r in db.execute("SELECT placa FROM vehiculos ORDER BY placa")]
        raise ErrorNegocio(f"No existe la placa {placa}. Placas registradas: {', '.join(placas)}")
    return fila


def parsear_fecha(texto, nombre="fecha"):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ErrorNegocio(f"'{nombre}' debe tener formato AAAA-MM-DD, recibí {texto!r}")


def rango_dia(fecha):
    """Límites [inicio, fin) en texto para comparar contra la columna ts."""
    inicio = datetime.combine(fecha, datetime.min.time())
    return inicio.strftime(FORMATO_TS), (inicio + timedelta(days=1)).strftime(FORMATO_TS)


def rango_fechas(fecha_inicio, fecha_fin, max_dias=92):
    """Valida un rango inclusivo de fechas y devuelve (inicio, fin) como objetos date."""
    inicio = parsear_fecha(fecha_inicio, "fecha_inicio")
    fin = parsear_fecha(fecha_fin, "fecha_fin")
    if fin < inicio:
        raise ErrorNegocio(f"fecha_fin ({fin}) es anterior a fecha_inicio ({inicio})")
    if (fin - inicio).days > max_dias:
        raise ErrorNegocio(f"El rango no puede superar {max_dias} días")
    return inicio, fin


def instante_actual(db):
    """El 'ahora' de la flota es el último reporte recibido de cualquier unidad."""
    ts = db.execute("SELECT max(ts) FROM posiciones").fetchone()[0]
    if ts is None:
        raise ErrorNegocio("No hay posiciones registradas")
    return datetime.strptime(ts, FORMATO_TS)


def posiciones_del_dia(db, vehiculo_id, fecha):
    """DataFrame con las posiciones de una unidad en un día, ordenadas por ts."""
    inicio, fin = rango_dia(fecha)
    df = pd.read_sql_query(
        "SELECT ts, lat, lon, velocidad, rumbo, ignicion, odometro FROM posiciones "
        "WHERE vehiculo_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
        db, params=(vehiculo_id, inicio, fin), parse_dates=["ts"],
    )
    return df


def geocercas(db):
    """Lista de (nombre, tipo, polígono shapely)."""
    return [(r["nombre"], r["tipo"], cargar_wkt(r["poligono_wkt"]))
            for r in db.execute("SELECT nombre, tipo, poligono_wkt FROM geocercas")]


def referencia_cercana(db, lat, lon):
    """Geocerca más cercana al punto, como referencia legible cuando no hay dirección."""
    mejor = None
    for nombre, _, poligono in geocercas(db):
        centro = poligono.centroid
        metros = great_circle((lat, lon), (centro.y, centro.x)).meters
        if mejor is None or metros < mejor[1]:
            mejor = (nombre, metros)
    if mejor is None:
        return f"{lat:.5f}, {lon:.5f}"
    if mejor[1] < 300:
        return f"en {mejor[0]}"
    return f"a {mejor[1] / 1000:.1f} km de {mejor[0]}"


def punto_cardinal(rumbo):
    puntos = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    return puntos[int((rumbo + 22.5) // 45) % 8]


def minutos_entre(a, b):
    return round((b - a).total_seconds() / 60)


def a_texto(datos):
    """Serializa el resultado como JSON legible; es lo que va en content[0].text."""
    return json.dumps(datos, ensure_ascii=False, indent=2, default=str)
