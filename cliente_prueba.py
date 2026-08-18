"""Cliente MCP mínimo para probar el servidor desde la terminal.

Arranca el servidor como subproceso, hace el handshake, lista las herramientas
y permite invocarlas. Imprime cada mensaje JSON tal como viaja por stdin/stdout
para que el protocolo sea visible.

Uso:
    python cliente_prueba.py            # modo interactivo
    python cliente_prueba.py --demo     # secuencia fija con las seis herramientas
"""

import json
import subprocess
import sys
from datetime import date, timedelta

VERSION_PROTOCOLO = "2025-06-18"

ROJO, VERDE, AZUL, GRIS, FIN = "\033[31m", "\033[32m", "\033[34m", "\033[90m", "\033[0m"


class Cliente:
    def __init__(self, comando):
        self.proceso = subprocess.Popen(
            comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, text=True, bufsize=1,
        )
        self.siguiente_id = 1

    def enviar(self, mensaje):
        linea = json.dumps(mensaje, ensure_ascii=False)
        print(f"{AZUL}-> {linea}{FIN}")
        self.proceso.stdin.write(linea + "\n")
        self.proceso.stdin.flush()

    def recibir(self):
        linea = self.proceso.stdout.readline()
        if not linea:
            raise ConnectionError("el servidor cerró stdout")
        print(f"{VERDE}<- {linea.rstrip()}{FIN}")
        return json.loads(linea)

    def llamar(self, metodo, params=None):
        """Envía un request y espera su respuesta, verificando que el id coincida."""
        id_ = self.siguiente_id
        self.siguiente_id += 1
        mensaje = {"jsonrpc": "2.0", "id": id_, "method": metodo}
        if params is not None:
            mensaje["params"] = params
        self.enviar(mensaje)
        respuesta = self.recibir()
        if respuesta.get("id") != id_:
            raise ValueError(f"id de respuesta {respuesta.get('id')} no coincide con {id_}")
        return respuesta

    def notificar(self, metodo, params=None):
        mensaje = {"jsonrpc": "2.0", "method": metodo}
        if params is not None:
            mensaje["params"] = params
        self.enviar(mensaje)

    def handshake(self):
        respuesta = self.llamar("initialize", {
            "protocolVersion": VERSION_PROTOCOLO,
            "capabilities": {},
            "clientInfo": {"name": "cliente_prueba", "version": "1.0.0"},
        })
        if "error" in respuesta:
            raise RuntimeError(f"initialize falló: {respuesta['error']}")
        self.notificar("notifications/initialized")
        return respuesta["result"]

    def cerrar(self):
        self.proceso.stdin.close()
        self.proceso.wait(timeout=5)


def imprimir_resultado(respuesta):
    """Muestra el texto de la herramienta de forma legible, separado de la traza cruda."""
    if "error" in respuesta:
        e = respuesta["error"]
        print(f"{ROJO}error {e['code']}: {e['message']} {e.get('data', '')}{FIN}")
        return
    result = respuesta["result"]
    if "content" in result:
        prefijo = f"{ROJO}[isError] " if result.get("isError") else ""
        for bloque in result["content"]:
            print(f"{prefijo}{bloque.get('text', '')}{FIN}")
    print()


def interactivo(cliente, herramientas):
    print(f"\n{GRIS}Comandos: <n> para invocar la herramienta n, 'ping', 'lista', 'salir'.{FIN}")
    while True:
        try:
            entrada = input("> ").strip()
        except EOFError:
            break
        if entrada in ("salir", "q", ""):
            break
        if entrada == "ping":
            cliente.llamar("ping")
            continue
        if entrada == "lista":
            for i, h in enumerate(herramientas, start=1):
                print(f"  {i}. {h['name']}")
            continue
        if not entrada.isdigit() or not 1 <= int(entrada) <= len(herramientas):
            print(f"{ROJO}no entendí '{entrada}'{FIN}")
            continue

        herramienta = herramientas[int(entrada) - 1]
        print(f"{GRIS}{herramienta['description']}{FIN}")
        argumentos = {}
        propiedades = herramienta["inputSchema"]["properties"]
        requeridos = herramienta["inputSchema"].get("required", [])
        for nombre, prop in propiedades.items():
            pista = " (opcional)" if nombre not in requeridos else ""
            valor = input(f"  {nombre}{pista} [{prop.get('description', '')}]: ").strip()
            if not valor:
                continue
            if prop.get("type") == "integer":
                try:
                    valor = int(valor)
                except ValueError:
                    print(f"{ROJO}{nombre} debe ser entero; lo mando como texto para ver el -32602{FIN}")
            argumentos[nombre] = valor
        imprimir_resultado(cliente.llamar("tools/call", {"name": herramienta["name"], "arguments": argumentos}))


def demo(cliente):
    """Invoca las seis herramientas de principio a fin, más tres casos de error."""
    # Tomo "hoy" del último reporte de la flota y no del reloj, para que la
    # demo funcione igual aunque la base se haya generado otro día.
    print(f"\n{GRIS}=== tools/call unidades_detenidas ==={FIN}")
    respuesta = cliente.llamar("tools/call", {"name": "unidades_detenidas", "arguments": {"minutos_minimos": 30}})
    imprimir_resultado(respuesta)
    hoy = date.fromisoformat(json.loads(respuesta["result"]["content"][0]["text"])["instante_consulta"][:10])
    ayer = hoy - timedelta(days=1)
    hace_una_semana = hoy - timedelta(days=6)

    pasos = [
        ("ping", None),
        ("tools/call", {"name": "posicion_actual", "arguments": {"placa": "P-123BCD"}}),
        ("tools/call", {"name": "resumen_recorrido", "arguments": {"placa": "P-456DEF", "fecha": str(ayer)}}),
        ("tools/call", {"name": "alertas", "arguments": {"tipo": "exceso_velocidad", "fecha_inicio": str(hace_una_semana), "fecha_fin": str(hoy)}}),
        ("tools/call", {"name": "verificar_geocerca", "arguments": {"placa": "P-456DEF", "nombre_geocerca": "CEDIS Zona 12", "fecha": str(ayer)}}),
        ("tools/call", {"name": "reporte_kilometraje", "arguments": {"fecha_inicio": str(hace_una_semana), "fecha_fin": str(hoy)}}),
        ("tools/call", {"name": "posicion_actual", "arguments": {"placa": "P-000XXX"}}),
        ("tools/call", {"name": "posicion_actual", "arguments": {}}),
        ("metodo/inexistente", None),
    ]
    for metodo, params in pasos:
        print(f"\n{GRIS}=== {metodo} {params['name'] if params else ''} ==={FIN}")
        imprimir_resultado(cliente.llamar(metodo, params))


def main():
    comando = [sys.executable, "-m", "servidor.main"]
    cliente = Cliente(comando)
    try:
        info = cliente.handshake()
        print(f"{GRIS}conectado a {info['serverInfo']['name']} {info['serverInfo']['version']}, "
              f"protocolo {info['protocolVersion']}{FIN}")
        herramientas = cliente.llamar("tools/list")["result"]["tools"]
        print(f"{GRIS}{len(herramientas)} herramientas disponibles{FIN}")
        if "--demo" in sys.argv:
            demo(cliente)
        else:
            interactivo(cliente, herramientas)
    finally:
        cliente.cerrar()


if __name__ == "__main__":
    main()
