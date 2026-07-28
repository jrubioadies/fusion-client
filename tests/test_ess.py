"""Tests de ess.py — parseo SOAP y clasificación de estados, sin red."""
import pytest

from fusion_client import ess


def fake_transport(status, text):
    def t(url, body, user, pw, timeout):
        return status, text
    return t


SUBMIT_OK = """<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope">
<env:Body><ns:submitESSJobRequestResponse><result>300100123456789</result>
</ns:submitESSJobRequestResponse></env:Body></env:Envelope>"""

STATUS_OK = """<env:Envelope><env:Body><ns:getESSJobStatusResponse>
<result>SUCCEEDED</result></ns:getESSJobStatusResponse></env:Body></env:Envelope>"""

FAULT = """<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope">
<env:Body><env:Fault><env:Reason><env:Text xml:lang="en">
ORA-20001: Job package not found</env:Text></env:Reason></env:Fault>
</env:Body></env:Envelope>"""


def test_submit_returns_request_id():
    rid = ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", ["1", "Jul-26"],
                             transport=fake_transport(200, SUBMIT_OK))
    assert rid == "300100123456789"


def test_submit_params_are_escaped_in_body():
    captured = {}

    def t(url, body, user, pw, timeout):
        captured["body"] = body
        return 200, SUBMIT_OK
    ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", ["a<b>&c"], transport=t)
    assert "a&lt;b&gt;&amp;c" in captured["body"]
    assert "<a<b>" not in captured["body"]


def test_submit_surfaces_ora_fault():
    with pytest.raises(RuntimeError) as e:
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(500, FAULT))
    assert "ORA-20001" in str(e.value)


def test_submit_401():
    with pytest.raises(RuntimeError) as e:
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(401, ""))
    assert "401" in str(e.value)


def test_get_status_parses_result():
    st = ess.get_job_status("https://x", "u", "p", "300", transport=fake_transport(200, STATUS_OK))
    assert st == "SUCCEEDED"


# Respuestas REALES de la instancia (SOAP 1.1, MTOM): el elemento <result>
# llega con un atributo xmlns por delante. El parser debe admitirlo.
NS_T = "http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/types/"
SUBMIT_REAL = (
    '<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"><env:Body>'
    f'<ns0:submitESSJobRequestResponse xmlns:ns0="{NS_T}">'
    f'<result xmlns="{NS_T}">29369204</result>'
    '</ns0:submitESSJobRequestResponse></env:Body></env:Envelope>'
)
STATUS_REAL = (
    '<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"><env:Body>'
    f'<ns0:getESSJobStatusResponse xmlns:ns0="{NS_T}">'
    f'<result xmlns="{NS_T}">SUCCEEDED</result>'
    '</ns0:getESSJobStatusResponse></env:Body></env:Envelope>'
)


def test_submit_parses_result_with_xmlns_attr():
    rid = ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", ["1"],
                             transport=fake_transport(200, SUBMIT_REAL))
    assert rid == "29369204"


def test_status_parses_result_with_xmlns_attr():
    st = ess.get_job_status("https://x", "u", "p", "29369204",
                            transport=fake_transport(200, STATUS_REAL))
    assert st == "SUCCEEDED"


def test_envelope_uses_soap11():
    body = ess._envelope("<x/>")
    assert "http://schemas.xmlsoap.org/soap/envelope/" in body
    assert "www.w3.org/2003/05/soap-envelope" not in body  # no SOAP 1.2


@pytest.mark.parametrize("raw,cat", [
    ("SUCCEEDED", "ok"), ("WARNING", "warn"), ("ERROR", "error"),
    ("RUNNING", "running"), ("WAIT", "running"), ("CANCELLED", "error"),
    ("SOMETHING_NEW", "running"),
])
def test_classify_status(raw, cat):
    assert ess.classify_status(raw) == cat


def test_is_terminal():
    assert ess.is_terminal("SUCCEEDED")
    assert ess.is_terminal("ERROR")
    assert not ess.is_terminal("RUNNING")
