"""mapa_recorrido: imagen PNG con el trazo de una unidad en un día.

El mapa se dibuja con matplotlib sobre tiles de OpenStreetMap descargados con
urllib. Si no hay red se dibuja el trazo sobre fondo plano; la herramienta
nunca falla por conectividad.
"""

import base64
import io
import json
import logging
import math
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from servidor.herramientas import comun, recorrido  # noqa: E402

log = logging.getLogger("mcp")

TAMANO_TILE = 256
MAX_TILES_POR_LADO = 4
TIMEOUT_S = 4
USER_AGENT = "mcp-flota-gt/1.0 (proyecto universitario CC3067)"
MAX_PUNTOS_TRAZO = 2000

_cache_tiles = {}


def a_pixel(lat, lon, zoom):
    """Coordenada en píxeles globales de Web Mercator para un nivel de zoom."""
    escala = TAMANO_TILE * 2 ** zoom
    x = (lon + 180) / 360 * escala
    lat_r = math.radians(lat)
    y = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * escala
    return x, y


def elegir_zoom(lat_min, lat_max, lon_min, lon_max):
    """El mayor zoom en que el recorrido cabe en MAX_TILES_POR_LADO tiles."""
    for zoom in range(16, 9, -1):
        x0, y0 = a_pixel(lat_max, lon_min, zoom)
        x1, y1 = a_pixel(lat_min, lon_max, zoom)
        if (x1 - x0) / TAMANO_TILE <= MAX_TILES_POR_LADO and (y1 - y0) / TAMANO_TILE <= MAX_TILES_POR_LADO:
            return zoom
    return 10


def descargar_tile(zoom, tx, ty):
    clave = (zoom, tx, ty)
    if clave not in _cache_tiles:
        url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
        peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as r:
            _cache_tiles[clave] = mpimg.imread(io.BytesIO(r.read()), format="png")
    return _cache_tiles[clave]


def dibujar_fondo(ax, zoom, x0, y0, x1, y1):
    """Coloca los tiles que cubren el rectángulo en píxeles. Devuelve False si no hubo red."""
    con_fondo = True
    for tx in range(int(x0 // TAMANO_TILE), int(x1 // TAMANO_TILE) + 1):
        for ty in range(int(y0 // TAMANO_TILE), int(y1 // TAMANO_TILE) + 1):
            try:
                imagen = descargar_tile(zoom, tx, ty)
            except Exception as e:
                log.warning("tile %s/%s/%s no disponible: %s", zoom, tx, ty, e)
                return False
            ax.imshow(imagen, extent=(tx * TAMANO_TILE, (tx + 1) * TAMANO_TILE,
                                      (ty + 1) * TAMANO_TILE, ty * TAMANO_TILE), zorder=0)
    return con_fondo


def ejecutar(db, argumentos):
    vehiculo = comun.buscar_vehiculo(db, argumentos["placa"])
    fecha = comun.parsear_fecha(argumentos["fecha"])
    df = comun.posiciones_del_dia(db, vehiculo["id"], fecha)
    if df.empty:
        raise comun.ErrorNegocio(f"La unidad {vehiculo['placa']} no tiene reportes el {fecha}")

    # Submuestreo uniforme: para dibujar no hacen falta los ~2 000 puntos de una jornada.
    paso = max(1, len(df) // MAX_PUNTOS_TRAZO)
    trazo = df.iloc[::paso]

    margen = 0.004
    lat_min, lat_max = df.lat.min() - margen, df.lat.max() + margen
    lon_min, lon_max = df.lon.min() - margen, df.lon.max() + margen
    zoom = elegir_zoom(lat_min, lat_max, lon_min, lon_max)
    x0, y0 = a_pixel(lat_max, lon_min, zoom)
    x1, y1 = a_pixel(lat_min, lon_max, zoom)

    fig, ax = plt.subplots(figsize=(8, 8 * (y1 - y0) / (x1 - x0)), dpi=96)
    con_fondo = dibujar_fondo(ax, zoom, x0, y0, x1, y1)
    if not con_fondo:
        ax.set_facecolor("#f2efe9")

    for nombre, _, poligono in comun.geocercas(db):
        lons, lats = poligono.exterior.xy
        px = [a_pixel(la, lo, zoom) for la, lo in zip(lats, lons)]
        ax.fill([p[0] for p in px], [p[1] for p in px], color="#1f77b4", alpha=0.18, zorder=1)
        ax.plot([p[0] for p in px], [p[1] for p in px], color="#1f77b4", linewidth=1, zorder=1)
        cx, cy = a_pixel(poligono.centroid.y, poligono.centroid.x, zoom)
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            ax.annotate(nombre, (cx, cy), fontsize=7, color="#1f77b4", ha="center", va="bottom", zorder=4)

    pixeles = [a_pixel(la, lo, zoom) for la, lo in zip(trazo.lat, trazo.lon)]
    ax.plot([p[0] for p in pixeles], [p[1] for p in pixeles], color="#d62728", linewidth=1.8, alpha=0.9, zorder=2)

    jornada = df[df.velocidad > 0]
    if not jornada.empty:
        jornada = df[(df.ts >= jornada.ts.iloc[0]) & (df.ts <= jornada.ts.iloc[-1])].copy()
        jornada["quieta"] = jornada.velocidad == 0
        # Las paradas en el mismo lugar (a ~100 m) se agrupan para que las
        # etiquetas no se encimen cuando la unidad pasa varias veces por un punto.
        lugares = {}
        for quieta, primera, ultima in recorrido.segmentos(jornada, "quieta"):
            minutos = comun.minutos_entre(primera.ts, ultima.ts)
            if quieta and minutos >= comun.MINUTOS_PARADA:
                clave = (round(primera.lat, 3), round(primera.lon, 3))
                lugar = lugares.setdefault(clave, {"lat": primera.lat, "lon": primera.lon, "minutos": 0, "veces": 0})
                lugar["minutos"] += minutos
                lugar["veces"] += 1
        for lugar in lugares.values():
            px, py = a_pixel(lugar["lat"], lugar["lon"], zoom)
            ax.scatter(px, py, s=40 + lugar["minutos"] * 2, color="#ff7f0e", edgecolor="black", alpha=0.85, zorder=3)
            etiqueta = f"{lugar['minutos']} min" if lugar["veces"] == 1 else f"{lugar['veces']} paradas · {lugar['minutos']} min"
            ax.annotate(etiqueta, (px, py), fontsize=7, ha="left", va="bottom",
                        xytext=(5, 5), textcoords="offset points", zorder=4,
                        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.8})

    inicio, fin = a_pixel(df.lat.iloc[0], df.lon.iloc[0], zoom), a_pixel(df.lat.iloc[-1], df.lon.iloc[-1], zoom)
    ax.scatter(*inicio, s=90, color="#2ca02c", edgecolor="black", marker="^", zorder=5, label="inicio")
    ax.scatter(*fin, s=90, color="black", marker="s", zorder=5, label="fin")

    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_axis_off()
    km = round(df.odometro.iloc[-1] - df.odometro.iloc[0], 1)
    ax.set_title(f"{vehiculo['placa']} · {fecha} · {km} km", fontsize=11)
    ax.legend(loc="lower left", fontsize=8)
    if con_fondo:
        ax.text(x1, y1, "© OpenStreetMap contributors", fontsize=6, ha="right", va="bottom",
                backgroundcolor="white", zorder=6)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)

    resumen = {
        "placa": vehiculo["placa"],
        "fecha": str(fecha),
        "kilometros": km,
        "reportes_dibujados": len(trazo),
        "fondo": "OpenStreetMap" if con_fondo else "sin mapa base (sin red)",
        "leyenda": "línea roja: recorrido; triángulo verde: inicio; cuadrado negro: fin; "
                   "círculos naranja: paradas (tamaño según minutos); áreas azules: geocercas",
    }
    return [
        {"type": "text", "text": json.dumps(resumen, ensure_ascii=False, indent=2)},
        {"type": "image", "data": base64.b64encode(buffer.getvalue()).decode("ascii"), "mimeType": "image/png"},
    ]


HERRAMIENTA = {
    "name": "mapa_recorrido",
    "description": (
        "Genera una imagen con el mapa del recorrido de una unidad en una fecha: el trazo sobre el "
        "mapa, punto de inicio y fin, paradas con su duración y las geocercas. Úsala cuando el "
        "usuario pida ver el recorrido en un mapa o una imagen de la ruta; para cifras usa "
        "resumen_recorrido. Fecha en AAAA-MM-DD."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "placa": {"type": "string", "description": "Placa de la unidad, por ejemplo P-456DEF"},
            "fecha": {"type": "string", "description": "Día a dibujar, formato AAAA-MM-DD"},
        },
        "required": ["placa", "fecha"],
    },
    "ejecutar": ejecutar,
}
