"""Capa MCP: handshake de inicialización, máquina de estados y despacho de métodos."""

import logging

from servidor import jsonrpc, registro

log = logging.getLogger("mcp")

# La primera es la que ofrezco cuando el cliente pide una versión que no conozco.
VERSIONES_SOPORTADAS = ("2025-06-18", "2025-03-26", "2024-11-05")

INFO_SERVIDOR = {"name": "mcp-flota-gt", "version": "1.0.0"}

# Estados de la sesión. Solo initialize y notifications/initialized la hacen
# avanzar; el resto de métodos (salvo ping) se rechaza mientras no esté LISTA.
NUEVA = "nueva"
INICIALIZANDO = "inicializando"
LISTA = "lista"


class Sesion:
    """Una sesión MCP sobre una conexión stdio."""

    def __init__(self, db=None):
        self.db = db
        self.estado = NUEVA
        self.version_protocolo = None
        self.cliente = None
        self._metodos = {
            "initialize": self._initialize,
            "notifications/initialized": self._initialized,
            "ping": self._ping,
            "tools/list": self._tools_list,
            "tools/call": self._tools_call,
        }

    def despachar(self, mensaje):
        """Resuelve un mensaje ya parseado y devuelve el `result` del método."""
        metodo = mensaje["method"]
        manejador = self._metodos.get(metodo)

        if manejador is None:
            if metodo.startswith("notifications/"):
                # Notificaciones que no manejo (por ejemplo notifications/cancelled)
                # se ignoran en silencio: responder a una notificación es un error.
                log.debug("notificación ignorada: %s", metodo)
                return None
            raise jsonrpc.ErrorRPC(jsonrpc.METHOD_NOT_FOUND, data=metodo)

        self._verificar_estado(metodo)
        return manejador(mensaje["params"])

    def _verificar_estado(self, metodo):
        if metodo == "ping" or self.estado == LISTA and metodo != "initialize":
            return
        if metodo == "initialize" and self.estado == NUEVA:
            return
        if metodo == "notifications/initialized" and self.estado == INICIALIZANDO:
            return
        if metodo == "initialize":
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_REQUEST, "La sesión ya fue inicializada")
        raise jsonrpc.ErrorRPC(
            jsonrpc.INVALID_REQUEST,
            "El servidor no ha sido inicializado",
            data={"estado": self.estado, "method": metodo},
        )

    def _initialize(self, params):
        if not isinstance(params, dict) or "protocolVersion" not in params:
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data="Falta 'protocolVersion'")

        pedida = params["protocolVersion"]
        # Si no conozco la versión pedida devuelvo la más reciente que sí soporto
        # y dejo que el cliente decida si continúa o cierra la conexión.
        self.version_protocolo = pedida if pedida in VERSIONES_SOPORTADAS else VERSIONES_SOPORTADAS[0]
        self.cliente = params.get("clientInfo", {})
        self.estado = INICIALIZANDO
        log.info(
            "initialize de %s %s (protocolo %s -> %s)",
            self.cliente.get("name", "?"), self.cliente.get("version", ""), pedida, self.version_protocolo,
        )
        return {
            "protocolVersion": self.version_protocolo,
            "capabilities": {"tools": {}},
            "serverInfo": INFO_SERVIDOR,
        }

    def _initialized(self, params):
        self.estado = LISTA
        log.info("handshake completo, sesión lista")
        return None

    def _ping(self, params):
        return {}

    def _tools_list(self, params):
        return {"tools": registro.listar()}

    def _tools_call(self, params):
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data="Falta 'name'")

        herramienta = registro.obtener(params["name"])
        if herramienta is None:
            # La especificación de MCP trata una herramienta desconocida como
            # parámetros inválidos, no como método inexistente.
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data=f"Herramienta desconocida: {params['name']}")

        argumentos = params.get("arguments", {})
        registro.validar_argumentos(herramienta, argumentos)
        log.info("tools/call %s %s", herramienta["name"], argumentos)

        try:
            resultado = herramienta["ejecutar"](self.db, argumentos)
        except registro.ErrorNegocio as e:
            log.info("  -> error de negocio: %s", e)
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}

        # Una herramienta devuelve texto o, si necesita varios bloques (por
        # ejemplo texto más una imagen), la lista de bloques ya armada.
        if isinstance(resultado, list):
            return {"content": resultado}
        return {"content": [{"type": "text", "text": resultado}]}
