#!/usr/bin/env python3
"""
ess.py — Cliente SOAP del Oracle Fusion ERP Integration Service.

Es el ÚNICO módulo que provoca acciones (escrituras) en Fusion. Envía
procesos programados (ESS jobs) con `submitESSJobRequest` y consulta su
estado con `getESSJobStatus`, sobre el endpoint:

    {base}/fscmService/ErpIntegrationService

Frontera de diseño: `fbip.py` sólo lee; `ess.py` sólo actúa. Toda la lógica
de negocio (qué job, en qué orden) vive en `closer.py`, no aquí.

El transporte HTTP es INYECTABLE (`transport=`) para poder testear sin red:
una función `transport(url, body, user, pw, timeout) -> (status_code, text)`.
"""
import re
import base64
import requests

NS_TYP = "http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/types/"
NS_ERP = "http://xmlns.oracle.com/apps/financials/commonModules/shared/model/erpIntegrationService/"

# Estados ESS normalizados a categorías de resultado.
STATUS_DONE_OK = {"SUCCEEDED"}
STATUS_DONE_WARN = {"WARNING"}
STATUS_DONE_ERR = {"ERROR", "CANCELLED", "ERROR_MANUAL_RECOVERY", "EXPIRED",
                   "VALIDATION_FAILED", "SCHEDULE_ENDED", "FINISHED_WITH_ERROR"}
STATUS_RUNNING = {"WAIT", "READY", "RUNNING", "COMPLETED", "PAUSED",
                  "PENDING_VALIDATION", "BLOCKED", "HOLD"}


def endpoint(base):
    return f"{base.rstrip('/')}/fscmService/ErpIntegrationService"


def _default_transport(url, body, user, pw, timeout):
    """POST SOAP real. Devuelve (status_code, text).

    El ErpIntegrationService exige SOAP 1.1: Content-Type text/xml y cabecera
    SOAPAction (vacía vale). Con application/soap+xml (SOAP 1.2) devuelve
    HTTP 500 'soap version soap1.1 is not compatable with Content type
    application/soap+xml'.
    """
    r = requests.post(
        url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
        auth=(user, pw),
        timeout=timeout,
    )
    return r.status_code, r.text


def _envelope(inner):
    # SOAP 1.1 (schemas.xmlsoap.org); el servicio rechaza el envelope 1.2.
    return (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:typ="{NS_TYP}">'
        "<soapenv:Header/><soapenv:Body>"
        f"{inner}"
        "</soapenv:Body></soapenv:Envelope>"
    )


def _fault_text(text):
    """Extrae el mensaje de fault de Oracle (SOAP 1.2 Reason/Text, 1.1
    faultstring, o líneas ORA-)."""
    m = (re.search(r"<(?:\w+:)?Text[^>]*>(.*?)</(?:\w+:)?Text>", text, re.S)
         or re.search(r"<faultstring>(.*?)</faultstring>", text, re.S))
    msg = m.group(1).strip() if m else text[:800]
    ora = re.findall(r"(ORA-\d+[^\n<]*)", msg)
    if ora:
        return "\n".join(dict.fromkeys(ora))
    return msg


def _check(status, text):
    if status == 401:
        raise RuntimeError("401 No autorizado — usuario o contraseña incorrectos.")
    if status >= 400:
        raise RuntimeError(f"Error ERP Integration (HTTP {status}):\n{_fault_text(text)}")


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def submit_ess_job(base, user, pw, job_package, job_definition, params=None,
                   timeout=120, transport=None):
    """Envía un ESS job. Devuelve el requestId (str).

    job_package: p. ej. "/oracle/apps/ess/financials/payables/.../PeriodClose"
    job_definition: nombre de la definición del job.
    params: lista de valores posicionales (str) para el job.
    """
    transport = transport or _default_transport
    params = params or []
    param_xml = "".join(f"<typ:paramList>{_esc(p)}</typ:paramList>" for p in params)
    inner = (
        "<typ:submitESSJobRequest>"
        f"<typ:jobPackageName>{_esc(job_package)}</typ:jobPackageName>"
        f"<typ:jobDefinitionName>{_esc(job_definition)}</typ:jobDefinitionName>"
        f"{param_xml}"
        "</typ:submitESSJobRequest>"
    )
    status, text = transport(endpoint(base), _envelope(inner), user, pw, timeout)
    _check(status, text)
    m = re.search(r"<(?:\w+:)?result(?:\s[^>]*)?>(.*?)</(?:\w+:)?result>", text, re.S)
    if not m:
        raise RuntimeError("submitESSJobRequest no devolvió requestId:\n" + text[:600])
    rid = m.group(1).strip()
    if not re.fullmatch(r"-?\d+", rid):
        raise RuntimeError(f"requestId inesperado: {rid!r}\n{text[:400]}")
    return rid


def get_job_status(base, user, pw, request_id, timeout=60, transport=None):
    """Consulta el estado de un ESS job. Devuelve el estado crudo (str),
    p. ej. 'RUNNING', 'SUCCEEDED', 'ERROR'."""
    transport = transport or _default_transport
    inner = (
        "<typ:getESSJobStatus>"
        f"<typ:requestId>{_esc(request_id)}</typ:requestId>"
        "</typ:getESSJobStatus>"
    )
    status, text = transport(endpoint(base), _envelope(inner), user, pw, timeout)
    _check(status, text)
    m = re.search(r"<(?:\w+:)?result(?:\s[^>]*)?>(.*?)</(?:\w+:)?result>", text, re.S)
    if not m:
        raise RuntimeError("getESSJobStatus sin result:\n" + text[:600])
    return m.group(1).strip().upper()


def classify_status(raw_status):
    """Normaliza un estado ESS a: 'ok' | 'warn' | 'error' | 'running'."""
    s = (raw_status or "").upper()
    if s in STATUS_DONE_OK:
        return "ok"
    if s in STATUS_DONE_WARN:
        return "warn"
    if s in STATUS_DONE_ERR:
        return "error"
    if s in STATUS_RUNNING:
        return "running"
    # Desconocido → lo tratamos como running para no dar por bueno un cierre.
    return "running"


def is_terminal(raw_status):
    return classify_status(raw_status) in ("ok", "warn", "error")
