"""Valida a coleção pela interface. Use --live para enviá-la ao DummyJSON."""
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
import rota


def check_product_response(request, reply):
    assert not reply.error, reply.error
    headers = {key.lower(): value for key, value in reply.headers}
    if request.method == "OPTIONS":
        assert reply.status in (200, 204)
        assert "PATCH" in headers["access-control-allow-methods"]
        return
    if request.method == "HEAD":
        assert reply.status == 200 and not reply.data and "content-type" in headers
        return
    body = json.loads(rota.body_view(reply).text)
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


LOGIN = "Entrar com a conta de demonstração"
PROFILE = "Consultar meu perfil"
REFRESH = "Renovar a sessão"
BAD_PASSWORD = "Entrar com senha incorreta"
ANONYMOUS = "Consultar perfil sem token"
AUTH_CASES = {
    LOGIN: ("POST", "/auth/login", 200),
    PROFILE: ("GET", "/auth/me", 200),
    REFRESH: ("POST", "/auth/refresh", 200),
    BAD_PASSWORD: ("POST", "/auth/login", 400),
    ANONYMOUS: ("GET", "/auth/me", 401),
}


def send(app, request):
    assert (request.scheme, request.host, request.port) == ("https", "dummyjson.com", None)
    app.send_button.invoke()
    deadline = time.monotonic() + rota.HTTP_TIMEOUT + 5
    while app.jobs and time.monotonic() < deadline:
        app.root.update()
        time.sleep(.015)
    assert not app.jobs, "A interface não concluiu o envio."
    reply = app.replies[app.selected]
    print(request.method, request.target, reply.status, flush=True)
    assert not reply.error, reply.error
    return reply


def check_auth(app, paths, variables, live):
    assert set(paths) == set(AUTH_CASES)
    access = variables["access_token"]
    refresh = variables["refresh_token"]
    assert all(var["secret"] and var["value"] == "" for var in (access, refresh))
    # Exercita o mesmo perfil novamente após a renovação.
    for name in (LOGIN, PROFILE, REFRESH, PROFILE, BAD_PASSWORD, ANONYMOUS):
        method, target, expected = AUTH_CASES[name]
        app.select(paths[name][-1]["id"])
        request = rota.prepare(app.state, app.path)
        assert (request.method, request.target) == (method, target)
        assert (request.scheme, request.host, request.port) == ("https", "dummyjson.com", None)
        headers = {key.lower(): value for key, value in request.headers}
        assert "cookie" not in headers
        if name == PROFILE:
            assert access["value"] and headers.get("authorization") == "Bearer " + access["value"]
        else:
            assert "authorization" not in headers
        if method == "POST":
            assert headers["content-type"] == "application/json"
            payload = json.loads(request.body)
            if name == REFRESH:
                assert refresh["value"] and payload["refreshToken"] == refresh["value"]
            else:
                assert payload["username"] == "emilys"
                assert bool(payload["password"]) and (payload["password"] == "emilyspass") == (name == LOGIN)
        if not live:
            if name in (LOGIN, REFRESH):
                access["value"], refresh["value"] = f"access-{name}", f"refresh-{name}"
            continue
        reply = send(app, request)
        assert reply.status == expected, f"{name} retornou {reply.status} (esperado {expected})"
        data = json.loads(rota.body_view(reply).text)
        if name in (LOGIN, PROFILE):
            assert data["username"] == "emilys" and data["id"] > 0
        if name in (LOGIN, REFRESH):
            for var, key in ((access, "accessToken"), (refresh, "refreshToken")):
                assert isinstance(data[key], str) and data[key]
                var["value"] = data[key]
        if expected >= 400:
            assert data["message"] and "accessToken" not in data and "refreshToken" not in data


def verify(live):
    example = ROOT / "outputs/examples/dummyjson/dummyjson.relay.json"
    with tempfile.TemporaryDirectory() as tmp:
        root = tk.Tk()
        root.withdraw()
        app = rota.App(root, rota.Workspace(Path(tmp)))
        original_env = app.state["default_env"]
        try:
            with patch.object(rota.filedialog, "askopenfilename", return_value=str(example)):
                app.import_file()
            collection = app.path[-1]
            assert collection["name"] == "DummyJSON"
            assert app.state["default_env"] == original_env
            paths = [path for item, path in rota.walk([collection]) if item["kind"] == "request"]
            auth_paths = {p[-1]["name"]: p for p in paths if p[-2]["name"] == "Autenticação"}
            products = [p for p in paths if p[-2]["name"] != "Autenticação"]
            assert len(paths) == 15 and len(products) == 10
            assert {p[-1]["method"] for p in paths} == {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
            for path in products:
                app.select(path[-1]["id"])
                request = rota.prepare(app.state, app.path)
                assert (request.scheme, request.host, request.port) == ("https", "dummyjson.com", None)
                assert request.target.startswith("/products") and "{" not in request.target
                assert all(k.lower() not in {"authorization", "cookie"} for k, _ in request.headers)
                if request.body:
                    assert ("Content-Type", "application/json") in request.headers
                    json.loads(request.body)
                if live:
                    check_product_response(request, send(app, request))
            env = rota.find_env(app.state, collection["env"])
            check_auth(app, auth_paths, {v["key"]: v for v in env["variables"]}, live)
            shared = rota.share_package(app.state, path=[collection])
            for var in shared["environments"][0]["variables"]:
                if var["secret"]:
                    assert var["value"] == ""
            print("Importação e 15 requisições verificadas, incluindo o perfil após a renovação.")
        finally:
            app.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    verify(parser.parse_args().live)
