"""Pruebas de la capa JSON-RPC y del protocolo MCP, sin tocar la base de datos."""

import io
import json
import subprocess
import sys

import pytest

from servidor import jsonrpc, main, protocolo
from servidor.protocolo import Sesion

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"}},
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def correr(mensajes):
    """Pasa una lista de mensajes (dicts o cadenas crudas) por el bucle y devuelve las respuestas."""
    entrada = io.StringIO("".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in mensajes))
    salidas = []
    sesion = Sesion(db=None)
    original = main.escribir
    main.escribir = salidas.append
    try:
        main.bucle(sesion.despachar, entrada)
    finally:
        main.escribir = original
    return salidas


def sesion_lista():
    sesion = Sesion(db=None)
    sesion.despachar(jsonrpc.parsear(json.dumps(INITIALIZE)))
    sesion.despachar(jsonrpc.parsear(json.dumps(INITIALIZED)))
    return sesion


def test_handshake_correcto():
    respuestas = correr([INITIALIZE, INITIALIZED])
    assert len(respuestas) == 1
    r = respuestas[0]
    assert r["id"] == 1 and "error" not in r
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert r["result"]["capabilities"] == {"tools": {}}
    assert r["result"]["serverInfo"]["name"]


def test_version_desconocida_devuelve_la_mas_reciente():
    pedido = dict(INITIALIZE, params=dict(INITIALIZE["params"], protocolVersion="1999-01-01"))
    r = correr([pedido])[0]
    assert r["result"]["protocolVersion"] == protocolo.VERSIONES_SOPORTADAS[0]


def test_rechaza_metodos_antes_de_initialize():
    r = correr([{"jsonrpc": "2.0", "id": 7, "method": "tools/list"}])[0]
    assert r["id"] == 7
    assert r["error"]["code"] == jsonrpc.INVALID_REQUEST


def test_rechaza_tools_antes_de_initialized():
    respuestas = correr([INITIALIZE, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    assert respuestas[1]["error"]["code"] == jsonrpc.INVALID_REQUEST


def test_initialize_dos_veces_falla():
    respuestas = correr([INITIALIZE, INITIALIZED, dict(INITIALIZE, id=2)])
    assert respuestas[1]["id"] == 2
    assert respuestas[1]["error"]["code"] == jsonrpc.INVALID_REQUEST


def test_ping_funciona_en_cualquier_estado():
    respuestas = correr([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, INITIALIZE, INITIALIZED,
                         {"jsonrpc": "2.0", "id": 3, "method": "ping"}])
    assert respuestas[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert respuestas[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_json_malformado_devuelve_parse_error():
    r = correr(["{esto no es json"])[0]
    assert r["id"] is None
    assert r["error"]["code"] == jsonrpc.PARSE_ERROR


@pytest.mark.parametrize("crudo", [
    "[1, 2, 3]",
    '{"id": 1, "method": "ping"}',
    '{"jsonrpc": "2.0", "id": 1}',
    '{"jsonrpc": "2.0", "id": 1, "method": 5}',
    '{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": "x"}',
    '{"jsonrpc": "2.0", "id": {"a": 1}, "method": "ping"}',
])
def test_request_invalido(crudo):
    r = correr([crudo])[0]
    assert r["error"]["code"] == jsonrpc.INVALID_REQUEST


def test_metodo_inexistente():
    respuestas = correr([INITIALIZE, INITIALIZED, {"jsonrpc": "2.0", "id": 9, "method": "no/existe"}])
    assert respuestas[1]["id"] == 9
    assert respuestas[1]["error"]["code"] == jsonrpc.METHOD_NOT_FOUND


def test_notificacion_no_genera_respuesta():
    respuestas = correr([
        INITIALIZE, INITIALIZED,
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
        {"jsonrpc": "2.0", "method": "metodo/desconocido"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ])
    assert [r["id"] for r in respuestas] == [1, 2]


@pytest.mark.parametrize("id_", [1, 0, "abc", 3.5, None])
def test_id_de_respuesta_coincide(id_):
    respuestas = correr([INITIALIZE, INITIALIZED, {"jsonrpc": "2.0", "id": id_, "method": "ping"}])
    assert respuestas[1]["id"] == id_
    assert respuestas[1]["jsonrpc"] == "2.0"


def test_respuesta_nunca_lleva_result_y_error():
    respuestas = correr([INITIALIZE, INITIALIZED, {"jsonrpc": "2.0", "id": 2, "method": "x"},
                         {"jsonrpc": "2.0", "id": 3, "method": "ping"}])
    for r in respuestas:
        assert ("result" in r) != ("error" in r)


def test_tools_list_publica_esquemas():
    sesion = sesion_lista()
    herramientas = sesion.despachar(jsonrpc.parsear('{"jsonrpc":"2.0","id":1,"method":"tools/list"}'))["tools"]
    assert {h["name"] for h in herramientas} == {
        "posicion_actual", "unidades_detenidas", "resumen_recorrido", "mapa_recorrido",
        "alertas", "verificar_geocerca", "reporte_kilometraje",
    }
    for h in herramientas:
        assert h["description"]
        assert h["inputSchema"]["type"] == "object"
        assert "properties" in h["inputSchema"] and "required" in h["inputSchema"]
        assert set(h) == {"name", "description", "inputSchema"}


@pytest.mark.parametrize("params", [
    {"name": "posicion_actual", "arguments": {}},
    {"name": "posicion_actual", "arguments": {"placa": 123}},
    {"name": "posicion_actual", "arguments": {"placa": "P-1", "extra": 1}},
    {"name": "unidades_detenidas", "arguments": {"minutos_minimos": "30"}},
    {"name": "unidades_detenidas", "arguments": {"minutos_minimos": True}},
    {"name": "alertas", "arguments": {"tipo": "otro", "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-02"}},
    {"name": "herramienta_inexistente", "arguments": {}},
    {"arguments": {}},
])
def test_argumentos_invalidos_devuelven_32602(params):
    sesion = sesion_lista()
    with pytest.raises(jsonrpc.ErrorRPC) as info:
        sesion.despachar({"method": "tools/call", "params": params, "id": 1, "es_notificacion": False})
    assert info.value.code == jsonrpc.INVALID_PARAMS


def test_sin_base_de_datos_es_error_de_negocio():
    sesion = sesion_lista()
    r = sesion.despachar({"method": "tools/call", "id": 1, "es_notificacion": False,
                          "params": {"name": "posicion_actual", "arguments": {"placa": "P-123BCD"}}})
    assert r["isError"] is True
    assert r["content"][0]["type"] == "text"


def test_proceso_real_por_stdio_y_cierre_limpio():
    """Arranca el servidor de verdad y confirma que stdout solo lleva JSON y que EOF lo termina."""
    proceso = subprocess.Popen(
        [sys.executable, "-m", "servidor.main"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    entrada = "\n".join(json.dumps(m) for m in [INITIALIZE, INITIALIZED, {"jsonrpc": "2.0", "id": 2, "method": "ping"}]) + "\n"
    salida, _ = proceso.communicate(entrada, timeout=20)
    assert proceso.returncode == 0
    lineas = [json.loads(l) for l in salida.splitlines() if l]
    assert [l["id"] for l in lineas] == [1, 2]
