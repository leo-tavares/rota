"""Valida a coleção importada pela interface; --live envia os dez exemplos ao DummyJSON."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "outputs"))
import relay


def check_response(request, reply):
    assert not reply.error, reply.error
    headers = {key.lower(): value for key, value in reply.headers}
    if request.method == "OPTIONS":
        assert reply.status in (200, 204)
        assert "PATCH" in headers["access-control-allow-methods"]
        return
    if request.method == "HEAD":
        assert reply.status == 200 and not reply.data and "content-type" in headers
        return
    body = json.loads(relay.body_view(reply).text)
    if request.target.endswith("/999999"):
        assert reply.status == 404 and body["message"]
    elif "?" in request.target:
        assert reply.status == 200 and 0 < len(body["products"]) <= 5
        assert {"id", "title", "price"} <= set(body["products"][0]) and body["total"] >= len(body["products"])
    elif request.method == "DELETE":
        assert reply.status == 200 and body["id"] == 1 and body["isDeleted"] is True and body["deletedOn"]
    elif request.body:
        assert reply.status in (200, 201) and body["id"] > 0
        if request.method != "POST":
            assert body["id"] == 1
        for key, value in json.loads(request.body).items():
            assert body[key] == value, key
    else:
        assert reply.status == 200 and body["id"] == 1 and body["title"]


def verify(live):
    example = ROOT / "outputs/examples/dummyjson/dummyjson.relay.json"
    with tempfile.TemporaryDirectory() as tmp:
        root = tk.Tk()
        root.withdraw()
        app = relay.App(root, relay.Workspace(Path(tmp)))
        original_env = app.state["default_env"]
        try:
            with patch.object(relay.filedialog, "askopenfilename", return_value=str(example)):
                app.import_file()
            collection = app.path[-1]
            assert collection["name"] == "DummyJSON"
            assert app.state["default_env"] == original_env
            paths = [path for item, path in relay.walk([collection]) if item["kind"] == "request"]
            assert len(paths) == 10
            assert {p[-1]["method"] for p in paths} == {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
            for path in paths:
                app.select(path[-1]["id"])
                request = relay.prepare(app.state, app.path)
                assert (request.scheme, request.host, request.port) == ("https", "dummyjson.com", None)
                assert request.target.startswith("/products") and "{" not in request.target
                assert all(k.lower() not in {"authorization", "cookie"} for k, _ in request.headers)
                if request.body:
                    assert ("Content-Type", "application/json") in request.headers
                    json.loads(request.body)
                if live:
                    app.send_button.invoke()
                    deadline = time.monotonic() + relay.HTTP_TIMEOUT + 5
                    while app.jobs and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.015)
                    assert not app.jobs, "A interface não concluiu o envio."
                    reply = app.replies[app.selected]
                    print(request.method, request.target, reply.status, reply.error, flush=True)
                    check_response(request, reply)
            print("Importação, ambiente herdado e 10 requisições verificados.")
        finally:
            app.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    verify(parser.parse_args().live)
