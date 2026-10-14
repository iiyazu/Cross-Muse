"""The hub's HTTP API: FastAPI on uvicorn, loopback only, in a thread of the hub process.

Two families with their own answer formats (both kept from the stdlib server this replaced):
  - the agent API (shim, hooks, CLI): POST with a bearer JWT; 200 {"result": ...} or 200 {"error": {code, message}}
    for a refused call, 401 for a bad token, 400/500 {"error": {code, message}} for a bad request or a crash.
  - the sidebar API (contract XMUSE2-VIEW-API v0): GET/POST; HTTP status plus a flat {"error", "message"}.
Handlers are the Hub's own synchronous methods; each runs in the thread pool (long polls wait up to 30 s there, so
the pool is sized for them). No OpenAPI or docs pages: nothing is served that is not part of the contract.
"""
import json
import logging
import socket
import threading
import time

import anyio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import config
from . import room as rooms
from .tools import ToolError

log = logging.getLogger("xmuse.api")

THREADS = 256  # long polls (/v1/view, /v1/relay/poll) hold a thread each while they wait
RELAY = {"bind": "relay_bind", "unbind": "relay_unbind", "poll": "relay_poll", "delivered": "relay_delivered"}
SIDEBAR = [("GET", "/v1/view"), ("GET", "/v1/timeline"), ("POST", "/v1/act"), ("POST", "/v1/rooms"),
           ("GET", "/v1/rooms"), ("POST", "/v1/join"), ("POST", "/v1/rebind"), ("POST", "/v1/leave"),
           ("GET", "/v1/agents"), ("POST", "/v1/agents/scan"), ("POST", "/v1/agents/trial"),
           ("POST", "/v1/agents/model"), ("GET", "/v1/compact_instructions")]


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def build(hub) -> FastAPI:
    async def lifespan(app):
        anyio.to_thread.current_default_thread_limiter().total_tokens = THREADS
        yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def notify() -> None:
        with hub.relay_cv:
            hub.relay_cv.notify_all()

    async def agent_call(request: Request, fn, human: bool | None) -> JSONResponse:
        """human: True = the admin token only, False = an agent's token only, None = either. The other kind gets
        not_found, as the path does not exist for it."""
        caller = await run_in_threadpool(hub.who, request.headers.get("authorization"))
        if caller is None:
            return _err(401, "unauthorized", "bad or missing token")
        path = request.url.path
        try:
            body = json.loads(await request.body() or b"{}")
            if human is not None and (caller == config.HUMAN) != human:
                raise ToolError("not_found", f"POST {path}")
            out = await run_in_threadpool(fn, caller, body, request.headers.get("x-xmuse-session") or None,
                                          request.client.port if request.client else None)
            if not path.startswith("/v1/relay/"):
                notify()
            return JSONResponse({"result": out})
        except ToolError as e:
            return JSONResponse({"error": {"code": e.code, "message": e.message}})
        except (KeyError, TypeError, ValueError) as e:
            return _err(400, "bad_request", repr(e))
        except Exception as e:  # noqa: BLE001 - never drop the connection: answer 500 with JSON
            log.exception("unhandled error in POST %s", path)
            return _err(500, "internal_error", f"{type(e).__name__}: {e}")

    # ---- the agent API -----------------------------------------------------------------------------------------
    @app.post("/v1/relay/{name}")
    async def relay(name: str, request: Request):
        if name not in RELAY:
            return await agent_call(request, lambda *a: _missing(request), None)
        return await agent_call(request, lambda c, b, s, _: getattr(hub, RELAY[name])(c, b, s), False)

    @app.post("/v1/tools/{name}")
    async def tool(name: str, request: Request):
        return await agent_call(request, lambda c, b, s, _: hub.tool(c, name, b.get("args", {}), s), False)

    @app.post("/v1/hooks/{vendor}")
    async def hook(vendor: str, request: Request):
        if vendor not in ("claude", "dsh"):
            return await agent_call(request, lambda *a: _missing(request), None)
        return await agent_call(request, lambda c, b, s, _: hub.hook(c, b), False)

    @app.post("/v1/shim/register")
    async def shim_register(request: Request):
        return await agent_call(request, lambda c, b, s, _: hub.register(c, b), False)

    @app.post("/v1/risk")
    async def risk(request: Request):
        return await agent_call(request, lambda c, b, s, _: hub.risk(c, b), None)

    @app.post("/v1/admin/{name}")
    async def admin(name: str, request: Request):
        fn = getattr(hub, "admin_" + name, None)
        if fn is None:
            return await agent_call(request, lambda *a: _missing(request), None)

        def call(caller, body, session, port):
            hub.require_human(name, port)
            return fn(body)
        return await agent_call(request, call, True)

    # ---- the sidebar API ---------------------------------------------------------------------------------------
    def sidebar_route(method: str, path: str) -> None:
        async def handler(request: Request):
            if method == "POST":
                try:
                    body = json.loads(await request.body() or b"{}")
                except ValueError:
                    return JSONResponse({"error": "bad_json", "message": "the body is not JSON"}, status_code=400)
            else:
                body = {}
            h = request.headers
            try:
                status, out = await run_in_threadpool(hub.sidebar, method, path, dict(request.query_params), body,
                                                      h.get("authorization"), h.get("x-xmuse-session") or None,
                                                      h.get("x-xmuse-sidebar"))
            except rooms.ApiError as e:
                status, out = e.status, {"error": e.code, "message": e.message}
                log.warning("sidebar %s %s from %s -> %s %s", method, path,
                            request.client.host if request.client else "?", status, e.code)
            except ToolError as e:
                status, out = 400, {"error": e.code, "message": e.message}
            except (KeyError, TypeError, ValueError) as e:
                status, out = 400, {"error": "bad_request", "message": repr(e)}
            except Exception as e:  # noqa: BLE001 - the sidebar needs a JSON answer
                log.exception("unhandled error in %s %s", method, path)
                status, out = 500, {"error": "internal_error", "message": f"{type(e).__name__}: {e}"}
            if method == "POST":
                notify()
            return Response(status_code=204) if status == 204 else JSONResponse(out, status_code=status)
        app.add_api_route(path, handler, methods=[method])

    for method, path in SIDEBAR:
        sidebar_route(method, path)

    # ---- anything else -----------------------------------------------------------------------------------------
    @app.get("/{rest:path}")
    async def get_missing(rest: str):
        return JSONResponse({"error": "not_found", "message": f"GET /{rest}"}, status_code=404)

    @app.post("/{rest:path}")
    async def post_missing(rest: str, request: Request):
        return await agent_call(request, lambda *a: _missing(request), None)

    return app


def _missing(request: Request):
    raise ToolError("not_found", f"POST {request.url.path}")


class Server:
    """uvicorn in a daemon thread on 127.0.0.1:<free port> (port 0: the kernel picks it; `port` is set on return)."""

    def __init__(self, app: FastAPI):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        # log_config=None: uvicorn leaves the hub's logging alone
        self.uv = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="on",
                                                timeout_graceful_shutdown=1, timeout_keep_alive=5))
        self.thread = threading.Thread(target=self.uv.run, kwargs={"sockets": [self.sock]}, daemon=True,
                                       name="xmuse-api")
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.uv.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the hub's HTTP server did not start")
            time.sleep(0.01)

    def shutdown(self) -> None:
        self.uv.should_exit = True
        self.thread.join(10)
        self.sock.close()
