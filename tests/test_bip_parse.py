"""Tests de bip.parse_rows — sin red."""
from fusion_client import bip


DATA = """<?xml version="1.0"?>
<DATA_DS>
  <G_1><CLAVE>BUFIN-1</CLAVE><IMPORTE>100.5</IMPORTE></G_1>
  <G_1><CLAVE>BUFIN-2</CLAVE><IMPORTE>200</IMPORTE></G_1>
</DATA_DS>"""


def test_parse_rows_extrae_columnas_y_filas():
    columns, rows = bip.parse_rows(DATA)
    assert columns == ["CLAVE", "IMPORTE"]
    assert rows == [
        {"CLAVE": "BUFIN-1", "IMPORTE": "100.5"},
        {"CLAVE": "BUFIN-2", "IMPORTE": "200"},
    ]


def test_parse_rows_con_celda_vacia_devuelve_cadena_vacia():
    xml = "<DATA_DS><G_1><A></A><B>x</B></G_1></DATA_DS>"
    columns, rows = bip.parse_rows(xml)
    assert rows == [{"A": "", "B": "x"}]


def test_parse_rows_sin_filas_devuelve_listas_vacias():
    columns, rows = bip.parse_rows("<DATA_DS></DATA_DS>")
    assert columns == []
    assert rows == []
