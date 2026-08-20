"""Pruebas de las seis herramientas contra el set sintético y sus eventos inyectados."""

import base64
import json
from datetime import timedelta

import pytest

from servidor import registro
from servidor.herramientas import alertas, detenidas, geocercas, kilometraje, mapa, posicion, recorrido
from servidor.registro import ErrorNegocio, MAX_FILAS
from tests.conftest import AHORA

import generador

HOY = AHORA.date()
AYER = HOY - timedelta(days=1)
INICIO_SEMANA = HOY - timedelta(days=6)


def llamar(herramienta, db, **argumentos):
    return json.loads(herramienta.ejecutar(db, argumentos))


def placa_de(indice):
    return generador.VEHICULOS[indice][0]


def contar_filas(valor):
    """Número de elementos en la lista más larga anidada en la respuesta."""
    if isinstance(valor, list):
        return max([len(valor)] + [contar_filas(v) for v in valor])
    if isinstance(valor, dict):
        return max([0] + [contar_filas(v) for v in valor.values()])
    return 0


def test_posicion_actual_de_unidad_activa(db):
    r = llamar(posicion, db, placa="P-456DEF")
    assert r["placa"] == "P-456DEF"
    assert r["ultimo_reporte"].startswith(str(HOY))
    assert 14.3 < r["lat"] < 14.8 and -90.8 < r["lon"] < -90.3
    assert r["direccion"]


def test_posicion_actual_acepta_minusculas(db):
    assert llamar(posicion, db, placa="p-456def")["placa"] == "P-456DEF"


def test_posicion_actual_placa_inexistente(db):
    with pytest.raises(ErrorNegocio, match="No existe la placa"):
        llamar(posicion, db, placa="P-000XXX")


def test_posicion_actual_unidad_inactiva(db):
    with pytest.raises(ErrorNegocio, match="dada de baja"):
        llamar(posicion, db, placa=generador.PLACA_INACTIVA)


def test_unidades_detenidas_encuentra_las_inyectadas(db, plan):
    r = llamar(detenidas, db, minutos_minimos=30)
    por_placa = {u["placa"]: u for u in r["unidades"]}
    for indice, minutos in plan["detenidas_ahora"].items():
        unidad = por_placa[placa_de(indice)]
        # Puede llevar más tiempo si ya estaba en una parada cuando se forzó la detención.
        assert unidad["minutos_detenida"] >= minutos
        assert unidad["estado"] == "motor encendido"


def test_unidades_detenidas_respeta_el_minimo(db):
    pocas = llamar(detenidas, db, minutos_minimos=90)["unidades"]
    muchas = llamar(detenidas, db, minutos_minimos=10)["unidades"]
    assert all(u["minutos_detenida"] >= 90 for u in pocas)
    assert len(muchas) >= len(pocas)


def test_unidades_detenidas_default_30(db):
    assert llamar(detenidas, db)["minutos_minimos"] == 30


def test_resumen_recorrido_detecta_parada_prolongada(db, plan):
    (indice, fecha), paradas = next(iter(plan["paradas_largas"].items()))
    r = llamar(recorrido, db, placa=placa_de(indice), fecha=str(fecha))
    minutos_esperados = max(paradas.values())
    assert any(abs(p["minutos"] - minutos_esperados) <= 1 for p in r["paradas"])
    assert r["kilometros"] > 20
    assert r["hora_salida"] < r["hora_retorno"]
    assert r["velocidad_maxima_kmh"] >= r["velocidad_promedio_kmh"]


def test_resumen_recorrido_detecta_hueco_de_senal(db, plan):
    (indice, fecha), (_, minutos) = next(iter(plan["huecos"].items()))
    r = llamar(recorrido, db, placa=placa_de(indice), fecha=str(fecha))
    assert any(abs(h["minutos"] - minutos) <= 1 for h in r["perdidas_de_senal"])


def test_resumen_recorrido_dia_sin_datos(db):
    with pytest.raises(ErrorNegocio, match="no tiene reportes"):
        llamar(recorrido, db, placa="P-123BCD", fecha="2020-01-01")


def test_resumen_recorrido_fecha_invalida(db):
    with pytest.raises(ErrorNegocio, match="AAAA-MM-DD"):
        llamar(recorrido, db, placa="P-123BCD", fecha="ayer")


def test_alertas_excesos_coinciden_con_los_inyectados(db, plan):
    r = llamar(alertas, db, tipo="exceso_velocidad", fecha_inicio=str(INICIO_SEMANA), fecha_fin=str(HOY))
    esperados = db.execute("SELECT count(*) FROM eventos WHERE tipo = 'exceso_velocidad'").fetchone()[0]
    assert r["total_eventos"] == esperados
    assert sum(u["total"] for u in r["por_unidad"]) == esperados
    graves = r["eventos_mas_graves"]
    assert all(e["detalle"]["velocidad_max"] > generador.LIMITE_VELOCIDAD_KMH for e in graves)
    assert graves == sorted(graves, key=lambda e: e["detalle"]["velocidad_max"], reverse=True)


def test_alertas_sin_tipo_excluye_geocercas_del_detalle(db):
    r = llamar(alertas, db, fecha_inicio=str(INICIO_SEMANA), fecha_fin=str(HOY))
    assert "geocerca_entrada" in r["por_tipo"]
    assert all(not e["tipo"].startswith("geocerca_") for e in r["eventos_mas_graves"])


def test_alertas_rango_vacio(db):
    with pytest.raises(ErrorNegocio, match="No hay alertas"):
        llamar(alertas, db, fecha_inicio="2020-01-01", fecha_fin="2020-01-07")


def test_alertas_rango_invertido(db):
    with pytest.raises(ErrorNegocio, match="anterior"):
        llamar(alertas, db, fecha_inicio=str(HOY), fecha_fin=str(AYER))


def test_verificar_geocerca_coincide_con_eventos(db):
    """Las visitas que calcula la herramienta deben coincidir con las entradas registradas por el generador."""
    placa, nombre = "P-456DEF", "CEDIS Zona 12"
    r = llamar(geocercas, db, placa=placa, nombre_geocerca=nombre, fecha=str(AYER))
    entradas = db.execute(
        "SELECT count(*) FROM eventos e JOIN vehiculos v ON v.id = e.vehiculo_id "
        "WHERE v.placa = ? AND e.tipo = 'geocerca_entrada' AND json_extract(e.detalle, '$.geocerca') = ? "
        "AND substr(e.ts, 1, 10) = ?",
        (placa, nombre, str(AYER)),
    ).fetchone()[0]
    assert r["entro"] is True
    entradas_del_dia = [v for v in r["visitas"] if not v["desde_inicio_del_dia"]]
    assert len(entradas_del_dia) == entradas
    assert r["minutos_total_dentro"] == sum(v["minutos_dentro"] for v in r["visitas"])


def test_verificar_geocerca_no_entro(db):
    # La ruta de la P-789GHJ va de Villa Nueva a Amatitlán y nunca pasa por Zona 18.
    r = llamar(geocercas, db, placa="P-789GHJ", nombre_geocerca="CD Zona 18", fecha=str(AYER))
    assert r["entro"] is False and r["visitas"] == []


def test_verificar_geocerca_nombre_parcial_y_ambiguo(db):
    assert llamar(geocercas, db, placa="P-456DEF", nombre_geocerca="cedis", fecha=str(AYER))["geocerca"] == "CEDIS Zona 12"
    with pytest.raises(ErrorNegocio, match="ambiguo"):
        llamar(geocercas, db, placa="P-456DEF", nombre_geocerca="bodega", fecha=str(AYER))
    with pytest.raises(ErrorNegocio, match="No existe la geocerca"):
        llamar(geocercas, db, placa="P-456DEF", nombre_geocerca="Marte", fecha=str(AYER))


def test_reporte_kilometraje_ordenado_y_consistente(db):
    r = llamar(kilometraje, db, fecha_inicio=str(INICIO_SEMANA), fecha_fin=str(HOY))
    km = [u["kilometros"] for u in r["ranking"]]
    assert km == sorted(km, reverse=True)
    assert [u["puesto"] for u in r["ranking"]] == list(range(1, len(km) + 1))
    assert generador.PLACA_INACTIVA not in {u["placa"] for u in r["ranking"]}
    # El kilometraje de un día debe coincidir con lo que reporta resumen_recorrido.
    dia = llamar(kilometraje, db, fecha_inicio=str(AYER), fecha_fin=str(AYER))
    primero = dia["ranking"][0]
    resumen = llamar(recorrido, db, placa=primero["placa"], fecha=str(AYER))
    assert abs(resumen["kilometros"] - primero["kilometros"]) < 0.2


def test_reporte_kilometraje_rango_vacio(db):
    with pytest.raises(ErrorNegocio, match="Ninguna unidad"):
        llamar(kilometraje, db, fecha_inicio="2020-01-01", fecha_fin="2020-01-31")


@pytest.mark.parametrize("nombre, argumentos", [
    ("posicion_actual", {"placa": "P-123BCD"}),
    ("unidades_detenidas", {"minutos_minimos": 0}),
    ("resumen_recorrido", {"placa": "P-234KLM", "fecha": str(AYER)}),
    ("alertas", {"fecha_inicio": str(INICIO_SEMANA), "fecha_fin": str(HOY)}),
    ("alertas", {"tipo": "geocerca_entrada", "fecha_inicio": str(INICIO_SEMANA), "fecha_fin": str(HOY)}),
    ("verificar_geocerca", {"placa": "P-123BCD", "nombre_geocerca": "Centro Histórico", "fecha": str(AYER)}),
    ("reporte_kilometraje", {"fecha_inicio": str(INICIO_SEMANA), "fecha_fin": str(HOY)}),
])
def test_ninguna_respuesta_supera_el_tope_de_filas(db, nombre, argumentos):
    herramienta = registro.obtener(nombre)
    respuesta = json.loads(herramienta["ejecutar"](db, argumentos))
    assert contar_filas(respuesta) <= MAX_FILAS


def test_tope_de_filas_es_explicito():
    assert MAX_FILAS == 200


def test_mapa_recorrido_devuelve_texto_e_imagen_png(db):
    bloques = mapa.ejecutar(db, {"placa": "P-456DEF", "fecha": str(AYER)})
    assert [b["type"] for b in bloques] == ["text", "image"]
    assert bloques[1]["mimeType"] == "image/png"
    png = base64.b64decode(bloques[1]["data"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert json.loads(bloques[0]["text"])["placa"] == "P-456DEF"


def test_mapa_recorrido_funciona_sin_red(db, monkeypatch):
    def sin_red(*args):
        raise OSError("sin conexión")
    monkeypatch.setattr(mapa, "descargar_tile", sin_red)
    bloques = mapa.ejecutar(db, {"placa": "P-456DEF", "fecha": str(AYER)})
    assert json.loads(bloques[0]["text"])["fondo"].startswith("sin mapa base")
    assert base64.b64decode(bloques[1]["data"])[:4] == b"\x89PNG"


def test_mapa_recorrido_dia_sin_datos(db):
    with pytest.raises(ErrorNegocio, match="no tiene reportes"):
        mapa.ejecutar(db, {"placa": "P-456DEF", "fecha": "2020-01-01"})
