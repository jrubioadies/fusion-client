"""La librería lanza excepciones; solo el CLI termina el proceso."""
import base64

import pytest

from fusion_client import bip
from fusion_client.errors import (
    FusionAuthError,
    FusionBIPError,
    FusionError,
    FusionESSError,
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


def test_http_generico_lanza_fusion_bip_error(monkeypatch):
    """HTTP >= 400 cuyo fault no es ORA- ni java.sql: antes RuntimeError pelado."""
    class R:
        status_code = 503
        text = ("<soapenv:Envelope><soapenv:Body><soapenv:Fault>"
                "<faultstring>Service temporarily unavailable</faultstring>"
                "</soapenv:Fault></soapenv:Body></soapenv:Envelope>")

    monkeypatch.setattr(bip.requests, "post", lambda *a, **k: R())
    with pytest.raises(FusionBIPError) as e:
        bip.soap_call("https://x", "u", "p", "<body/>")
    assert "503" in str(e.value)
    assert "Service temporarily unavailable" in str(e.value)


def test_http_generico_no_se_confunde_con_error_sql(monkeypatch):
    """Un 500 con ORA- sigue siendo FusionSQLError, no FusionBIPError."""
    class R:
        status_code = 500
        text = "<faultstring>ORA-00904: invalid identifier</faultstring>"

    monkeypatch.setattr(bip.requests, "post", lambda *a, **k: R())
    with pytest.raises(FusionSQLError):
        bip.soap_call("https://x", "u", "p", "<body/>")


def test_run_sql_sin_report_bytes_lanza_fusion_bip_error(monkeypatch):
    """La ruta caliente de los cuatro consumidores: HTTP 200 pero el cuerpo
    no trae reportBytes. Antes salía como RuntimeError pelado."""
    class R:
        status_code = 200
        text = ("<env:Envelope><env:Body><runReportResponse>"
                "<runReportReturn></runReportReturn>"
                "</runReportResponse></env:Body></env:Envelope>")

    monkeypatch.setattr(bip.requests, "post", lambda *a, **k: R())
    with pytest.raises(FusionBIPError) as e:
        bip.run_sql("https://x", "u", "p", "/Custom/R.xdo", "select 1 from dual")
    assert "reportBytes" in str(e.value)


def test_run_sql_ok_devuelve_los_bytes_decodificados(monkeypatch):
    """Contraprueba del test anterior: con reportBytes, run_sql no lanza."""
    payload = base64.b64encode(b"<DATA_DS><R><N>1</N></R></DATA_DS>").decode()

    class R:
        status_code = 200
        text = f"<env:Body><reportBytes>{payload}</reportBytes></env:Body>"

    monkeypatch.setattr(bip.requests, "post", lambda *a, **k: R())
    data = bip.run_sql("https://x", "u", "p", "/Custom/R.xdo", "select 1 from dual")
    assert data == b"<DATA_DS><R><N>1</N></R></DATA_DS>"


def test_los_errores_son_capturables_como_runtime_error():
    """Los 15 `except (RuntimeError, SystemExit)` de los proyectos
    consumidores dependen de esto. Si alguien cambia la herencia, este
    test lo cierra antes de que rompa las cuatro aplicaciones."""
    assert issubclass(FusionError, RuntimeError)
    for cls in (FusionAuthError, FusionSQLError, FusionTooLongError,
                FusionBIPError, FusionESSError):
        assert issubclass(cls, RuntimeError)
        assert issubclass(cls, FusionError)


def test_ningun_modulo_lanza_runtime_error_pelado():
    """Contrato de la jerarquía: `raise RuntimeError(` no debe reaparecer en
    bip.py ni en ess.py. El único `except RuntimeError` legítimo es el de
    `main()`, que es CLI, no librería."""
    import pathlib
    src = pathlib.Path(bip.__file__).parent
    for name in ("bip.py", "ess.py"):
        texto = (src / name).read_text(encoding="utf-8")
        assert "raise RuntimeError(" not in texto, name
