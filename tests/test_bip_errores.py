"""La librería lanza excepciones; solo el CLI termina el proceso."""
import pytest

from fusion_client import bip
from fusion_client.errors import (
    FusionAuthError,
    FusionError,
    FusionSQLError,
    FusionTooLongError,
)


def test_sql_demasiado_largo_lanza_excepcion_no_sale():
    sql = "x" * (192 * 1024 + 1)
    with pytest.raises(FusionTooLongError):
        bip._sql_params_xml(sql)


def test_sql_demasiado_largo_no_lanza_systemexit():
    sql = "x" * (192 * 1024 + 1)
    try:
        bip._sql_params_xml(sql)
    except SystemExit:
        pytest.fail("la librería no debe llamar a sys.exit")
    except FusionTooLongError:
        pass


def test_401_lanza_auth_error(monkeypatch):
    class R:
        status_code = 401
        text = "Unauthorized"

    monkeypatch.setattr(bip.requests, "post", lambda *a, **k: R())
    with pytest.raises(FusionAuthError):
        bip.soap_call("https://x", "u", "p", "<body/>")


def test_error_sql_ora_lanza_fusion_sql_error(monkeypatch):
    class R:
        status_code = 500
        text = (
            "<soapenv:Envelope><soapenv:Body><soapenv:Fault>"
            "<faultstring>ORA-00942: table or view does not exist</faultstring>"
            "</soapenv:Fault></soapenv:Body></soapenv:Envelope>"
        )

    monkeypatch.setattr(bip.requests, "post", lambda *a, **k: R())
    with pytest.raises(FusionSQLError):
        bip.soap_call("https://x", "u", "p", "<body/>")


def test_los_errores_son_capturables_como_runtime_error():
    """Los 15 `except (RuntimeError, SystemExit)` de los proyectos
    consumidores dependen de esto. Si alguien cambia la herencia, este
    test lo cierra antes de que rompa las cuatro aplicaciones."""
    assert issubclass(FusionError, RuntimeError)
    for cls in (FusionAuthError, FusionSQLError, FusionTooLongError):
        assert issubclass(cls, RuntimeError)
