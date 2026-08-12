CREATE TABLE IF NOT EXISTS vehiculos (
    id        INTEGER PRIMARY KEY,
    placa     TEXT    NOT NULL UNIQUE,
    tipo      TEXT    NOT NULL,
    conductor TEXT    NOT NULL,
    activo    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS posiciones (
    id          INTEGER PRIMARY KEY,
    vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id),
    ts          TEXT    NOT NULL,
    lat         REAL    NOT NULL,
    lon         REAL    NOT NULL,
    velocidad   REAL    NOT NULL,
    rumbo       REAL    NOT NULL,
    ignicion    INTEGER NOT NULL,
    odometro    REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS geocercas (
    id           INTEGER PRIMARY KEY,
    nombre       TEXT NOT NULL UNIQUE,
    poligono_wkt TEXT NOT NULL,
    tipo         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos (
    id          INTEGER PRIMARY KEY,
    vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id),
    ts          TEXT    NOT NULL,
    tipo        TEXT    NOT NULL,
    lat         REAL    NOT NULL,
    lon         REAL    NOT NULL,
    detalle     TEXT    NOT NULL
);

-- Sin estos índices cada consulta por unidad y rango de fechas recorre
-- cientos de miles de filas de posiciones.
CREATE INDEX IF NOT EXISTS idx_posiciones_vehiculo_ts ON posiciones(vehiculo_id, ts);
CREATE INDEX IF NOT EXISTS idx_eventos_vehiculo_ts    ON eventos(vehiculo_id, ts);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo_ts        ON eventos(tipo, ts);
