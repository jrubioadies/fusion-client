#!/usr/bin/env python3
"""
fbip - Oracle Fusion BI Publisher CLI (Linux)

A small client for Oracle Fusion Cloud Applications that runs BI Publisher
data models / reports over the ExternalReportWSSService SOAP endpoint and
returns the data locally (CSV / XML / raw). This is the same mechanism
desktop tools like Pi Cube use under the hood, but scriptable from Linux.

Oracle Fusion SaaS does NOT expose the underlying DB directly (no JDBC).
The supported way to "run SQL" is: create a Data Model with your SQL in
BI Publisher (/xmlpserver), put a report on it, then run it here.

Config resolution order for credentials:
  1. CLI flags --base/--user/--pass
  2. Env: FUSION_BASE, FUSION_USER, FUSION_PASS
  3. ~/.config/fusion-bip/config.json  {"base","user","pass"}

Commands:
  test                 Verify connectivity + auth
  ls [PATH]            List a catalog folder (default "/")
  params REPORT_PATH   Show a report's parameters
  run REPORT_PATH      Run a report and save/print the output
"""
import argparse, base64, json, os, sys, re
from pathlib import Path
import requests
from xml.sax.saxutils import escape

from .errors import (
    FusionAuthError,
    FusionBIPError,
    FusionSQLError,
    FusionTooLongError,
)

NS = "http://xmlns.oracle.com/oxp/service/PublicReportService"
CFG = Path.home() / ".config" / "fusion-bip" / "config.json"


def load_creds(args):
    base = args.base or os.environ.get("FUSION_BASE")
    user = args.user or os.environ.get("FUSION_USER")
    pw = getattr(args, "pw", None) or os.environ.get("FUSION_PASS")
    if (not base or not user or not pw) and CFG.exists():
        c = json.loads(CFG.read_text())
        base = base or c.get("base")
        user = user or c.get("user")
        pw = pw or c.get("pass")
    if not (base and user and pw):
        sys.exit("Missing credentials. Use --base/--user/--pass, env vars, "
                 "or run: fbip save-creds")
    return base.rstrip("/"), user, pw


def endpoint(base):
    return f"{base}/xmlpserver/services/ExternalReportWSSService"


def soap_call(base, user, pw, body_inner, timeout=120):
    env = (
        '<soapenv:Envelope xmlns:soapenv="http://www.w3.org/2003/05/soap-envelope" '
        f'xmlns:pub="{NS}">'
        "<soapenv:Header/><soapenv:Body>"
        f"{body_inner}"
        "</soapenv:Body></soapenv:Envelope>"
    )
    r = requests.post(
        endpoint(base),
        data=env.encode("utf-8"),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        auth=(user, pw),
        timeout=timeout,
    )
    if r.status_code == 401:
        raise FusionAuthError("401 Unauthorized - usuario o contraseña incorrectos.")
    if r.status_code >= 400:
        # surface SOAP fault text (SOAP 1.2 Reason/Text, or 1.1 faultstring)
        fault = (re.search(r"<(?:\w+:)?Text[^>]*>(.*?)</(?:\w+:)?Text>", r.text, re.S)
                 or re.search(r"<faultstring>(.*?)</faultstring>", r.text, re.S))
        msg = fault.group(1).strip() if fault else r.text[:2000]
        # If it's a SQL error, surface the ORA-/error line(s) up front.
        ora = re.findall(r"(ORA-\d+[^\n]*)", msg)
        sqlerr = re.search(r"java\.sql\.\w+:\s*(.*)", msg, re.S)
        if ora:
            head = "\n".join(dict.fromkeys(ora))  # dedupe, keep order
            raise FusionSQLError(f"SQL error:\n{head}\n\n--- full ---\n{msg}")
        if sqlerr:
            raise FusionSQLError(f"SQL error:\n{sqlerr.group(1).strip()[:400]}\n\n--- full ---\n{msg}")
        raise FusionBIPError(f"BI Publisher error (HTTP {r.status_code}):\n{msg}")
    return r.text


def cmd_test(args):
    base, user, pw = load_creds(args)
    body = "<pub:getFolderContents><pub:folderAbsolutePath>/</pub:folderAbsolutePath></pub:getFolderContents>"
    xml = soap_call(base, user, pw, body)
    ok = "getFolderContentsReturn" in xml or "<absolutePath" in xml
    print(f"Endpoint : {endpoint(base)}")
    print(f"User     : {user}")
    print("Auth     : OK" if ok else "Auth     : responded but unexpected body")
    if not ok:
        print(xml[:600])


def _tag(block, name):
    m = re.search(r"<(?:\w+:)?%s>(.*?)</(?:\w+:)?%s>" % (name, name), block, re.S)
    return m.group(1) if m else ""


def _folder_items(xml):
    # <...catalogContents> holds repeated <...item> entries
    items = []
    for block in re.findall(r"<(?:\w+:)?item>(.*?)</(?:\w+:)?item>", xml, re.S):
        items.append({
            "path": _tag(block, "absolutePath"),
            "type": _tag(block, "type"),        # "Folder" or "Report"
            "name": _tag(block, "displayName"),
        })
    return items


def cmd_ls(args):
    base, user, pw = load_creds(args)
    path = args.path or "/"
    body = f"<pub:getFolderContents><pub:folderAbsolutePath>{escape(path)}</pub:folderAbsolutePath></pub:getFolderContents>"
    xml = soap_call(base, user, pw, body)
    items = _folder_items(xml)
    if not items:
        print(f"(empty or no access) {path}")
        return
    for it in sorted(items, key=lambda x: (x["type"].lower() != "folder", x["path"])):
        tag = "DIR " if it["type"].lower() == "folder" else "RPT "
        print(f"{tag}{it['path']}")


def cmd_params(args):
    base, user, pw = load_creds(args)
    body = ("<pub:getReportParameters><pub:reportRequest>"
            f"<pub:reportAbsolutePath>{escape(args.report)}</pub:reportAbsolutePath>"
            "</pub:reportRequest></pub:getReportParameters>")
    xml = soap_call(base, user, pw, body)
    names = re.findall(r"<(?:\w+:)?name>(.*?)</(?:\w+:)?name>", xml, re.S)
    labels = re.findall(r"<(?:\w+:)?label>(.*?)</(?:\w+:)?label>", xml, re.S)
    if not names:
        print("(no parameters)")
        return
    for i, n in enumerate(names):
        lbl = labels[i] if i < len(labels) else ""
        print(f"{n}\t{lbl}")


def cmd_run(args):
    base, user, pw = load_creds(args)
    pnv = ""
    for kv in args.param or []:
        k, _, v = kv.partition("=")
        pnv += (f"<pub:item><pub:name>{escape(k)}</pub:name>"
                f"<pub:values><pub:item>{escape(v)}</pub:item></pub:values></pub:item>")
    params_xml = f"<pub:parameterNameValues>{pnv}</pub:parameterNameValues>" if pnv else ""
    tmpl = f"<pub:attributeTemplate>{escape(args.template)}</pub:attributeTemplate>" if args.template else ""
    body = (
        "<pub:runReport><pub:reportRequest>"
        f"<pub:attributeFormat>{escape(args.format)}</pub:attributeFormat>"
        f"{tmpl}"
        f"<pub:reportAbsolutePath>{escape(args.report)}</pub:reportAbsolutePath>"
        "<pub:sizeOfDataChunkDownload>-1</pub:sizeOfDataChunkDownload>"
        f"{params_xml}"
        "</pub:reportRequest></pub:runReport>"
    )
    xml = soap_call(base, user, pw, body, timeout=args.timeout)
    m = re.search(r"<(?:\w+:)?reportBytes>(.*?)</(?:\w+:)?reportBytes>", xml, re.S)
    if not m:
        sys.exit("No reportBytes in response:\n" + xml[:800])
    data = base64.b64decode(m.group(1))
    if args.out:
        Path(args.out).write_bytes(data)
        print(f"Wrote {len(data)} bytes -> {args.out}")
    else:
        sys.stdout.buffer.write(data)


SQL_REPORT_DEFAULT = "/Custom/SQLTools/SQLConReport.xdo"


def _sql_params_xml(sql):
    """Split raw SQL into <=8 chunks, base64 each -> query1..query8.
    The SQLConDM data model base64-decodes each param separately then
    concatenates, so we split the RAW sql and encode each piece."""
    raw = sql.encode("utf-8")
    MAX = 24000  # per-chunk raw bytes (base64 stays < RAW(32767))
    chunks = [raw[i:i + MAX] for i in range(0, len(raw), MAX)] or [b""]
    if len(chunks) > 8:
        raise FusionTooLongError(
            "El SQL supera los 192 KB que admite el data model. Divídelo o redúcelo."
        )
    pnv = ""
    for idx in range(8):
        val = base64.b64encode(chunks[idx]).decode() if idx < len(chunks) else ""
        pnv += (f"<pub:item><pub:name>query{idx+1}</pub:name>"
                f"<pub:values><pub:item>{val}</pub:item></pub:values></pub:item>")
    return f"<pub:parameterNameValues>{pnv}</pub:parameterNameValues>"


def run_sql(base, user, pw, report_path, sql, timeout=300):
    body = (
        "<pub:runReport><pub:reportRequest>"
        "<pub:attributeFormat>xml</pub:attributeFormat>"
        f"<pub:reportAbsolutePath>{escape(report_path)}</pub:reportAbsolutePath>"
        "<pub:sizeOfDataChunkDownload>-1</pub:sizeOfDataChunkDownload>"
        f"{_sql_params_xml(sql)}"
        "</pub:reportRequest></pub:runReport>"
    )
    xml = soap_call(base, user, pw, body, timeout=timeout)
    m = re.search(r"<(?:\w+:)?reportBytes>(.*?)</(?:\w+:)?reportBytes>", xml, re.S)
    if not m:
        raise FusionBIPError("No reportBytes in response: " + xml[:800])
    return base64.b64decode(m.group(1))


def parse_rows(data_xml):
    """Parse BIP data XML into (columns, rows). Rows are the repeated
    element under the DATA_DS root; columns are their child tags."""
    import xml.etree.ElementTree as ET
    def strip_ns(t): return t.rsplit("}", 1)[-1]
    root = ET.fromstring(data_xml)
    rows_el = list(root)
    columns, rows = [], []
    for r in rows_el:
        row = {}
        for c in r:
            col = strip_ns(c.tag)
            if col not in columns:
                columns.append(col)
            row[col] = (c.text or "")
        if row:
            rows.append(row)
    return columns, rows


def resolve_report(args, conf):
    """Pick the executor report path: --report > --ds (datasources map) > config default."""
    if getattr(args, "report", None):
        return args.report
    ds_map = conf.get("datasources", {})
    if getattr(args, "ds", None):
        # match by key (case-insensitive substring, e.g. "fscm" / "hcm")
        for k, v in ds_map.items():
            if args.ds.lower() in k.lower():
                return v
        sys.exit(f"Unknown datasource '{args.ds}'. Options: {list(ds_map)}")
    if conf.get("default_ds") and conf["default_ds"] in ds_map:
        return ds_map[conf["default_ds"]]
    return conf.get("sql_report") or SQL_REPORT_DEFAULT


def cmd_sql(args):
    base, user, pw = load_creds(args)
    conf = json.loads(CFG.read_text()) if CFG.exists() else {}
    report = resolve_report(args, conf)
    sql = args.query
    if args.file:
        sql = Path(args.file).read_text()
    if not sql:
        sql = sys.stdin.read()
    data = run_sql(base, user, pw, report, sql, timeout=args.timeout)
    if args.raw:
        sys.stdout.buffer.write(data)
        return
    cols, rows = parse_rows(data)
    import csv as _csv
    w = _csv.writer(sys.stdout)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    print(f"\n({len(rows)} rows)", file=sys.stderr)


def _build_sql_report_zip():
    """Build a minimal BIP report (.xdo) zip bound to SQLConDM, XML output."""
    import io, zipfile
    report_xdo = (
        "<?xml version = '1.0' encoding = 'utf-8'?>\n"
        '<report xmlns="http://xmlns.oracle.com/oxp/xmlp" '
        'xmlns:xsd="http://wwww.w3.org/2001/XMLSchema" version="2.0" '
        'dataModel="true" useBipParameters="true">\n'
        '   <dataModel url="/Custom/SQLTools/SQLConDM.xdm"/>\n'
        "   <description/>\n"
        '   <property name="online" value="true"/>\n'
        '   <property name="autoRun" value="false"/>\n'
        '   <property name="asynchronousRun" value="false"/>\n'
        '   <property name="saveXMLForRepublishing" value="true"/>\n'
        "   <templates/>\n"
        "</report>\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_report.xdo", report_xdo)
        z.writestr("xdo.cfg", "<config xmlns=\"http://xmlns.oracle.com/oxp/config/\"/>\n")
    return buf.getvalue()


def cmd_setup(args):
    """Create the SQL executor report on top of SQLConDM.xdm (writes to catalog)."""
    base, user, pw = load_creds(args)
    path = args.path or SQL_REPORT_DEFAULT
    folder, _, name = path.rpartition("/")
    name = name[:-4] if name.endswith(".xdo") else name
    zipped = base64.b64encode(_build_sql_report_zip()).decode()
    body = (
        "<pub:uploadReportObject>"
        f"<pub:reportObjectAbsolutePathURL>{escape(path)}</pub:reportObjectAbsolutePathURL>"
        "<pub:objectType>xdoz</pub:objectType>"
        f"<pub:objectZippedData>{zipped}</pub:objectZippedData>"
        "</pub:uploadReportObject>"
    )
    xml = soap_call(base, user, pw, body)
    print("Setup response:", xml[:500])


def cmd_save_creds(args):
    base = args.base or input("Base URL (https://host): ").strip()
    user = args.user or input("User: ").strip()
    pw = getattr(args, "pw", None) or input("Password: ").strip()
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps({"base": base.rstrip("/"), "user": user, "pass": pw}, indent=2))
    os.chmod(CFG, 0o600)
    print(f"Saved -> {CFG} (chmod 600)")


def main():
    p = argparse.ArgumentParser(prog="fbip", description="Oracle Fusion BI Publisher CLI")
    p.add_argument("--base"); p.add_argument("--user"); p.add_argument("--pass", dest="pw")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("test").set_defaults(func=cmd_test)
    sp = sub.add_parser("ls"); sp.add_argument("path", nargs="?"); sp.set_defaults(func=cmd_ls)
    sp = sub.add_parser("params"); sp.add_argument("report"); sp.set_defaults(func=cmd_params)
    sp = sub.add_parser("run")
    sp.add_argument("report")
    sp.add_argument("--format", default="csv", help="csv|xml|pdf|xlsx (default csv)")
    sp.add_argument("--template", help="layout/template name (required by some reports)")
    sp.add_argument("--param", action="append", help="name=value (repeatable)")
    sp.add_argument("-o", "--out", help="output file (default: stdout)")
    sp.add_argument("--timeout", type=int, default=300)
    sp.set_defaults(func=cmd_run)
    sp = sub.add_parser("sql", help="run ad-hoc SQL via the SQLConDM executor report")
    sp.add_argument("query", nargs="?")
    sp.add_argument("-f", "--file", help="read SQL from file")
    sp.add_argument("--report", help="executor report path (default from config)")
    sp.add_argument("--ds", help="datasource: fscm (Financials/SCM) or hcm (RRHH)")
    sp.add_argument("--raw", action="store_true", help="print raw XML instead of CSV")
    sp.add_argument("--timeout", type=int, default=300)
    sp.set_defaults(func=cmd_sql)
    sp = sub.add_parser("setup", help="create the SQL executor report (writes to catalog)")
    sp.add_argument("--path", help="report path (default /Custom/SQLTools/SQLConReport.xdo)")
    sp.set_defaults(func=cmd_setup)
    sub.add_parser("save-creds").set_defaults(func=cmd_save_creds)

    args = p.parse_args()
    try:
        args.func(args)
    except RuntimeError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
