"""Rota · cliente HTTP para desenvolvedores. Execute com Python 3.10+ e Tkinter.

O tema visual está em Theme e em configure_styles(). O espaço de trabalho
fica em %LOCALAPPDATA%/RelayHTTP. O formato de intercâmbio é JSON versão 1.
"""

from __future__ import annotations

import base64
import codecs
import copy
import csv
import http.client
import ipaddress
import io
import json
import os
import queue
import re
import socket
import ssl
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import uuid
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import quote, urlencode, urlsplit
from xml.parsers import expat


APP = "Rota"
# Identificadores de disco mantidos para ler dados e coleções do Relay.
WORKSPACE_DIR = "RelayHTTP"
WORKSPACE_FORMAT = "relay-dpapi"
FORMAT = "relay-http"
APP_ICON = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAABLklEQVR42mNgGGyAMzPc"
    "FojXAvFrIP5PJfwaaqYtIctnUtFSXHjmQFqO3RHQYP9PZ2yL7IC11DRctCTxv93sVjAG"
    "sXGoW4vsAKolOItpDf+nvb/8f87XG2AMYoPEsCVMZAdQzefIliM7AltIUN0BoCBHtxy"
    "GQXLD3wEDHgUkJkLaOACEdbrL4A4AsXGpo5kDvJZPgDtArbWQvg5wWdiNEv/SVWn0c"
    "wC65SA+PvVUdQCpllPVAeRYTtABivU5/4vPbQFnIxAGsUFi1LIcrwNAFuEqUJAdQYn"
    "leB0A8i3MQlCWAmGYgyov7wRnLeSsRo7leB0AswxkCba8jY7JsZxqDiDXcoqjAITxF"
    "TJ0SYSUYrxNMmKzISV9BZo1SonEawdPs3zAOyaDoms2KDqnAwEAexnLjypHt8YAAAAA"
    "SUVORK5CYII="
)
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT")
AUTH = {"inherit": "Herdar", "none": "Sem autenticação", "bearer": "Bearer token", "basic": "Basic Auth"}
BODIES = {"none": "Sem corpo", "json": "JSON", "text": "Texto", "form": "Formulário", "file": "Arquivo"}
TYPES = {"collection": "Coleção", "folder": "Pasta", "request": "Requisição"}
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
VARIABLE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
SECRET_NAME = re.compile(r"(authorization|cookie|password|passwd|secret|token|api.?key|credential|senha)", re.I)
PREVIEW_LIMIT = 512 * 1024
TABLE_ROWS = 500
TABLE_COLUMNS = 64
HEX_LIMIT = 16 * 1024
VIEW_MODES = {"auto": "Automático", "json": "JSON", "lines": "JSON Lines", "xml": "XML",
              "csv": "CSV", "tsv": "TSV", "text": "Texto", "raw": "Raw",
              "png": "PNG", "hex": "Hex", "base64": "Base64"}
HTTP_TIMEOUT = 30


class Theme:
    """Paleta e tipografia compartilhadas por todos os componentes."""

    nav = "#182635"
    nav_alt = "#233547"
    nav_sel = "#30485B"
    nav_text = "#ECF3F6"
    nav_muted = "#B4C6D2"
    mint = "#77DEC1"
    bg = "#F4F6F8"
    card = "#FFFFFF"
    ink = "#192C39"
    muted = "#526471"
    border = "#D4DDE2"
    line = "#E6EBEE"
    accent = "#096957"
    accent_hover = "#075343"
    accent_soft = "#DCF3EB"
    danger = "#9A3931"
    danger_soft = "#FBE8E5"
    amber = "#815000"
    amber_soft = "#FFF0C9"
    font = "Segoe UI"
    mono = "Consolas"


def uid():
    return uuid.uuid4().hex


def row(key="", value="", enabled=True):
    return {"key": key, "value": value, "enabled": enabled}


def make_node(kind, name):
    item = dict(id=uid(), kind=kind, name=name, auth={"mode": "inherit"}, env="inherit")
    if kind == "request":
        item.update(method="GET", url="", params=[row()], headers=[row()], body_kind="none",
                    body="", form=[row()], file="", target="")
    else:
        item["children"] = []
    return item


def initial_state():
    env = dict(id=uid(), name="Local", variables=[dict(key="base_url", value="http://localhost:8000", secret=False)])
    request = make_node("request", "Verificar status")
    request["url"] = "{{base_url}}/health"
    root = make_node("collection", "Minha coleção")
    root["children"].append(request)
    return dict(version=1, roots=[root], environments=[env], default_env=env["id"], selected=request["id"])


def walk(items, parents=()):
    for item in items:
        path = (*parents, item)
        yield item, path
        yield from walk(item.get("children", []), path)


def path_for(state, node_id):
    return next((path for item, path in walk(state["roots"]) if item["id"] == node_id), ())


def env_for(state, path):
    for item in reversed(path):
        if item["env"] != "inherit":
            return item["env"], item["name"]
    return state["default_env"], "espaço de trabalho"


def auth_for(path):
    for item in reversed(path):
        if item["auth"]["mode"] != "inherit":
            return item["auth"], item["name"]
    return {"mode": "none"}, "espaço de trabalho"


def find_env(state, env_id):
    return next((e for e in state["environments"] if e["id"] == env_id), None)


def fresh_name(base, existing):
    names = {x["name"].casefold() for x in existing}
    name = base
    i = 2
    while name.casefold() in names:
        name = f"{base} ({i})"
        i += 1
    return name


def need(ok, message):
    if not ok:
        raise ValueError(message)


def is_text(value):
    return isinstance(value, str)


def valid_rows(rows, flag):
    need(isinstance(rows, list), "Lista de campos inválida.")
    for r in rows:
        need(isinstance(r, dict) and is_text(r.get("key")) and is_text(r.get("value"))
             and isinstance(r.get(flag), bool), "Campo de chave/valor inválido.")


def validate(state, fragment=False):
    need(isinstance(state, dict) and state.get("version") == 1, "Versão de arquivo incompatível.")
    if not fragment and "proxy" in state:
        configured_proxy(state["proxy"])
    roots, envs = state.get("roots"), state.get("environments")
    need(isinstance(roots, list) and isinstance(envs, list), "Estrutura de arquivo inválida.")
    ids = set()

    def identity(obj):
        need(isinstance(obj, dict) and is_text(obj.get("id")) and bool(obj["id"])
             and is_text(obj.get("name")) and bool(obj["name"].strip()), "Nome ou identificador inválido.")
        need(obj["id"] not in ids and obj["id"] not in ("inherit", "none"), "Identificador repetido ou reservado.")
        ids.add(obj["id"])

    for env in envs:
        identity(env)
        valid_rows(env.get("variables"), "secret")
    env_ids = {e["id"] for e in envs}
    need(state.get("default_env") in env_ids | {"none"}, "Ambiente padrão ausente.")

    def visit(item, depth):
        need(depth <= 80, "Limite de 80 níveis de pastas excedido.")
        identity(item)
        kind = item.get("kind")
        need(kind in TYPES, "Tipo de item desconhecido.")
        need((kind == "collection") == (depth == 0) or (fragment and depth == 0), "Coleção em posição inválida.")
        need(item.get("env") in env_ids | {"inherit", "none"}, "Referência a ambiente ausente.")
        auth = item.get("auth")
        need(isinstance(auth, dict) and auth.get("mode") in AUTH
             and all(is_text(auth.get(k, "")) for k in ("username", "password", "token")), "Autenticação inválida.")
        if kind == "request":
            need(all(is_text(item.get(k)) for k in ("method", "url", "body", "file", "target"))
                 and item.get("body_kind") in BODIES and "children" not in item, "Requisição inválida.")
            for k in ("params", "headers", "form"):
                valid_rows(item.get(k), "enabled")
        else:
            need(isinstance(item.get("children"), list), "Lista de itens ausente.")
            for child in item["children"]:
                visit(child, depth + 1)

    for root in roots:
        visit(root, 0)


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".rota-", suffix=".tmp", delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def windows_protect(data, *, decrypt=False):
    """Usa a DPAPI no escopo do usuário conectado, sem chave no script."""
    import ctypes as ct
    from ctypes import wintypes

    class Blob(ct.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ct.POINTER(ct.c_ubyte))]

    crypt = ct.WinDLL("crypt32", use_last_error=True)
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    action = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    action.argtypes = [ct.POINTER(Blob), ct.c_void_p, ct.POINTER(Blob), ct.c_void_p,
                       ct.c_void_p, wintypes.DWORD, ct.POINTER(Blob)]
    action.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ct.c_void_p]
    kernel.LocalFree.restype = ct.c_void_p
    buf = (ct.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(buf), buf)
    result = Blob()
    if not action(ct.byref(source), None, None, None, None, 1, ct.byref(result)):
        raise ct.WinError(ct.get_last_error())
    try:
        return ct.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


class Workspace:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "workspace.json"
        self.lock = (directory / "workspace.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            raise ValueError(f"O espaço de trabalho já está aberto em outra instância do {APP}.") from exc
        try:
            self.state = read_json(self.path) if self.path.exists() else initial_state()
            if isinstance(self.state, dict) and self.state.get("format") == WORKSPACE_FORMAT:
                need(os.name == "nt", "Abra este espaço de trabalho com a conta Windows que o criou.")
                protected = base64.b64decode(self.state["data"], validate=True)
                self.state = json.loads(windows_protect(protected, decrypt=True))
            validate(self.state)
        except Exception:
            self.lock.close()
            raise

    def save(self):
        payload = self.state
        if os.name == "nt":
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            payload = dict(format=WORKSPACE_FORMAT, data=base64.b64encode(windows_protect(raw)).decode("ascii"))
        write_json(self.path, payload)

    def close(self):
        self.lock.close()


def share_package(state, *, path=(), environment=None, secrets=False):
    """Congela a herança externa à seleção e inclui os ambientes referenciados."""
    roots = []
    if environment is not None:
        envs = [copy.deepcopy(environment)]
    else:
        item = copy.deepcopy(path[-1])
        if item["auth"]["mode"] == "inherit":
            item["auth"] = copy.deepcopy(auth_for(path)[0])
        if item["env"] == "inherit":
            item["env"] = env_for(state, path)[0]
        roots.append(item)
        used = {n["env"] for n, _ in walk(roots)}
        envs = [copy.deepcopy(e) for e in state["environments"] if e["id"] in used]
    for n, _ in walk(roots):
        if n["kind"] == "request":
            n["file"] = ""  # Caminhos locais e conteúdo de arquivos não são portáveis.
        if not secrets:
            for k in ("password", "token"):
                if k in n["auth"] and not VARIABLE.fullmatch(n["auth"][k]):
                    n["auth"][k] = ""
            for group in ("params", "headers", "form"):
                for r in n.get(group, []):
                    if SECRET_NAME.search(r["key"]) and not VARIABLE.fullmatch(r["value"]):
                        r["value"] = ""
    if not secrets:
        for e in envs:
            for r in e["variables"]:
                if r["secret"] or SECRET_NAME.search(r["key"]):
                    r["value"] = ""
    return dict(format=FORMAT, version=1, roots=roots, environments=envs, default_env="none")


def import_package(state, package, parent_path=()):
    need(isinstance(package, dict) and package.get("format") == FORMAT, f"Selecione um arquivo JSON exportado pelo {APP}.")
    incoming = copy.deepcopy(package)
    validate(incoming, fragment=True)
    need(incoming["roots"] or incoming["environments"], "O arquivo está vazio.")
    # Prepara e valida tudo em uma cópia antes de alterar o espaço de trabalho.
    merged = copy.deepcopy(state)
    env_map = {}
    for e in incoming["environments"]:
        old = e["id"]
        e["id"] = env_map[old] = uid()
        e["name"] = fresh_name(e["name"], merged["environments"])
        merged["environments"].append(e)
    for n, _ in walk(incoming["roots"]):
        n["id"] = uid()
        n["env"] = env_map.get(n["env"], n["env"])
        if n["kind"] == "request":
            n["file"] = ""
    parent = next((n for n in reversed(parent_path) if n["kind"] != "request"), None)
    dest = path_for(merged, parent["id"])[-1] if parent else None
    for n in incoming["roots"]:
        if n["kind"] == "collection":
            target = merged["roots"]
        else:
            if dest is None:
                dest = make_node("collection", fresh_name("Importados", merged["roots"]))
                merged["roots"].append(dest)
            target = dest["children"]
        n["name"] = fresh_name(n["name"], target)
        target.append(n)
        merged["selected"] = n["id"]
    validate(merged)
    state.update(merged)
    return len(incoming["roots"]), len(env_map)


class Variables:
    def __init__(self, environment):
        self.values = {}
        self.cache = {}
        for r in (environment or {}).get("variables", []):
            name = r["key"].strip()
            if name:
                need(name not in self.values, f"Variável duplicada no ambiente: {name}")
                self.values[name] = r["value"]

    def expand(self, value, chain=()):
        chunks, end, total = [], 0, len(value)
        for match in VARIABLE.finditer(value):
            key = match[1].strip()
            need(key in self.values, "Variável ausente no ambiente: " + key)
            need(key not in chain and len(chain) < 50, "Referência circular ou muito profunda: " + key)
            if key not in self.cache:
                self.cache[key] = self.expand(self.values[key], (*chain, key))
            replacement = self.cache[key]
            total += len(replacement) - len(match[0])
            need(total <= 16 * 1024 * 1024, "Campo expandido excede 16 MiB. Para corpos grandes, use Arquivo.")
            chunks.extend((value[end:match.start()], replacement))
            end = match.end()
        if not chunks:
            return value
        chunks.append(value[end:])
        return "".join(chunks)


PROXY_DEFAULTS = {"enabled": False, "host": "", "port": "8080", "authenticate": False,
                  "username": "", "password": "", "bypass": ""}


class ProxyInputError(ValueError):
    def __init__(self, field_name, message):
        super().__init__(message)
        self.field_name = field_name


def proxy_hostname(value):
    if re.search(r"[\s\x00-\x1f\x7f/@\\?#]", value):
        raise ValueError("Host inválido")
    if value.startswith("[") and value.endswith("]"):
        return str(ipaddress.IPv6Address(value[1:-1]))
    if ":" in value:
        return str(ipaddress.IPv6Address(value))
    host = value.rstrip(".").encode("idna").decode("ascii").lower()
    if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                                  for part in host.split(".")):
        raise ValueError("Host inválido")
    return host


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    authorization: str = field(repr=False)
    bypass: tuple

    def bypasses(self, host):
        host = host.rstrip(".").lower()
        if ":" in host:
            host = str(ipaddress.IPv6Address(host))
        return any(host.endswith(pattern[1:]) if pattern.startswith("*.") else host == pattern
                   for pattern in self.bypass)


def configured_proxy(settings):
    need(isinstance(settings, dict) and all(isinstance(settings.get(k), type(v))
         for k, v in PROXY_DEFAULTS.items()), "Configuração de proxy inválida.")
    if not settings["enabled"]:
        return None
    try:
        host = proxy_hostname(settings["host"].strip())
    except (UnicodeError, ValueError):
        raise ProxyInputError("host", "Informe o nome ou IP do servidor, sem protocolo nem porta.") from None
    port = settings["port"].strip()
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise ProxyInputError("port", "Informe uma porta entre 1 e 65535.")
    patterns = []
    for item in settings["bypass"].split(","):
        item = item.strip()
        if item:
            wildcard = item.startswith("*.")
            try:
                normalized = proxy_hostname(item.removeprefix("*."))
            except (UnicodeError, ValueError):
                raise ProxyInputError("bypass", "Use nomes ou IPs separados por vírgula, como localhost, *.empresa.com.") from None
            patterns.append(("*." if wildcard else "") + normalized)
    auth = ""
    if settings["authenticate"]:
        user = settings["username"]
        if not user.strip() or ":" in user:
            raise ProxyInputError("username", "Informe um usuário sem dois-pontos.")
        pair = (user + ":" + settings["password"]).encode("utf-8")
        auth = "Basic " + base64.b64encode(pair).decode("ascii")
    return Proxy(host, int(port), auth, tuple(patterns))


@dataclass
class Prepared:
    method: str
    scheme: str
    host: str
    port: int | None
    target: str
    headers: list
    body: bytes | None
    file: str
    proxy: Proxy | None = None


def prepare(state, path):
    n = path[-1]
    expand = Variables(find_env(state, env_for(state, path)[0])).expand
    method = n["method"].strip()
    need(TOKEN.fullmatch(method), "Informe um método HTTP válido.")
    url = expand(n["url"]).strip()
    need(not re.search(r"[\x00-\x1f\x7f]", url), "A URL contém caracteres de controle.")
    parts = urlsplit(url)
    need(parts.scheme in ("http", "https") and parts.hostname, "Informe uma URL completa com http:// ou https://.")
    need(parts.username is None and parts.password is None, "Configure as credenciais na aba Autenticação.")
    host = parts.hostname.encode("idna").decode("ascii")
    port = parts.port
    need(port is None or port > 0, "Porta inválida.")

    def pairs(group):
        result = []
        for r in n[group]:
            if r["enabled"] and (r["key"] or r["value"]):
                result.append((expand(r["key"]), expand(r["value"])))
        return result

    target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="=&%/:@!$'()*+,;?-._~")
    params = urlencode(pairs("params"))
    query = "&".join(x for x in (query, params) if x)
    if query:
        target += "?" + query
    if method == "CONNECT":
        authority = f"[{host}]" if ":" in host else host
        target = expand(n["target"]).strip() or f"{authority}:{port or (443 if parts.scheme == 'https' else 80)}"
        need(re.fullmatch(r"(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._-]+):[0-9]+", target)
             and 0 < int(target.rsplit(":", 1)[1]) <= 65535, "Destino CONNECT inválido. Use host:porta.")
    headers = pairs("headers")
    names = {k.lower() for k, _ in headers}
    auth, _ = auth_for(path)
    if "authorization" not in names:
        if auth["mode"] == "bearer":
            token = expand(auth.get("token", ""))
            need(token.strip(), "Preencha o token Bearer na configuração de autenticação.")
            headers.append(("Authorization", "Bearer " + token))
        elif auth["mode"] == "basic":
            user = expand(auth.get("username", ""))
            need(":" not in user, "O usuário de Basic Auth contém dois-pontos.")
            pair = (user + ":" + expand(auth.get("password", ""))).encode()
            headers.append(("Authorization", "Basic " + base64.b64encode(pair).decode("ascii")))
    kind = n["body_kind"]
    body, file = None, ""
    content_types = {"json": "application/json", "text": "text/plain; charset=utf-8",
                     "form": "application/x-www-form-urlencoded", "file": "application/octet-stream"}
    if kind in ("json", "text"):
        content = expand(n["body"])
        if kind == "json":
            try:
                json.loads(content)
            except ValueError as exc:
                raise ValueError(f"Corpo JSON inválido: {exc}") from exc
        body = content.encode()
    elif kind == "form":
        body = urlencode(pairs("form")).encode("ascii")
    elif kind == "file":
        file = n["file"]
        need(file and Path(file).is_file(), "Selecione um arquivo de corpo disponível neste computador.")
    if kind != "none" and "content-type" not in names:
        headers.append(("Content-Type", content_types[kind]))
    for k, v in headers:
        need(TOKEN.fullmatch(k), "Nome de cabeçalho HTTP inválido: " + k)
        need(not re.search(r"[\x00-\x08\x0a-\x1f\x7f]", v), "Valor inválido no cabeçalho " + k)
        try:
            v.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise ValueError("Caractere incompatível com HTTP/1.1 no cabeçalho " + k) from exc
    if method == "CONNECT" and "host" not in names:
        headers.append(("Host", target))
    need("transfer-encoding" not in names, f"O {APP} calcula o enquadramento do corpo. Remova Transfer-Encoding.")
    proxy = configured_proxy(state.get("proxy", PROXY_DEFAULTS))
    if proxy and "proxy-authorization" in names:
        raise ValueError("Use a autenticação em Proxy e remova o cabeçalho Proxy-Authorization da requisição.")
    if proxy and proxy.bypasses(host):
        proxy = None
    return Prepared(method, parts.scheme, host, port, target, headers, body, file, proxy)


@dataclass
class Reply:
    status: int = 0
    reason: str = ""
    headers: list = field(default_factory=list)
    data: bytes = b""
    elapsed: float = 0
    truncated: bool = False
    error: str = ""


class Job:
    def __init__(self):
        self.cancelled = threading.Event()
        self.connection = None

    def cancel(self):
        self.cancelled.set()
        sock = getattr(self.connection, "sock", None)
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def check(self):
        if self.cancelled.is_set():
            raise ValueError("Requisição cancelada.")


def perform(req, job):
    start = time.perf_counter()
    conn = None
    upload = None
    try:
        endpoint = (req.proxy.host, req.proxy.port) if req.proxy else (req.host, req.port)
        if req.scheme == "https":
            conn = http.client.HTTPSConnection(*endpoint, timeout=HTTP_TIMEOUT,
                                                context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(*endpoint, timeout=HTTP_TIMEOUT)
        job.connection = conn
        job.check()
        target = req.target
        headers = req.headers
        if req.proxy:
            authority = f"[{req.host}]" if ":" in req.host else req.host
            proxy_headers = {"Proxy-Authorization": req.proxy.authorization} if req.proxy.authorization else {}
            if req.scheme == "https" or req.method == "CONNECT":
                destination_port = req.port or (443 if req.scheme == "https" else 80)
                proxy_headers["Host"] = f"{authority}:{destination_port}"
                conn.set_tunnel(req.host, destination_port, headers=proxy_headers)
            else:
                if req.port is not None:
                    authority += f":{req.port}"
                target = f"http://{authority}{target}"
                headers = [*headers, *proxy_headers.items()]
        upload = open(req.file, "rb") if req.file else None
        size = os.fstat(upload.fileno()).st_size if upload else len(req.body or b"")
        lengths = [v for k, v in req.headers if k.lower() == "content-length"]
        need(not lengths or lengths == [str(size)], "Content-Length deve corresponder ao tamanho do corpo.")
        names = {k.lower() for k, _ in req.headers}
        conn.putrequest(req.method, target, skip_host="host" in names, skip_accept_encoding="accept-encoding" in names)
        for k, v in headers:
            conn.putheader(k, v)
        if not lengths and (req.body is not None or upload or req.method in ("POST", "PUT", "PATCH")):
            conn.putheader("Content-Length", str(size))
        conn.endheaders()
        job.check()
        if upload:
            while chunk := upload.read(65536):
                job.check()
                conn.send(chunk)
        elif req.body:
            conn.send(req.body)
        with conn.getresponse() as res:
            headers = res.getheaders()
            # CONNECT bem-sucedido abre um túnel. A resposta HTTP termina nos cabeçalhos.
            data = bytearray()
            if not (req.method == "CONNECT" and 200 <= res.status < 300):
                while len(data) <= PREVIEW_LIMIT:
                    job.check()
                    chunk = res.read1(min(65536, PREVIEW_LIMIT + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                if len(data) <= PREVIEW_LIMIT and res.length and req.method != "HEAD":
                    raise OSError("Conexão encerrada com corpo incompleto.")
            job.check()
            return Reply(res.status, res.reason, headers, bytes(data[:PREVIEW_LIMIT]),
                         time.perf_counter() - start, len(data) > PREVIEW_LIMIT)
    except Exception as exc:
        msg = "Requisição cancelada." if job.cancelled.is_set() else str(exc)
        if req.proxy and "Tunnel connection failed: 407" in msg:
            msg = "HTTP 407 · O proxy exige autenticação. Confira o usuário e a senha em Proxy."
        return Reply(error=msg, elapsed=time.perf_counter() - start)
    finally:
        if upload:
            upload.close()
        if conn:
            conn.close()


@dataclass
class BodyView:
    mode: str
    text: str = ""  # Conteúdo do botão Copiar, sem avisos nem decoração.
    note: str = ""
    columns: tuple = ()
    rows: list = field(default_factory=list)
    image: bytes = b""


def hex_view(data, note=""):
    sample = data[:HEX_LIMIT]
    lines = []
    for offset in range(0, len(sample), 16):
        block = sample[offset:offset+16]
        ascii_text = "".join(chr(b) if 32 <= b < 127 else "." for b in block)
        lines.append(f"{offset:08X}  {block.hex(' '):47}  {ascii_text}")
    if len(sample) < len(data):
        note = (note + "  Hex limitado aos primeiros 16 KiB.").strip()
    return BodyView("hex", "\n".join(lines), note)


def decode_entity(reply, headers):
    data, clipped = reply.data, reply.truncated
    encodings = ",".join(headers.get_all("Content-Encoding", [])).lower().split(",")
    for coding in reversed(encodings):
        coding = coding.strip()
        if coding in ("", "identity"):
            continue
        if coding not in ("gzip", "deflate"):
            raise ValueError(f"Codificação {coding} sem decodificador.")
        decoder = zlib.decompressobj(31 if coding == "gzip" else 15)
        data = decoder.decompress(data, PREVIEW_LIMIT + 1)
        if not decoder.eof and not clipped and len(data) <= PREVIEW_LIMIT:
            raise ValueError("Fluxo comprimido incompleto.")
        if decoder.unused_data:
            raise ValueError("Dados adicionais após o fluxo comprimido.")
        clipped |= len(data) > PREVIEW_LIMIT
        data = data[:PREVIEW_LIMIT]
    return data, clipped


def detect_mode(mime, data):
    if mime in ("application/x-ndjson", "application/ndjson", "application/jsonl",
                "application/jsonlines", "application/json-lines"):
        return "lines"
    if mime.endswith(("/json", "+json")):
        return "json"
    if mime.endswith(("/xml", "+xml")):
        return "xml"
    if mime in ("text/csv", "application/csv"):
        return "csv"
    if mime == "text/tab-separated-values":
        return "tsv"
    if mime == "image/png" or (not mime and data.startswith(b"\x89PNG\r\n\x1a\n")):
        return "png"
    if not mime or mime == "text/plain":
        if data.removeprefix(codecs.BOM_UTF8).lstrip().startswith((b"{", b"[")):
            return "json"
        if not mime:
            if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE, codecs.BOM_UTF32_BE)):
                return "text"
            sample = data[:2048]
            if any(b < 32 and b not in (9, 10, 12, 13) for b in sample):
                return "hex"
            try:
                codecs.getincrementaldecoder("utf-8")().decode(sample, final=len(data) <= len(sample))
            except UnicodeDecodeError:
                return "hex"
        return "text"
    if mime.startswith("text/") or mime.endswith(("/yaml", "+yaml", "/x-yaml", "/javascript",
                                                "/x-www-form-urlencoded", "/graphql", "/toml")):
        return "text"
    return "hex"


def decode_text(data, charset, mode):
    if charset in ("utf-8", "utf8") and data.startswith(codecs.BOM_UTF8):
        charset = "utf-8-sig"
    if not charset:
        if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            charset = "utf-32"
        elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            charset = "utf-16"
        elif mode == "xml":
            decl = re.match(rb"""<\?xml\s+[^?]*?\bencoding\s*=\s*["']([\w.-]+)["']""", data[:256])
            charset = decl[1].decode("ascii") if decl else None
    charset = charset or "utf-8-sig"
    try:
        return data.decode(charset), ""
    except (UnicodeError, LookupError):
        try:
            return data.decode(charset, errors="replace"), "A prévia contém caracteres substituídos."
        except (LookupError, UnicodeError):
            return data.decode("utf-8", errors="replace"), "Charset indisponível. Prévia em UTF-8."


def validate_json(source):
    def invalid(value):
        raise ValueError(f"Valor JSON inválido ({value}).")
    json.loads(source, parse_int=str, parse_float=str, parse_constant=invalid)


def format_json(source):
    # Recuar os tokens originais preserva números, escapes e chaves repetidas.
    validate_json(source)
    tokens = re.finditer(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]|[^\s{}\[\],:"]+', source)
    chunks, depth, length, previous = [], 0, 0, ""
    for match in tokens:
        token = match[0]
        closed = token in ("}", "]")
        opened = previous in ("{", "[")
        if closed:
            depth -= 1
        new_line = (closed and not opened) or (opened and not closed) or previous == ","
        prefix = "\n" + "  " * depth if new_line else (" " if previous == ":" else "")
        length += len(prefix) + len(token)
        if length > PREVIEW_LIMIT:
            raise ValueError("JSON formatado excede 512 KiB.")
        chunks.extend((prefix, token))
        if token in ("{", "["):
            depth += 1
        previous = token
    return "".join(chunks)


def table_view(mode, content, headers):
    source = io.StringIO(content, newline="")
    if mode == "lines":
        rows = []
        limited = False
        for i, line in enumerate(source, 1):
            if i > TABLE_ROWS:
                limited = True
                break
            try:
                validate_json(line)
            except (ValueError, RecursionError) as exc:
                raise ValueError(f"Registro JSON inválido na linha {i}.") from exc
            rows.append((str(i), line.rstrip("\r\n")))
        columns = ("Linha", "JSON")
    else:
        delimiter = "\t" if mode == "tsv" else ","
        if mode == "csv" and ";" in content.partition("\n")[0]:
            try:
                delimiter = csv.Sniffer().sniff(content[:4096], delimiters=",;").delimiter
            except csv.Error:
                pass
        reader = csv.reader(source, delimiter=delimiter, strict=True)
        explicit_header = str(headers.get_param("header", "")).lower() == "present"
        heading = next(reader, []) if explicit_header else []
        rows, limited = [], len(heading) > TABLE_COLUMNS
        for i, values in enumerate(reader):
            if i == TABLE_ROWS:
                limited = True
                break
            limited |= len(values) > TABLE_COLUMNS
            rows.append(tuple(values[:TABLE_COLUMNS]))
        width = min(TABLE_COLUMNS, max([1, len(heading), *(len(values) for values in rows)]))
        columns = tuple(heading[i] if i < len(heading) and heading[i] else f"Coluna {i+1}" for i in range(width))
    note = f"Tabela limitada a {TABLE_ROWS} linhas e {TABLE_COLUMNS} colunas." if limited else ""
    return BodyView(mode, content, note, columns, rows)


def xml_view(content):
    parser = expat.ParserCreate()
    rows, parents = [], []
    parser.buffer_text = True

    def append(name, value):
        if len(rows) >= 2000 or len(parents) >= 80:
            raise ValueError("XML excede o limite da árvore (2.000 nós ou 80 níveis).")
        rows.append((str(parents[-1]) if parents else "", name, value))

    def start(name, attrs):
        append(name, "  ".join(f'{k}="{v}"' for k, v in attrs.items()))
        parents.append(len(rows))

    def text(value):
        if value.strip():
            append("#texto", value)

    def doctype(*_):
        raise ValueError("A árvore XML não processa DTD.")

    parser.StartElementHandler = start
    parser.EndElementHandler = lambda _: parents.pop()
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = doctype
    parser.Parse(content, True)
    return BodyView("xml", content, columns=("Elemento", "Atributos / valor"), rows=rows)


def body_view(reply, requested="auto"):
    if not reply.data:
        return BodyView("text", "Resposta sem corpo.")
    headers = Message()
    for k, v in reply.headers:
        headers[k] = v
    mime = headers.get_content_type() if "Content-Type" in headers else ""
    note = "Prévia limitada aos primeiros 512 KiB." if reply.truncated else ""
    if requested == "hex":
        return hex_view(reply.data, note)
    if requested == "base64":
        return BodyView("base64", base64.b64encode(reply.data).decode("ascii"), note)
    try:
        data, clipped = decode_entity(reply, headers)
    except (ValueError, zlib.error) as exc:
        return hex_view(reply.data, f"{exc} Exibindo os bytes recebidos. {note}".strip())
    detected = detect_mode(mime, data)
    mode = detected if requested == "auto" else requested
    if mode == "hex" or (mode == "raw" and detected in ("hex", "png")):
        return hex_view(reply.data, " ".join(filter(None, ["Corpo binário.", note])))
    if clipped:
        note = "Prévia limitada aos primeiros 512 KiB."
    if mode == "png":
        size = (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
        if (not clipped and data.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
                and all(0 < side <= 8192 for side in size) and size[0]*size[1] <= 4_000_000):
            return BodyView("png", image=data, note=f"{size[0]} × {size[1]} px")
        return hex_view(reply.data, f"PNG incompleto, inválido ou acima do limite de dimensões. {note}".strip())
    content, warning = decode_text(data, headers.get_content_charset(), detected if mode == "raw" else mode)
    if mode in ("raw", "text") or clipped or warning:
        return BodyView(mode if mode in ("raw", "text") else "raw", content, " ".join(filter(None, (note, warning))))
    try:
        if mode == "json":
            return BodyView(mode, format_json(content))
        if mode == "xml":
            return xml_view(content)
        return table_view(mode, content, headers)
    except (ValueError, RecursionError, csv.Error, expat.ExpatError) as exc:
        return BodyView("raw", content, f"{VIEW_MODES[mode]} · {exc} Exibindo Raw.")


def render_body(reply, pretty=True):
    """Representação textual para consumidores sem interface gráfica."""
    view = body_view(reply, "auto" if pretty else "raw")
    return "\n\n".join(filter(None, (view.text, view.note)))


def configure_styles(root):
    t = Theme
    style = ttk.Style(root)
    style.theme_use("clam")
    root.option_add("*Font", (t.font, 10))
    root.option_add("*Menu.Font", (t.font, 10))
    root.option_add("*TCombobox*Listbox.font", (t.font, 10))
    style.configure(".", font=(t.font, 10), foreground=t.ink, background=t.card)
    style.configure("TEntry", fieldbackground=t.card, bordercolor=t.border,
                    lightcolor=t.border, darkcolor=t.border, padding=(7, 5))
    style.map("TEntry", bordercolor=[("focus", t.accent)], lightcolor=[("focus", t.accent)],
              darkcolor=[("focus", t.accent)])
    style.configure("TCombobox", fieldbackground=t.card, background=t.card,
                    bordercolor=t.border, lightcolor=t.border, darkcolor=t.border,
                    arrowcolor=t.muted, padding=(7, 5))
    style.map("TCombobox", fieldbackground=[("readonly", t.card)],
              foreground=[("readonly", t.ink)], bordercolor=[("focus", t.accent)])
    for name, bg, fg, hover, border in (
        ("TButton", t.card, t.ink, t.bg, t.border),
        ("Primary.TButton", t.accent, "white", t.accent_hover, t.accent),
        ("Quiet.TButton", t.card, t.muted, t.bg, t.card),
        ("Tab.TButton", t.card, t.muted, t.bg, t.card),
        ("Active.Tab.TButton", t.card, t.accent, t.accent_soft, t.card),
        ("Nav.TButton", t.nav_alt, t.nav_text, t.nav_sel, t.nav_alt),
        ("Link.Nav.TButton", t.nav, t.nav_muted, t.nav_alt, t.nav),
    ):
        style.configure(name, background=bg, foreground=fg, bordercolor=border,
                        lightcolor=border, darkcolor=border, focuscolor=fg,
                        padding=(9, 5), anchor="center", relief="flat", borderwidth=1)
        style.map(name, background=[("active", hover), ("pressed", hover)],
                  foreground=[("disabled", t.muted)], lightcolor=[("active", border)],
                  darkcolor=[("active", border)], bordercolor=[("focus", fg)])
    style.configure("Primary.TButton", font=(t.font, 10, "bold"), padding=(15, 6))
    style.configure("Method.TCombobox", foreground=t.accent, font=(t.mono, 11, "bold"))
    style.configure("TCheckbutton", background=t.card, focuscolor=t.accent)
    style.map("TCheckbutton", background=[("active", t.card)])
    style.configure("Nav.Treeview", background=t.nav, fieldbackground=t.nav,
                    foreground=t.nav_text, borderwidth=0, relief="flat",
                    font=(t.font, 10), rowheight=34, indent=15)
    style.layout("Nav.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.map("Nav.Treeview", background=[("selected", t.nav_sel)],
              foreground=[("selected", "white")])
    style.configure("Treeview", rowheight=31, borderwidth=0, background=t.card,
                    fieldbackground=t.card, foreground=t.ink)
    style.map("Treeview", background=[("selected", t.accent_soft)], foreground=[("selected", t.accent)])
    style.configure("Treeview.Heading", background=t.bg, foreground=t.muted,
                    font=(t.font, 9, "bold"), padding=5, relief="flat")
    style.configure("Vertical.TScrollbar", arrowsize=12, background=t.border,
                    troughcolor=t.bg, borderwidth=0)


def frame(parent, bg=None, **kwargs):
    return tk.Frame(parent, bg=bg or Theme.card, **kwargs)


def label(parent, text, size=10, color=None, *, bold=False, mono=False, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent.cget("bg"), fg=color or Theme.ink,
                    font=(Theme.mono if mono else Theme.font, size, "bold" if bold else "normal"),
                    anchor="w", bd=0, **kw)


def button(parent, text, command, style="TButton", **kw):
    return ttk.Button(parent, text=text, command=command, style=style, cursor="hand2", **kw)


def clear(widget):
    for child in widget.winfo_children():
        child.destroy()


def auto_scroll(bar):
    """Mostra a barra gerenciada por grid somente se houver conteúdo oculto."""
    def update(first, last):
        bar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            bar.grid_remove()
        else:
            bar.grid()
    return update


def watch(var, callback):
    var.trace_add("write", lambda *_: callback(var.get()))
    return var


def combo(parent, value, values, on_change, **kw):
    var = tk.StringVar(parent, value=value)
    box = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", **kw)
    box.bind("<<ComboboxSelected>>", lambda _: on_change(var.get()))
    box.variable = var
    return box


def entry(parent, record, key, changed, **kw):
    var = tk.StringVar(parent, value=record.get(key, ""))
    def edit(value):
        record[key] = value
        changed()
    watch(var, edit)
    widget = ttk.Entry(parent, textvariable=var, **kw)
    widget.variable = var
    return widget


def icon(parent, kind):
    img = tk.PhotoImage(master=parent, width=18, height=18)
    color = Theme.mint if kind == "collection" else Theme.nav_muted
    def rect(x, y, w, h):
        img.put(color, to=(x, y, x+w, y+h))
    if kind in ("collection", "folder"):
        rect(2, 4, 6, 1); rect(2, 5, 1, 9); rect(8, 5, 2, 1)
        rect(9, 6, 7, 1); rect(15, 7, 1, 7); rect(2, 14, 14, 1)
        if kind == "collection":
            rect(4, 8, 9, 1)
    else:
        rect(3, 9, 11, 1)
        for i in range(4):
            rect(10+i, 5+i, 1, 1); rect(10+i, 13-i, 1, 1)
    return img


def text_area(parent, content="", *, changed=None, wrap="none"):
    panel = frame(parent)
    panel.rowconfigure(0, weight=1)
    panel.columnconfigure(0, weight=1)
    widget = tk.Text(panel, bg=Theme.card, fg=Theme.ink, insertbackground=Theme.accent,
                     selectbackground=Theme.accent_soft, selectforeground=Theme.ink,
                     font=(Theme.mono, 10), relief="flat", bd=0, highlightthickness=0,
                     undo=changed is not None, wrap=wrap, padx=10, pady=7, width=1, height=1)
    vs = ttk.Scrollbar(panel, orient="vertical", command=widget.yview)
    widget.configure(yscrollcommand=auto_scroll(vs))
    widget.grid(row=0, column=0, sticky="nsew")
    vs.grid(row=0, column=1, sticky="ns")
    if wrap == "none":
        hs = ttk.Scrollbar(panel, orient="horizontal", command=widget.xview)
        widget.configure(xscrollcommand=auto_scroll(hs))
        hs.grid(row=1, column=0, sticky="ew")
    widget.insert("1.0", content)
    widget.edit_modified(False)
    if changed:
        def edited(_):
            if widget.edit_modified():
                widget.edit_modified(False)
                changed(widget.get("1.0", "end-1c"))
        widget.bind("<<Modified>>", edited)
    else:
        widget.configure(state="disabled")
    panel.pack(fill="both", expand=True)
    return widget


def response_table(parent, view):
    panel = frame(parent)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(0, weight=1)
    panel.rowconfigure(0, weight=1)
    is_tree = view.mode == "xml"
    ids = [f"c{i}" for i in range(len(view.columns))]
    tree = ttk.Treeview(panel, columns=ids[1:] if is_tree else ids,
                        show="tree headings" if is_tree else "headings", height=2)
    tree.grid(row=0, column=0, sticky="nsew")
    for i, name in enumerate(view.columns):
        col = "#0" if is_tree and i == 0 else ids[i]
        tree.heading(col, text=name, anchor="w")
        width = 64 if view.mode == "lines" and i == 0 else 165
        tree.column(col, width=width, minwidth=width, stretch=True)
    for i, values in enumerate(view.rows, 1):
        if is_tree:
            ancestor, name, value = values
            tree.insert(ancestor, "end", iid=str(i), text=name, values=(value,), open=i <= 30)
        else:
            # Treeview exibe uma linha por registro, inclusive para campos CSV multilinha.
            shown = [v.replace("\r\n", " ↵ ").replace("\n", " ↵ ").replace("\r", " ↵ ") for v in values]
            tree.insert("", "end", values=shown)
    vs = ttk.Scrollbar(panel, command=tree.yview)
    hs = ttk.Scrollbar(panel, orient="horizontal", command=tree.xview)
    vs.grid(row=0, column=1, sticky="ns")
    hs.grid(row=1, column=0, sticky="ew")
    tree.configure(yscrollcommand=auto_scroll(vs), xscrollcommand=auto_scroll(hs))


class RowEditor:
    """Linhas editáveis, com ordem estável e suporte a chaves repetidas."""

    def __init__(self, parent, rows, changed, *, variables=False, add_label="Adicionar linha"):
        self.rows, self.changed, self.variables = rows, changed, variables
        outer = frame(parent)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(outer, bg=Theme.card, highlightthickness=0, height=40)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=auto_scroll(scroll))
        scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.inner = frame(self.canvas)
        window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.inner.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.add_label = add_label
        self.draw()

    def draw(self):
        clear(self.inner)
        self.inner.columnconfigure(1, weight=2, uniform="kv")
        self.inner.columnconfigure(2, weight=3, uniform="kv")
        for col, name in enumerate(("Sigilo" if self.variables else "Usar", "Variável" if self.variables else "Chave", "Valor")):
            label(self.inner, name, 9, Theme.muted, bold=True).grid(row=0, column=col, sticky="w", padx=5, pady=(0, 4))
        self.last = None
        for i, r in enumerate(self.rows, 1):
            flag = "secret" if self.variables else "enabled"
            var = tk.BooleanVar(self.inner, r[flag])
            check = ttk.Checkbutton(self.inner, variable=var)
            check.grid(row=i, column=0, padx=5, pady=2)
            key = entry(self.inner, r, "key", self.changed, width=6)
            key.grid(row=i, column=1, sticky="ew", padx=(0, 5), pady=2)
            val = entry(self.inner, r, "value", self.changed, width=6, show="•" if self.variables and r[flag] else "")
            val.grid(row=i, column=2, sticky="ew", pady=2)
            def toggle(value, record=r, widget=val):
                record[flag] = value
                if self.variables:
                    widget.configure(show="•" if value else "")
                self.changed()
            watch(var, toggle)
            check.variable = var
            button(self.inner, "×", lambda index=i-1: self.remove(index), "Quiet.TButton", width=2).grid(row=i, column=3, padx=(3, 0))
            self.last = key
        button(self.inner, "+  " + self.add_label, self.add, "Quiet.TButton").grid(
            row=len(self.rows)+1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        for widget in (self.canvas, self.inner, *self.inner.winfo_children()):
            widget.bind("<MouseWheel>", self.wheel)

    def wheel(self, event):
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def add(self):
        self.rows.append(dict(key="", value="", secret=False) if self.variables else row())
        self.changed()
        self.draw()
        self.inner.update_idletasks()
        self.canvas.yview_moveto(1)
        self.last.focus_set()

    def remove(self, index):
        del self.rows[index]
        self.changed()
        self.draw()


def tab_bar(parent, options, selected, callback):
    bar = frame(parent)
    bar.pack(fill="x")
    for key, title in options:
        item = frame(bar)
        item.pack(side="left")
        button(item, title, lambda k=key: callback(k),
               "Active.Tab.TButton" if key == selected else "Tab.TButton").pack()
        frame(item, Theme.accent if key == selected else Theme.card, height=2).pack(fill="x")
    frame(parent, Theme.line, height=1).pack(fill="x")


def env_choices(state, inherit=True):
    pairs = [("none", "Sem ambiente")]
    if inherit:
        pairs.insert(0, ("inherit", "Herdar"))
    pairs.extend((e["id"], e["name"]) for e in state["environments"])
    return pairs


def choice_ids(parent, pairs, value, callback, width=24):
    index = next((i for i, (key, _) in enumerate(pairs) if key == value), 0)
    box = ttk.Combobox(parent, values=[name for _, name in pairs], state="readonly", width=width)
    box.current(index)
    box.bind("<<ComboboxSelected>>", lambda _: callback(pairs[box.current()][0]))
    return box


def modal(parent, name):
    previous = parent.grab_current()
    win = tk.Toplevel(parent)
    win.title(name)
    win.configure(bg=Theme.card)
    win.transient(parent)
    win.grab_set()
    win.bind("<Escape>", lambda _: win.destroy())
    if previous:
        def restore(event):
            if event.widget == win and previous.winfo_exists():
                previous.grab_set()
        win.bind("<Destroy>", restore)
    return win


def place_window(win, parent, width, height):
    parent.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    width, height = min(width, sw-30), min(height, sh-90)
    x = min(max(0, parent.winfo_rootx() + (parent.winfo_width()-width)//2), sw-width)
    y = min(max(0, parent.winfo_rooty() + (parent.winfo_height()-height)//2), sh-height-60)
    win.geometry(f"{width}x{height}+{x}+{max(0, y)}")


class App:
    def __init__(self, root, store):
        self.root, self.store, self.state = root, store, store.state
        self.events, self.jobs, self.replies = queue.Queue(), {}, OrderedDict()
        self.save_timer = None
        self.dirty = False
        self.selected = self.state.get("selected", "")
        self.page = "params"
        self.response_page = "body"
        self.body_mode = "auto"
        self.method_box = self.method_var = None
        self.env_window = None
        self.status = tk.StringVar(root, "Salvo localmente")
        configure_styles(root)
        root.title(f"{APP} · Cliente HTTP")
        self.brand_icon = tk.PhotoImage(master=root, data=APP_ICON)
        root.iconphoto(True, self.brand_icon)
        root.configure(bg=Theme.bg)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1210, sw-30)}x{min(820, sh-90)}")
        root.minsize(min(830, sw-30), min(580, sh-90))
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self.icons = {k: icon(root, k) for k in TYPES}
        self.sidebar()
        self.main = frame(root, Theme.bg)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=1)
        self.context = frame(self.main, Theme.card, padx=22, pady=10)
        self.context.grid(row=0, column=0, sticky="ew")
        self.context.columnconfigure(0, weight=1)
        self.crumb = label(self.context, "", 9, Theme.muted)
        self.crumb.grid(row=0, column=0, sticky="ew")
        label(self.context, "", 9, Theme.muted, textvariable=self.status).grid(row=0, column=1, padx=(10, 0))
        self.proxy_button = button(self.context, "", self.open_proxy)
        self.proxy_button.grid(row=0, column=2, padx=(14, 0))
        self.refresh_proxy()
        self.content = frame(self.main, Theme.bg)
        self.content.grid(row=1, column=0, sticky="nsew", padx=14, pady=14)
        self.refresh_tree()
        self.show()
        if not store.path.exists():
            self.changed()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-Return>", self.short_send)
        root.bind("<Control-s>", lambda _: self.short_save())
        root.bind("<Control-n>", lambda _: self.new("request"))
        root.bind("<Control-o>", lambda _: self.import_file())
        root.bind("<F2>", lambda _: self.rename())
        self.poll_timer = root.after(75, self.poll)

    @property
    def path(self):
        return path_for(self.state, self.selected)

    def changed(self):
        self.dirty = True
        if self.save_timer:
            self.root.after_cancel(self.save_timer)
        self.status.set("Salvando…")
        self.save_timer = self.root.after(550, self.save)

    def save(self, *, notify=False):
        if self.save_timer:
            self.root.after_cancel(self.save_timer)
            self.save_timer = None
        try:
            self.store.save()
            self.dirty = False
            self.status.set("Salvo localmente")
            return True
        except (OSError, ValueError) as exc:
            self.status.set("Falha ao salvar · Ctrl+S para tentar")
            if notify:
                messagebox.showerror("Salvar espaço de trabalho", str(exc), parent=self.root)
            return False

    def short_save(self):
        self.save(notify=True)
        return "break"

    def refresh_proxy(self):
        enabled = self.state.get("proxy", PROXY_DEFAULTS)["enabled"]
        self.proxy_button.configure(text="Proxy ativo" if enabled else "Proxy desativado")

    def open_proxy(self):
        return ProxyWindow(self)

    def close(self):
        if self.dirty and not self.save(notify=True):
            if not messagebox.askyesno(APP, "Sair e descartar as alterações não salvas?", parent=self.root):
                return
        for job in self.jobs.values():
            job.cancel()
        self.root.after_cancel(self.poll_timer)
        self.store.close()
        self.root.destroy()

    def sidebar(self):
        t = Theme
        side = frame(self.root, t.nav, width=245)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(3, weight=1)
        brand = frame(side, t.nav)
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(19, 20))
        tk.Label(brand, image=self.brand_icon, bg=t.nav, bd=0).pack(side="left")
        label(brand, APP, 23, t.nav_text, bold=True).pack(side="left", padx=9)
        head = frame(side, t.nav)
        head.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 9))
        label(head, "Coleções", 12, t.nav_text, bold=True).pack(side="left")
        self.new_button = button(head, "+ Novo", self.new_menu, "Nav.TButton", width=7)
        self.new_button.pack(side="right")
        search = frame(side, t.nav_alt, padx=8, pady=5)
        search.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 7))
        glyph = tk.Canvas(search, width=17, height=18, bg=t.nav_alt, highlightthickness=0)
        glyph.create_oval(2, 2, 10, 10, outline=t.nav_muted, width=2)
        glyph.create_line(10, 10, 15, 15, fill=t.nav_muted, width=2)
        glyph.pack(side="left", padx=(0, 6))
        self.search = tk.StringVar()
        self.filter_entry = tk.Entry(search, textvariable=self.search, bg=t.nav_alt, fg=t.nav_text,
                     insertbackground=t.mint, relief="flat", bd=0, width=12)
        self.filter_entry.pack(side="left", fill="x", expand=True)
        self.search_hint = label(self.filter_entry, "Filtrar itens", 10, t.nav_muted, bg=t.nav_alt)
        self.search_hint.place(x=0, y=0)
        self.search_hint.bind("<Button-1>", lambda _: self.filter_entry.focus_set())
        self.filter_entry.bind("<FocusIn>", lambda _: self.search_hint.place_forget())
        self.filter_entry.bind("<FocusOut>", lambda _: self.search_hint.place(x=0, y=0) if not self.search.get() else None)
        self.filter_entry.bind("<Escape>", lambda _: self.search.set(""))
        tree_wrap = frame(side, t.nav)
        tree_wrap.grid(row=3, column=0, sticky="nsew", padx=7, pady=2)
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_wrap, show="tree", style="Nav.Treeview", selectmode="browse",
                                 takefocus=True, height=4)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(tree_wrap, command=self.tree.yview)
        vs.grid(row=0, column=1, sticky="ns")
        hs = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.tree.xview)
        hs.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=auto_scroll(vs), xscrollcommand=auto_scroll(hs))
        self.tree_font = tkfont.Font(root=self.root, font=(t.font, 10))
        self.tree.column("#0", width=210, minwidth=20)
        self.tree.bind("<<TreeviewSelect>>", self.tree_selected)
        self.tree.bind("<Button-3>", self.context_menu)
        watch(self.search, lambda _: self.refresh_tree())
        foot = frame(side, t.nav, padx=14, pady=13)
        foot.grid(row=4, column=0, sticky="ew")
        frame(foot, t.nav_sel, height=1).pack(fill="x", pady=(0, 13))
        env_head = frame(foot, t.nav)
        env_head.pack(fill="x")
        label(env_head, "Ambiente padrão", 9, t.nav_muted, bold=True).pack(side="left")
        button(env_head, "Gerenciar", self.environments, "Link.Nav.TButton").pack(side="right")
        self.default_wrap = frame(foot, t.nav)
        self.default_wrap.pack(fill="x", pady=(4, 12))
        self.refresh_default()
        share = frame(foot, t.nav)
        share.pack(fill="x")
        for col, (name, cb) in enumerate((("Importar", self.import_file), ("Exportar", self.export_selected))):
            share.columnconfigure(col, weight=1, uniform="share")
            button(share, name, cb, "Nav.TButton").grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0))

    def refresh_default(self):
        clear(self.default_wrap)
        def choose(value):
            self.state["default_env"] = value
            self.changed()
            self.show()
        choice_ids(self.default_wrap, env_choices(self.state, False), self.state["default_env"], choose).pack(fill="x")

    def refresh_tree(self):
        opened = {n["id"] for n, _ in walk(self.state["roots"])
                  if self.tree.exists(n["id"]) and self.tree.item(n["id"], "open")}
        self.tree.delete(*self.tree.get_children())
        min_width = 60
        query = self.search.get().strip().casefold()
        selected_path = self.path
        expanded = opened | {n["id"] for n in selected_path[:-1]}
        def insert(n, parent, show_all=False, depth=0):
            nonlocal min_width
            title = (n["method"] + "   " if n["kind"] == "request" else "") + n["name"]
            hit = not query or show_all or query in title.casefold()
            key = n["id"]
            self.tree.insert(parent, "end", iid=key, text=title, image=self.icons[n["kind"]],
                             open=bool(query) or key in expanded)
            visible = False
            for child in n.get("children", []):
                visible |= insert(child, key, hit, depth+1)
            if not hit and not visible:
                self.tree.delete(key)
                return False
            min_width = max(min_width, self.tree_font.measure(title) + 45 + depth*18)
            return True
        for n in self.state["roots"]:
            insert(n, "")
        self.tree.column("#0", minwidth=min_width, width=min_width)
        if self.tree.exists(self.selected) and self.selected:
            self.tree.selection_set(self.selected)
            self.tree.see(self.selected)

    def tree_selected(self, _):
        selected = self.tree.selection()
        if selected and selected[0] != self.selected:
            self.select(selected[0], sync=False)

    def select(self, key, *, sync=True):
        self.selected = self.state["selected"] = key
        self.page, self.response_page = "params", "body"
        self.body_mode = "auto"
        if sync:
            if self.search.get():
                self.search.set("")
            self.refresh_tree()
        self.changed()
        self.show()

    def menu(self, entries, widget=None, event=None):
        menu = tk.Menu(self.root, tearoff=False, bg=Theme.card, fg=Theme.ink,
                       activebackground=Theme.accent_soft, activeforeground=Theme.ink)
        for name, cmd in entries:
            if cmd:
                menu.add_command(label=name, command=cmd)
            else:
                menu.add_separator()
        try:
            x, y = (event.x_root, event.y_root) if event else (widget.winfo_rootx(), widget.winfo_rooty()+widget.winfo_height())
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def new_menu(self):
        self.menu([("Nova requisição", lambda: self.new("request")), ("Nova pasta", lambda: self.new("folder")),
                   ("Nova coleção", lambda: self.new("collection"))], self.new_button)

    def item_menu(self, widget=None, event=None):
        self.menu([("Nova requisição", lambda: self.new("request")), ("Nova pasta", lambda: self.new("folder")),
                   ("", None), ("Renomear", self.rename), ("Mover para…", self.move),
                   ("Exportar…", self.export_selected), ("Excluir…", self.delete)], widget, event)

    def context_menu(self, event):
        key = self.tree.identify_row(event.y)
        if key:
            self.tree.selection_set(key)
            if key != self.selected:
                self.select(key, sync=False)
            self.item_menu(event=event)

    def new(self, kind):
        path = self.path
        name = simpledialog.askstring(TYPES[kind], f"Nome da {TYPES[kind].lower()}", parent=self.root)
        if not name or not name.strip():
            return
        if kind == "collection":
            siblings = self.state["roots"]
        else:
            parent = next((n for n in reversed(path) if n["kind"] != "request"), None)
            if parent is None:
                parent = make_node("collection", fresh_name("Minha coleção", self.state["roots"]))
                self.state["roots"].append(parent)
            if len(path_for(self.state, parent["id"])) > 80:
                messagebox.showerror(APP, "Limite de 80 níveis de pastas excedido.", parent=self.root)
                return
            siblings = parent["children"]
        node = make_node(kind, name.strip())
        siblings.append(node)
        self.select(node["id"])

    def rename(self):
        if self.path:
            n = self.path[-1]
            name = simpledialog.askstring("Renomear", "Nome", initialvalue=n["name"], parent=self.root)
            if name and name.strip():
                n["name"] = name.strip()
                self.refresh_tree()
                self.changed()
                self.show()

    def move(self):
        path = self.path
        if not path or len(path) == 1:
            messagebox.showinfo(APP, "As coleções ficam na raiz do espaço de trabalho.", parent=self.root)
            return
        n = path[-1]
        choices = [(dest, p) for dest, p in walk(self.state["roots"])
                   if dest["kind"] != "request" and n["id"] not in [a["id"] for a in p]
                   and dest["id"] != path[-2]["id"]]
        if not choices:
            messagebox.showinfo(APP, "Crie outra pasta ou coleção para mover este item.", parent=self.root)
            return
        win = modal(self.root, "Mover item")
        box = frame(win, padx=18, pady=14)
        box.pack(fill="both", expand=True)
        label(box, "Pasta de destino", 12, bold=True).pack(anchor="w", pady=(0, 8))
        dest = ttk.Combobox(box, values=[" / ".join(a["name"] for a in p) for _, p in choices], state="readonly")
        dest.pack(fill="x")
        dest.current(0)
        def apply():
            parent, p = choices[dest.current()]
            height = max(len(child_path) for _, child_path in walk([n]))
            if len(p) + height > 81:
                messagebox.showerror(APP, "Limite de 80 níveis de pastas excedido.", parent=win)
                return
            path[-2]["children"].remove(n)
            parent["children"].append(n)
            win.destroy()
            self.select(n["id"])
        button(box, "Mover", apply, "Primary.TButton").pack(anchor="e", pady=12)
        place_window(win, self.root, 430, 160)

    def delete(self):
        path = self.path
        if not path:
            return
        n = path[-1]
        suffix = " e todo o seu conteúdo" if n.get("children") else ""
        if messagebox.askyesno("Excluir item", f'Excluir “{n["name"]}”{suffix}?', parent=self.root):
            for child, _ in walk([n]):
                job = self.jobs.pop(child["id"], None)
                if job:
                    job.cancel()
                self.replies.pop(child["id"], None)
            siblings = self.state["roots"] if len(path) == 1 else path[-2]["children"]
            siblings.remove(n)
            key = path[-2]["id"] if len(path) > 1 else (siblings[0]["id"] if siblings else "")
            self.select(key)

    def show(self):
        clear(self.content)
        self.method_box = self.method_var = None
        path = self.path
        if not path:
            self.crumb.configure(text="Espaço de trabalho")
            group = frame(self.content, padx=20, pady=20)
            group.pack(fill="both", expand=True)
            label(group, "Suas coleções", 21, bold=True).pack(anchor="w")
            button(group, "+ Nova coleção", lambda: self.new("collection"), "Primary.TButton").pack(anchor="w", pady=15)
            return
        n = path[-1]
        self.crumb.configure(text="   /   ".join(["Espaço de trabalho", *[a["name"] for a in path[:-1]]]))
        top = frame(self.content, padx=16, pady=12)
        top.pack(fill="x")
        options = button(top, "Opções ▾", lambda: self.item_menu(options), "Quiet.TButton")
        options.pack(side="right")
        label(top, n["name"], 20, bold=True).pack(side="left", fill="x", expand=True)
        if n["kind"] == "request":
            self.request_view(n)
        else:
            self.editor = frame(self.content, padx=16, pady=8)
            self.editor.pack(fill="both", expand=True)
            self.draw_editor()

    def request_view(self, n):
        url_bar = frame(self.content, padx=16, pady=3)
        url_bar.pack(fill="x")
        self.method_var = tk.StringVar(value=n["method"])
        self.method_box = ttk.Combobox(url_bar, textvariable=self.method_var, values=METHODS,
                                      style="Method.TCombobox", width=9, font=(Theme.mono, 10, "bold"))
        self.method_box.pack(side="left", ipady=2)
        def method_changed(value):
            old = n["method"]
            n["method"] = value
            if self.tree.exists(n["id"]):
                self.tree.item(n["id"], text=value + "   " + n["name"])
            if (old == "CONNECT") != (value == "CONNECT"):
                self.target_panel(n)
            self.changed()
        watch(self.method_var, method_changed)
        self.url_entry = entry(url_bar, n, "url", self.changed, font=(Theme.mono, 11), width=8)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=6, ipady=2)
        self.send_button = button(url_bar, "Enviar", self.send, "Primary.TButton", width=8)
        self.send_button.pack(side="right", ipady=1)
        self.target_slot = frame(self.content)
        self.target_slot.pack(fill="x")
        self.target_panel(n)
        frame(self.content, height=9).pack(fill="x")
        panes = tk.PanedWindow(self.content, orient="vertical", bg=Theme.bg, sashwidth=7,
                               sashrelief="flat", bd=0, showhandle=False, opaqueresize=True)
        panes.pack(fill="both", expand=True)
        self.editor = frame(panes, padx=16, pady=5)
        self.response = frame(panes, padx=16, pady=10)
        panes.add(self.editor, minsize=102, stretch="always")
        panes.add(self.response, minsize=95, stretch="always")
        self.draw_editor()
        self.draw_response()
        def first_size(event):
            if event.height > 100:
                panes.sash_place(0, 0, int(event.height * .47))
                panes.unbind("<Configure>", handler)
        handler = panes.bind("<Configure>", first_size)

    def target_panel(self, n):
        clear(self.target_slot)
        if n["method"] == "CONNECT":
            inner = frame(self.target_slot, padx=16, pady=5)
            inner.pack(fill="x")
            label(inner, "Destino do túnel (host:porta)", 9, Theme.muted).pack(side="left", padx=(0, 8))
            entry(inner, n, "target", self.changed, width=30).pack(side="left")

    def set_page(self, key):
        self.page = key
        self.draw_editor()

    def draw_editor(self):
        clear(self.editor)
        path = self.path
        n = path[-1]
        req = n["kind"] == "request"
        options = ([("params", "Parâmetros"), ("headers", "Cabeçalhos"), ("body", "Corpo")]
                   if req else [("items", "Itens")])
        options.extend([("auth", "Autenticação"), ("env", "Ambiente")])
        if self.page not in dict(options):
            self.page = options[0][0]
        tab_bar(self.editor, options, self.page, self.set_page)
        area = frame(self.editor, pady=10)
        area.pack(fill="both", expand=True)
        if self.page in ("params", "headers"):
            RowEditor(area, n[self.page], self.changed, add_label="Adicionar parâmetro" if self.page == "params" else "Adicionar cabeçalho")
        elif self.page == "body":
            self.body_editor(area, n)
        elif self.page == "auth":
            self.auth_editor(area, path)
        elif self.page == "env":
            self.environment_editor(area, path)
        elif self.page == "items":
            self.items_editor(area, n)

    def items_editor(self, area, n):
        bar = frame(area)
        bar.pack(fill="x", pady=(0, 8))
        count = len(n["children"])
        label(bar, f"{count} " + ("item" if count == 1 else "itens"), 10, Theme.muted).pack(side="left")
        button(bar, "+ Requisição", lambda: self.new("request")).pack(side="right")
        button(bar, "+ Pasta", lambda: self.new("folder"), "Quiet.TButton").pack(side="right", padx=5)
        listing = ttk.Treeview(area, columns=("name", "type"), show="headings", selectmode="browse", height=3)
        for k, text, width in (("name", "Nome", 280), ("type", "Tipo / método", 130)):
            listing.heading(k, text=text, anchor="w")
            listing.column(k, anchor="w", width=width, minwidth=50)
        scroll = ttk.Scrollbar(area, command=listing.yview)
        listing.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        listing.pack(fill="both", expand=True)
        for child in n["children"]:
            listing.insert("", "end", iid=child["id"], values=(child["name"], child.get("method", TYPES[child["kind"]])))
        def open_item(_):
            if listing.selection():
                self.select(listing.selection()[0])
        listing.bind("<Double-1>", open_item)
        listing.bind("<Return>", open_item)

    def body_editor(self, area, n):
        bar = frame(area)
        bar.pack(fill="x", pady=(0, 7))
        label(bar, "Formato", 9, Theme.muted, bold=True).pack(side="left", padx=(0, 8))
        def change(kind):
            n["body_kind"] = kind
            self.changed()
            self.draw_editor()
        choice_ids(bar, list(BODIES.items()), n["body_kind"], change, 14).pack(side="left")
        if n["body_kind"] in ("json", "text"):
            def edited(value):
                n["body"] = value
                self.changed()
            text_area(area, n["body"], changed=edited)
        elif n["body_kind"] == "form":
            RowEditor(area, n["form"], self.changed, add_label="Adicionar campo")
        elif n["body_kind"] == "file":
            def choose():
                filename = filedialog.askopenfilename(parent=self.root, title="Arquivo para enviar")
                if filename:
                    n["file"] = filename
                    self.changed()
                    self.draw_editor()
            button(area, "Escolher arquivo…", choose).pack(anchor="w")
            label(area, n["file"] or "Nenhum arquivo selecionado", 9, Theme.muted).pack(anchor="w", pady=5)

    def auth_editor(self, area, path):
        n = path[-1]
        auth = n["auth"]
        group = frame(area)
        group.pack(fill="x")
        label(group, "Tipo", 9, Theme.muted, bold=True).pack(side="left", padx=(0, 8))
        def choose(mode):
            auth["mode"] = mode
            self.changed()
            self.draw_editor()
        choice_ids(group, list(AUTH.items()), auth["mode"], choose, 19).pack(side="left")
        if auth["mode"] == "inherit":
            effective, origin = auth_for(path[:-1])
            label(area, f'{AUTH[effective["mode"]]} · Herdado de {origin}', 10, Theme.muted).pack(anchor="w", pady=10)
        elif auth["mode"] in ("bearer", "basic"):
            fields = [("token", "Token")] if auth["mode"] == "bearer" else [("username", "Usuário"), ("password", "Senha")]
            form = frame(area)
            form.pack(fill="x", pady=7)
            form.columnconfigure(1, weight=1)
            for i, (key, caption) in enumerate(fields):
                label(form, caption, 9, Theme.muted).grid(row=i, column=0, sticky="w", padx=(0, 10), pady=2)
                entry(form, auth, key, self.changed, show="" if key == "username" else "•").grid(row=i, column=1, sticky="ew", pady=2)

    def environment_editor(self, area, path):
        n = path[-1]
        bar = frame(area)
        bar.pack(fill="x")
        def choose(value):
            n["env"] = value
            self.changed()
            self.draw_editor()
        choice_ids(bar, env_choices(self.state), n["env"], choose).pack(side="left")
        button(bar, "Gerenciar ambientes", self.environments, "Quiet.TButton").pack(side="left", padx=5)
        eid, origin = env_for(self.state, path)
        env = find_env(self.state, eid)
        name = env["name"] if env else "Sem ambiente"
        label(area, f"{name} · Definido em {origin}", 10, Theme.muted).pack(anchor="w", pady=9)
        if env:
            lines = [r["key"] + "  =  " + ("••••••" if r["secret"] or SECRET_NAME.search(r["key"]) else r["value"])
                     for r in env["variables"] if r["key"].strip()]
            text_area(area, "\n".join(lines), wrap="word")

    def short_send(self, _):
        if self.path and self.path[-1]["kind"] == "request" and self.selected not in self.jobs:
            self.send()
        return "break"

    def send(self):
        key = self.selected
        if key in self.jobs:
            self.jobs.pop(key).cancel()
            self.remember(key, Reply(error="Requisição cancelada."))
            self.draw_response()
            return
        try:
            prepared = prepare(self.state, self.path)
        except (ValueError, OSError, UnicodeError) as exc:
            self.remember(key, Reply(error=str(exc)))
            self.draw_response()
            return
        job = self.jobs[key] = Job()
        def run():
            self.events.put((key, job, perform(prepared, job)))
        threading.Thread(target=run, daemon=True, name="rota-http").start()
        self.draw_response()

    def remember(self, key, reply):
        self.replies[key] = reply
        if key == self.selected:
            self.body_mode = "auto"
        self.replies.move_to_end(key)
        if len(self.replies) > 30:
            self.replies.popitem(last=False)

    def poll(self):
        while True:
            try:
                key, job, reply = self.events.get_nowait()
            except queue.Empty:
                break
            if self.jobs.get(key) is job:
                del self.jobs[key]
                self.remember(key, reply)
                if key == self.selected:
                    self.draw_response()
        self.poll_timer = self.root.after(75, self.poll)

    def set_response_page(self, key):
        self.response_page = key
        self.draw_response()

    def set_body_mode(self, mode):
        self.body_mode = mode
        self.draw_response()

    def draw_response(self):
        clear(self.response)
        reply = self.replies.get(self.selected)
        busy = self.selected in self.jobs
        self.send_button.configure(text="Cancelar" if busy else "Enviar")
        bar = frame(self.response)
        bar.pack(fill="x", pady=(0, 5))
        label(bar, "Resposta", 13, bold=True).pack(side="left")
        if reply and not busy:
            status = "Falha" if reply.error else f"{reply.status} {reply.reason}".strip()
            if reply.error or reply.status >= 400:
                fg, bg = Theme.danger, Theme.danger_soft
            elif reply.status >= 300:
                fg, bg = Theme.amber, Theme.amber_soft
            else:
                fg, bg = Theme.accent, Theme.accent_soft
            label(bar, status, 9, fg, bg=bg, bold=True, padx=7, pady=2).pack(side="left", padx=10)
            info = f"{reply.elapsed * 1000:,.0f} ms".replace(",", ".")
            if not reply.error:
                size = len(reply.data)
                amount = f"{size} B" if size < 1024 else f"{size / 1024:.1f} KiB".replace(".", ",")
                info += "    ·    " + ("≥ " if reply.truncated else "") + amount
            label(bar, info, 9, Theme.muted, mono=True).pack(side="right")
        if busy or not reply:
            empty = frame(self.response, Theme.bg, padx=10, pady=8)
            empty.pack(fill="both", expand=True, pady=(6, 1))
            middle = frame(empty, Theme.bg)
            middle.place(relx=.5, rely=.5, anchor="center")
            label(middle, "Aguardando o servidor…" if busy else "Envie a requisição para ver a resposta.",
                  11, Theme.muted).pack()
            if not busy:
                label(middle, "Ctrl + Enter", 9, Theme.muted, mono=True).pack(pady=(4, 0))
            return
        if reply.error:
            text_area(self.response, reply.error, wrap="word")
            return
        view = (body_view(reply, self.body_mode) if self.response_page == "body" else
                BodyView("raw", "\n".join(k + ": " + v for k, v in reply.headers)))
        photo = None
        if view.image:
            try:
                photo = tk.PhotoImage(master=self.response, data=view.image, format="png")
                width = max(240, self.response.winfo_width() - 40)
                height = max(90, self.response.winfo_height() - 100)
                scale = max(1, (photo.width()+width-1)//width, (photo.height()+height-1)//height)
                if scale > 1:
                    photo = photo.subsample(scale)
            except tk.TclError:
                photo = None
                view = hex_view(reply.data, "Não foi possível ler o PNG. Exibindo os bytes recebidos.")

        def copy_text():
            self.root.clipboard_clear()
            self.root.clipboard_append(base64.b64encode(view.image).decode("ascii") if view.image else view.text)
            copy_btn.configure(text="Copiado")
        controls = frame(self.response)
        controls.pack(fill="x")
        copy_btn = button(controls, "Copiar Base64" if view.image else "Copiar", copy_text, "Quiet.TButton")
        copy_btn.pack(side="right")
        if self.response_page == "body" and reply.data:
            choices = list(VIEW_MODES.items())
            choices[0] = ("auto", f"Auto · {VIEW_MODES[view.mode]}" if self.body_mode == "auto" else "Automático")
            choice_ids(controls, choices, self.body_mode, self.set_body_mode, width=16).pack(side="right", padx=5)
        tabs = frame(controls)
        tabs.pack(side="left", fill="x", expand=True)
        tab_bar(tabs, [("body", "Corpo"), ("headers", f"Cabeçalhos ({len(reply.headers)})")],
                self.response_page, self.set_response_page)
        if view.note:
            label(self.response, view.note, 9, Theme.muted, wraplength=max(380, self.response.winfo_width()-55),
                  justify="left").pack(anchor="w", pady=(3, 0))
        if photo is not None:
            picture = tk.Label(self.response, image=photo, bg=Theme.card)
            picture.image = photo
            picture.pack(fill="both", expand=True)
        elif view.columns:
            response_table(self.response, view)
        elif view.mode == "base64":
            text_area(self.response, "\n".join(view.text[i:i+76] for i in range(0, len(view.text), 76)))
        else:
            text_area(self.response, view.text, wrap="word" if view.mode == "text" else "none")

    def export_selected(self):
        if self.path:
            self.export(path=self.path)
        else:
            messagebox.showinfo(APP, "Selecione um item para exportar.", parent=self.root)

    def export(self, *, path=(), environment=None, parent=None):
        parent = parent or self.root
        source = environment if environment is not None else path[-1]
        win = modal(parent, "Exportar para JSON")
        box = frame(win, padx=20, pady=16)
        box.pack(fill="both", expand=True)
        label(box, "Exportar " + source["name"], 14, bold=True).pack(anchor="w")
        include = tk.BooleanVar(win, False)
        ttk.Checkbutton(box, text="Incluir senhas, tokens e variáveis secretas", variable=include).pack(anchor="w", pady=(12, 4))
        label(box, "Revise a URL e o corpo antes de compartilhar. Esses campos são copiados integralmente.",
              9, Theme.muted, wraplength=395, justify="left").pack(anchor="w")
        def save_as():
            clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", source["name"]).strip(" .")[:100] or APP.lower()
            filename = filedialog.asksaveasfilename(parent=win, title="Salvar arquivo de compartilhamento",
                       initialfile=clean_name + ".rota.json", defaultextension=".json", filetypes=[("Arquivo JSON", "*.json")])
            if not filename:
                return
            try:
                if Path(filename).resolve() == self.store.path.resolve():
                    raise ValueError("Escolha um arquivo diferente do espaço de trabalho ativo.")
                write_json(filename, share_package(self.state, path=path, environment=environment, secrets=include.get()))
            except (OSError, ValueError) as exc:
                messagebox.showerror("Exportar", str(exc), parent=win)
                return
            win.destroy()
            self.status.set("Arquivo exportado")
        button(box, "Salvar arquivo…", save_as, "Primary.TButton").pack(anchor="e", pady=(12, 0))
        place_window(win, parent, 460, 220)

    def import_file(self):
        filename = filedialog.askopenfilename(parent=self.root, title=f"Importar do {APP}",
                                              filetypes=[("Arquivo JSON", "*.json"), ("Todos", "*.*")])
        if not filename:
            return
        try:
            roots, envs = import_package(self.state, read_json(filename), self.path)
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            messagebox.showerror("Importar", f"Importação cancelada.\n\n{exc}", parent=self.root)
            return
        self.refresh_default()
        self.select(self.state["selected"])
        if envs and not roots:
            self.environments(self.state["environments"][-1]["id"])

    def environments(self, selected=None):
        if self.env_window and self.env_window.winfo_exists():
            self.env_window.lift()
            return
        self.env_window = EnvironmentWindow(self, selected).win


class ProxyWindow:
    def __init__(self, app):
        self.app = app
        self.win = modal(app.root, f"Proxy · {APP}")
        self.win.resizable(False, False)
        current = app.state.get("proxy", PROXY_DEFAULTS)
        self.values = {}
        self.entries = {}
        for key, value in current.items():
            var_type = tk.BooleanVar if isinstance(value, bool) else tk.StringVar
            self.values[key] = var_type(self.win, value=value)

        body = frame(self.win, padx=22, pady=16)
        body.pack(fill="both", expand=True)
        label(body, "Proxy de rede", 16, bold=True).pack(anchor="w")
        label(body, "Conexão usada pelas requisições deste espaço de trabalho.", 10,
              Theme.muted).pack(anchor="w", pady=(3, 14))
        toggle = ttk.Checkbutton(body, text="Usar um proxy HTTP", variable=self.values["enabled"],
                                 command=self.update_form)
        toggle.pack(anchor="w")
        self.details = frame(body)
        self.details.pack(fill="x", pady=(12, 0))
        self.details.columnconfigure(0, weight=1)
        self.add_field(self.details, "host", "Servidor", 0, 0, width=30)
        self.add_field(self.details, "port", "Porta", 0, 1, width=8)
        self.add_field(self.details, "bypass", "Conexão direta para (opcional)", 1, 0, span=2)
        label(self.details, "Separe os destinos por vírgula. Ex.: localhost, *.empresa.com", 9,
              Theme.muted).grid(row=2, column=0, columnspan=2, sticky="w")
        self.auth_toggle = ttk.Checkbutton(self.details, text="Usar autenticação Basic",
                                          variable=self.values["authenticate"], command=self.update_form)
        self.auth_toggle.grid(row=3, column=0, columnspan=2, sticky="w", pady=(14, 0))
        self.credentials = frame(self.details)
        self.credentials.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        for col, (key, caption) in enumerate((("username", "Usuário"), ("password", "Senha"))):
            self.credentials.columnconfigure(col, weight=1, uniform="auth")
            self.add_field(self.credentials, key, caption, 0, col, width=16)
        self.error = label(body, "", 10, Theme.danger, wraplength=390, justify="left")
        frame(self.win, Theme.line, height=1).pack(fill="x")
        actions = frame(self.win, padx=22, pady=12)
        actions.pack(fill="x")
        button(actions, "Salvar", self.apply, "Primary.TButton").pack(side="right")
        button(actions, "Cancelar", self.win.destroy, "Quiet.TButton").pack(side="right", padx=(0, 8))
        self.update_form(initial=True)
        toggle.focus_set()

    def add_field(self, parent, key, caption, row_index, col, *, span=1, width=20):
        box = frame(parent)
        box.grid(row=row_index, column=col, columnspan=span, sticky="ew",
                 padx=(10 if col else 0, 0), pady=(0, 5))
        label(box, caption, 10, bold=True).pack(anchor="w", pady=(0, 3))
        widget = ttk.Entry(box, textvariable=self.values[key], width=width,
                           show="•" if key == "password" else "")
        widget.pack(fill="x")
        self.entries[key] = widget

    def fit(self, initial=False):
        self.win.update_idletasks()
        w = max(445, self.win.winfo_reqwidth())
        h = self.win.winfo_reqheight()
        if initial:
            place_window(self.win, self.app.root, w, h)
        else:
            top = max(0, min(self.win.winfo_y(), self.win.winfo_screenheight()-h-70))
            self.win.geometry(f"{w}x{h}+{max(0,self.win.winfo_x())}+{top}")

    def update_form(self, initial=False):
        if self.values["enabled"].get():
            self.details.pack(fill="x", pady=(12, 0))
        else:
            self.details.pack_forget()
        if self.values["authenticate"].get():
            self.credentials.grid()
        else:
            self.credentials.grid_remove()
        self.error.pack_forget()
        self.fit(initial)

    def apply(self):
        draft = {key: var.get() for key, var in self.values.items()}
        try:
            configured_proxy(draft)
        except ProxyInputError as exc:
            self.error.configure(text=str(exc))
            self.error.pack(anchor="w", pady=(8, 0))
            self.fit()
            self.entries[exc.field_name].focus_set()
            return
        previous = self.app.state.get("proxy")
        self.app.state["proxy"] = draft
        if not self.app.save(notify=True):
            if previous is None:
                del self.app.state["proxy"]
            else:
                self.app.state["proxy"] = previous
            return
        self.app.refresh_proxy()
        self.win.destroy()


class EnvironmentWindow:
    def __init__(self, app, selected):
        self.app = app
        self.envs = app.state["environments"]
        self.win = modal(app.root, f"Ambientes · {APP}")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _: self.close())
        self.win.minsize(560, 310)
        place_window(self.win, app.root, 780, 475)
        self.win.columnconfigure(1, weight=1)
        self.win.rowconfigure(0, weight=1)
        side = frame(self.win, Theme.bg, padx=12, pady=14, width=190)
        side.grid(row=0, column=0, sticky="nsew")
        label(side, "Ambientes", 14, bold=True).pack(anchor="w", pady=(0, 9))
        self.list = tk.Listbox(side, width=18, exportselection=False, bg=Theme.bg, fg=Theme.ink,
                              selectbackground=Theme.accent_soft, selectforeground=Theme.accent,
                              relief="flat", bd=0, highlightthickness=0, activestyle="none",
                              font=(Theme.font, 11))
        self.list.pack(fill="both", expand=True)
        self.list.bind("<<ListboxSelect>>", lambda _: self.selected())
        button(side, "+ Ambiente", self.add).pack(fill="x", pady=(9, 0))
        self.area = frame(self.win, padx=16, pady=14)
        self.area.grid(row=0, column=1, sticky="nsew")
        foot = frame(self.win, padx=15, pady=9)
        foot.grid(row=1, column=0, columnspan=2, sticky="ew")
        label(foot, "Use {{variavel}} na URL, nos cabeçalhos, no corpo ou na autenticação.",
              9, Theme.muted, wraplength=450, justify="left").pack(side="left")
        button(foot, "Concluir", self.close, "Primary.TButton").pack(side="right")
        self.refresh(selected or app.state["default_env"])

    def refresh(self, eid=None):
        self.list.delete(0, "end")
        for env in self.envs:
            self.list.insert("end", env["name"])
        if self.envs:
            i = next((i for i, e in enumerate(self.envs) if e["id"] == eid), 0)
            self.list.selection_set(i)
            self.list.see(i)
        self.selected()

    def selected(self):
        clear(self.area)
        idx = self.list.curselection()
        if not idx:
            label(self.area, "Crie um ambiente para definir variáveis.", 11, Theme.muted).pack(anchor="w")
            return
        env = self.envs[idx[0]]
        label(self.area, env["name"], 16, bold=True).pack(anchor="w")
        actions = frame(self.area)
        actions.pack(fill="x", pady=(4, 10))
        for name, fn in (("Renomear", lambda: self.rename(env)), ("Exportar…", lambda: self.app.export(environment=env, parent=self.win)),
                         ("Excluir…", lambda: self.delete(env))):
            button(actions, name, fn, "Quiet.TButton").pack(side="left")
        RowEditor(self.area, env["variables"], self.app.changed, variables=True, add_label="Adicionar variável")

    def add(self):
        name = simpledialog.askstring("Novo ambiente", "Nome do ambiente", parent=self.win)
        if name and name.strip():
            env = dict(id=uid(), name=fresh_name(name.strip(), self.envs), variables=[])
            self.envs.append(env)
            self.app.changed()
            self.refresh(env["id"])

    def rename(self, env):
        name = simpledialog.askstring("Renomear ambiente", "Nome", initialvalue=env["name"], parent=self.win)
        if name and name.strip():
            env["name"] = fresh_name(name.strip(), [e for e in self.envs if e != env])
            self.app.changed()
            self.refresh(env["id"])

    def delete(self, env):
        if messagebox.askyesno("Excluir ambiente", f'Excluir “{env["name"]}”? Os itens vinculados passarão a herdar o ambiente.',
                               parent=self.win):
            eid = env["id"]
            for n, _ in walk(self.app.state["roots"]):
                if n["env"] == eid:
                    n["env"] = "inherit"
            if self.app.state["default_env"] == eid:
                self.app.state["default_env"] = "none"
            self.envs.remove(env)
            self.app.changed()
            self.refresh()

    def close(self):
        self.win.destroy()
        self.app.refresh_default()
        self.app.show()


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.withdraw()
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    directory = base / WORKSPACE_DIR
    try:
        store = Workspace(directory)
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as exc:
        messagebox.showerror(APP, f"Não foi possível abrir o espaço de trabalho.\n{directory}\n\n{exc}", parent=root)
        root.destroy()
        return
    App(root, store)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
