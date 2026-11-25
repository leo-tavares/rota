"""Ensaios locais. Executar com python -B work/check_relay.py."""
import copy
import gzip
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "outputs"))
import relay as r


class Echo(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def echo(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        result = dict(method=self.command, url=self.path, auth=self.headers.get("Authorization"),
                      tags=self.headers.get_all("X-Tag"), body=body.hex(),
                      type=self.headers.get("Content-Type"), host=self.headers.get("Host"))
        payload = json.dumps(result).encode()
        content_type = "application/json; charset=utf-8"
        if self.path == "/table":
            content_type = "text/csv; header=present"
            payload = b'id,name\r\n1,"Ana, M."\r\n'
        if self.path == "/slow":
            time.sleep(0.4)
        if self.path == "/big":
            payload = b"x" * (r.PREVIEW_LIMIT+27)
        if self.path == "/gzip":
            payload = gzip.compress(payload)
        self.send_response(307 if self.path == "/redirect" else (401 if self.path == "/private" else 200))
        if self.path == "/redirect":
            self.send_header("Location", "/health")
        if self.path == "/gzip":
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(0 if self.command == "CONNECT" else len(payload)))
        self.send_header("X-Multi", "1")
        self.send_header("X-Multi", "2")
        self.end_headers()
        if self.command not in ("HEAD", "CONNECT"):
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass


for verb in (*r.METHODS, "PROPFIND"):
    setattr(Echo, "do_" + verb, Echo.echo)


class Server(ThreadingHTTPServer):
    def handle_error(self, request, address):
        pass


def start(secure, temp):
    server = Server(("127.0.0.1", 0), Echo)
    if secure:
        exe = Path("C:/Program Files/Git/ucrt64/bin/openssl.exe")
        cert, key = temp/"cert.pem", temp/"key.pem"
        subprocess.run([str(exe), "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "1", "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
                        "-config", str(Path("C:/Program Files/Git/usr/ssl/openssl.cnf")),
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def require_error(fn, contains):
    try:
        fn()
    except ValueError as exc:
        assert contains in str(exc), exc
    else:
        raise AssertionError(contains)


def core(temp, http, https):
    s = r.initial_state()
    collection, request = r.path_for(s, s["selected"])
    folder = r.make_node("folder", "serviços")
    sub = r.make_node("folder", "v1")
    collection["children"] = [folder]
    folder["children"].append(sub)
    sub["children"].append(request)
    path = r.path_for(s, request["id"])
    env = s["environments"][0]
    env["variables"] = [dict(key="host", value="127.0.0.1", secret=False),
                        dict(key="base_url", value=f"http://{{{{host}}}}:{http.server_port}", secret=False),
                        dict(key="secret", value="sample-value", secret=True)]
    collection["auth"] = dict(mode="basic", username="user", password="pwd")
    folder["auth"] = dict(mode="bearer", token="{{secret}}")
    sub["env"] = env["id"]
    request.update(params=[r.row("k", "a b"), r.row("k", "á"), r.row("omit", "{{missing}}", False)],
                   headers=[r.row("X-Tag", "alpha"), r.row("X-Tag", "beta")],
                   url="{{base_url}}/saúde?x=1#fragment")

    def run():
        reply = r.perform(r.prepare(s, path), r.Job())
        assert not reply.error, reply
        return reply

    for verb in (*r.METHODS, "PROPFIND"):
        request["method"] = verb
        rep = run()
        assert rep.status == 200
        assert len([k for k, v in rep.headers if k == "X-Multi"]) == 2
        if verb in ("HEAD", "CONNECT"):
            assert not rep.data
        else:
            view = json.loads(r.render_body(rep))
            assert view["method"] == verb and view["tags"] == ["alpha", "beta"]
            assert view["auth"] == "Bearer sample-value"
            assert view["url"] == "/sa%C3%BAde?x=1&k=a+b&k=%C3%A1"
    request.update(method="POST", body_kind="json", body='{"segredo":"{{secret}}"}')
    result = json.loads(run().data)
    assert bytes.fromhex(result["body"]).decode() == '{"segredo":"sample-value"}'
    request.update(body_kind="form", form=[r.row("n", "a b")])
    assert bytes.fromhex(json.loads(run().data)["body"]) == b"n=a+b"
    file = temp/"blob.bin"
    file.write_bytes(b"\xfe" * 80000)
    request.update(body_kind="file", file=str(file))
    assert bytes.fromhex(json.loads(run().data)["body"]) == file.read_bytes()
    request.update(body_kind="text", body="Olá {{host}}")
    assert bytes.fromhex(json.loads(run().data)["body"]).decode() == "Olá 127.0.0.1"
    request.update(method="GET", body_kind="none", body="", params=[])
    sub["auth"] = {"mode":"none"}
    assert json.loads(run().data)["auth"] is None
    sub["auth"] = {"mode":"inherit"}
    folder["auth"] = {"mode":"inherit"}
    assert json.loads(run().data)["auth"] == "Basic dXNlcjpwd2Q="
    folder["auth"] = dict(mode="bearer", token="{{secret}}")
    request["headers"].append(r.row("Authorization", "manual"))
    assert json.loads(run().data)["auth"] == "manual"
    request["headers"].pop()
    for url, code in (("/gzip",200),("/private",401),("/redirect",307),("/big",200)):
        request["url"] = "{{base_url}}" + url
        rep = run()
        assert rep.status == code
        if url == "/big":
            assert rep.truncated and len(rep.data) == r.PREVIEW_LIMIT
        if url == "/gzip":
            assert json.loads(r.render_body(rep))["url"] == url
    request["url"] = f"https://127.0.0.1:{https.server_port}/tls"
    assert "CERTIFICATE_VERIFY_FAILED" in r.perform(r.prepare(s, path), r.Job()).error
    with patch.dict(os.environ, {"SSL_CERT_FILE":str(temp/"cert.pem")}):
        assert json.loads(run().data)["url"] == "/tls"
    request["url"] = "{{base_url}}/health"
    print("OK HTTP e HTTPS, verificação TLS, 9 métodos e PROPFIND, autenticações, corpos, status, gzip e limite")

    for selection in (path, path[:2], path[:1]):
        pkg = r.share_package(s, path=selection)
        assert "sample-value" not in json.dumps(pkg)
        assert str(file) not in str(pkg)
        complete = r.share_package(s, path=selection, secrets=True)
        dest = r.initial_state()
        r.import_package(dest, complete, r.path_for(dest, dest["selected"]))
        dest_request = [p for n, p in r.walk(dest["roots"]) if n["kind"] == "request"][-1]
        compiled = r.prepare(dest, dest_request)
        assert compiled.port == http.server_port and ("Authorization", "Bearer sample-value") in compiled.headers
        assert dest_request[-1]["id"] != request["id"] and dest_request[-1]["file"] == ""
        assert len(dest["environments"]) == 2 and dest["environments"][-1]["name"] == "Local (2)"
    only = r.share_package(s, environment=env)
    assert only["roots"] == [] and only["environments"][0]["variables"][-1]["value"] == ""
    orig = copy.deepcopy(s)
    bad = r.share_package(s, path=path)
    bad["roots"][0]["env"] = "missing-id"
    require_error(lambda: r.import_package(s, bad), "ambiente ausente")
    assert s == orig
    env["variables"].append(dict(key="loop", value="{{loop}}", secret=False))
    require_error(lambda: r.Variables(env).expand("{{loop}}"), "circular")
    require_error(lambda: r.Variables(env).expand("{{missing}}"), "ausente")
    print("OK coleções, subpastas, herança, portabilidade, sigilo, colisões e importação atômica")


def ui(temp, http):
    store = r.Workspace(temp/"data")
    require_error(lambda:r.Workspace(temp/"data"), "outra instância")
    root = tk.Tk()
    failures = []
    root.report_callback_exception = lambda t,e,tb: failures.append(e)
    app = r.App(root, store)
    root.update()
    for key in ("headers","body","auth","env","params"):
        app.set_page(key)
        root.update()
    orig = app.path[-1]
    app.url_entry.variable.set(f"http://127.0.0.1:{http.server_port}/ui")
    app.method_var.set("POST")
    app.set_page("body")
    orig["body_kind"] = "json"
    app.draw_editor()
    def descendants(w):
        for child in w.winfo_children():
            yield child
            yield from descendants(child)
    editor = next(w for w in descendants(app.editor) if isinstance(w, tk.Text))
    editor.insert("1.0",'{"from":"ui"}')
    root.update()
    app.send_button.invoke()
    limit = time.monotonic() + 6
    while app.jobs and time.monotonic() < limit:
        root.update()
        time.sleep(.02)
    reply = app.replies[orig["id"]]
    assert reply.status == 200 and bytes.fromhex(json.loads(reply.data)["body"]) == b'{"from":"ui"}'
    app.set_response_page("headers")
    root.update()
    names = [w for w in descendants(app.response) if isinstance(w, tk.Text)]
    assert "X-Multi: 1\nX-Multi: 2" in names[0].get("1.0","end")
    app.set_response_page("body")
    app.url_entry.variable.set(f"http://127.0.0.1:{http.server_port}/table")
    app.send_button.invoke()
    limit = time.monotonic() + 6
    while app.jobs and time.monotonic() < limit:
        root.update()
        time.sleep(.02)
    grid = next(w for w in descendants(app.response) if isinstance(w,r.ttk.Treeview))
    assert grid.heading("c1","text") == "name"
    assert grid.item(grid.get_children()[0], "values") == ("1","Ana, M.")
    selector = next(w for w in descendants(app.response) if isinstance(w,r.ttk.Combobox))
    selector.current(list(r.VIEW_MODES).index("raw"))
    selector.event_generate("<<ComboboxSelected>>")
    root.update()
    raw_text = next(w for w in descendants(app.response) if isinstance(w,tk.Text))
    assert raw_text.get("1.0","end-1c") == 'id,name\r\n1,"Ana, M."\r\n'
    for mode in ("hex", "base64"):
        app.set_body_mode(mode)
        root.update()
        btn = next(w for w in descendants(app.response) if isinstance(w,r.ttk.Button) and w.cget("text") == "Copiar")
        btn.invoke()
        assert root.clipboard_get() == r.body_view(app.replies[app.selected],mode).text
    pixels = tk.PhotoImage(master=root,width=2,height=2)
    pixels.put("green",to=(0,0,2,2))
    image_path = temp/"pixels.png"
    pixels.write(str(image_path),format="png")
    png = r.Reply(status=200,headers=[("Content-Type","image/png")],data=image_path.read_bytes())
    app.remember(app.selected,png)
    app.draw_response()
    root.update()
    assert any(getattr(w,"image",None) is not None for w in descendants(app.response))
    xml = r.Reply(status=200,headers=[("Content-Type","application/xml")],data=b'<r><a>first</a><a>second</a></r>')
    app.remember(app.selected,xml)
    app.draw_response()
    grid = next(w for w in descendants(app.response) if isinstance(w,r.ttk.Treeview))
    assert grid.item("4","text") == "a" and grid.parent("4") == "1"
    orig["url"] = f"http://127.0.0.1:{http.server_port}/slow"
    app.send()
    app.send()
    assert "cancelada" in app.replies[orig["id"]].error
    for typ, name in (("folder","Pasta A"), ("folder","Pasta B"), ("request","Nova")):
        with patch.object(r.simpledialog, "askstring", return_value=name):
            app.new(typ)
        root.update()
    assert [n["name"] for n in app.path] == ["Minha coleção","Pasta A","Pasta B","Nova"]
    with patch.object(r.simpledialog,"askstring", return_value="Renomeada"):
        app.rename()
    app.path[-1]["auth"] = dict(mode="bearer",token="test-local-secret")
    app.export_selected()
    root.update()
    modal = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
    out = temp/"req.relay.json"
    with patch.object(r.filedialog,"asksaveasfilename",return_value=str(out)):
        next(w for w in descendants(modal) if isinstance(w,r.ttk.Button) and w.cget("text") == "Salvar arquivo…").invoke()
    assert r.read_json(out)["roots"][0]["auth"] == {"mode":"bearer", "token":""}
    assert "test-local-secret" not in out.read_text()
    app.search.set("Renomeada")
    root.update()
    assert app.tree.exists(app.selected) and not app.tree.exists(orig["id"])
    app.search.set("")
    app.environments()
    root.update()
    assert app.env_window.winfo_exists()
    app.env_window.event_generate("<Escape>")
    root.update()
    if app.env_window.winfo_exists():
        app.env_window.tk.call(app.env_window.protocol("WM_DELETE_WINDOW"))
    env = app.state["environments"][0]
    shared = temp/"env.relay.json"
    r.write_json(shared, r.share_package(app.state, environment=env))
    with patch.object(r.filedialog, "askopenfilename",return_value=str(shared)):
        app.import_file()
    root.update()
    assert len(app.state["environments"]) == 2
    app.env_window.tk.call(app.env_window.protocol("WM_DELETE_WINDOW"))
    selected = app.selected
    app.close()
    assert "test-local-secret" not in store.path.read_text()
    stored = r.Workspace(temp/"data")
    assert r.path_for(stored.state, selected)[-1]["name"] == "Renomeada"
    assert r.path_for(stored.state, selected)[-1]["auth"]["token"] == "test-local-secret"
    stored.close()
    assert not failures, failures
    print("OK Tk, envio pelo botão, cancelamento, editor JSON, organização, busca, ambientes, persistência e trava de instância")


with tempfile.TemporaryDirectory(dir=BASE/"work") as tmp:
    temp = Path(tmp)
    http, https = start(False,temp), start(True,temp)
    try:
        core(temp, http, https)
        ui(temp, http)
    finally:
        for server in (http, https):
            server.shutdown()
            server.server_close()
