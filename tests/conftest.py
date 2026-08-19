import os
import sqlite3
import sys
from datetime import datetime

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "datos"))

import generador  # noqa: E402

# Instante fijo para que los resultados sean reproducibles entre corridas.
AHORA = datetime(2026, 8, 19, 15, 30)
SEMILLA = 7


@pytest.fixture(scope="session")
def base(tmp_path_factory):
    """Genera el set sintético una sola vez por sesión y devuelve (ruta, plan de inyecciones)."""
    ruta = str(tmp_path_factory.mktemp("datos") / "flota.db")
    plan = generador.generar(ruta, AHORA, SEMILLA)
    return ruta, plan


@pytest.fixture
def db(base):
    conexion = sqlite3.connect(f"file:{base[0]}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row
    yield conexion
    conexion.close()


@pytest.fixture
def plan(base):
    return base[1]
