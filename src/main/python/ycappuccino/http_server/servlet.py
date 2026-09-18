"""
ApiServlet: HTTP adapter over the endpoints_storage use cases (ICrud, IDrafts, IItemCatalog).
"""

import json
import logging
from typing import Any

from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.api.endpoints_storage import (
    Forbidden,
    ICrud,
    IDrafts,
    IItemCatalog,
    InvalidRequest,
    NotAuthenticated,
    NotFound,
)
from ycappuccino.api.http import HttpRequest, HttpResponse, IHttpServlet
from ycappuccino.api.http_server import IAuthentication

_logger = logging.getLogger(__name__)


class ApiServlet(IHttpServlet):

    def __init__(
        self,
        crud: ICrud,
        drafts: IDrafts,
        catalog: IItemCatalog,
        authentications: list[IAuthentication],
        services: list[IServiceEndpoint],
        path: str = "/api",
        allowed_origins: str = "",
    ) -> None:
        # allowed_origins: comma separated origins (scheme://host:port) of pages served elsewhere that may
        # call this API from a browser (CORS); empty, none may
        self._crud = crud
        self._drafts = drafts
        self._catalog = catalog
        self._authentications = authentications
        self._services = services
        self._allowed_origins = {origin.strip() for origin in allowed_origins.split(",") if origin.strip()}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def handle(self, request: HttpRequest) -> HttpResponse:
        origin = request.headers.get("origin")
        allowed = origin if origin in self._allowed_origins else None
        if request.method == "OPTIONS":
            # a browser's preflight: answered here, it never reaches a use case
            return _cross_origin(HttpResponse(status=204, body=b"", content_type="text/plain"), allowed, preflight=True)
        return _cross_origin(await self._handle(request), allowed)

    async def _handle(self, request: HttpRequest) -> HttpResponse:
        try:
            subject = await self._authenticate(request)
            fields = _decode_body(request)
            segments = _segments(request)
            return await self._route(request.method, segments, request.query, fields, subject)
        except NotAuthenticated as error:
            return _error(401, error)
        except Forbidden as error:
            return _error(403, error)
        except NotFound as error:
            return _error(404, error)
        except InvalidRequest as error:
            return _error(400, error)
        except Exception:
            _logger.exception("unhandled error handling %s %s", request.method, request.path)
            return _error(500, "internal error")

    async def _authenticate(self, request: HttpRequest) -> dict | None:
        # several providers coexist (a user JWT, a peer HMAC signature): the first to recognize the
        # request decides its subject
        for authentication in list(self._authentications):
            subject = await authentication.authenticate(request.headers, request.method, request.path, request.body)
            if subject is not None:
                return subject
        return None

    async def _route(
        self, method: str, segments: list, params: dict, fields: Any, subject: dict | None
    ) -> HttpResponse:
        if not segments:
            raise NotFound("not found")
        family, rest = segments[0], segments[1:]
        if family == "crud":
            return await self._route_crud(method, rest, params, fields, subject)
        if family == "drafts":
            return await self._route_drafts(method, rest, params, fields, subject)
        if family == "items":
            return await self._route_items(method, rest, subject)
        if family == "services":
            return await self._route_services(method, rest, params, fields, subject)
        raise NotFound("not found")

    async def _route_crud(
        self, method: str, rest: list, params: dict, fields: Any, subject: dict | None
    ) -> HttpResponse:
        if len(rest) == 1:
            (plural,) = rest
            item_id = await self._item_id(plural, subject)
            if method == "GET":
                return _ok(200, await self._crud.get_many(item_id, params, subject))
            if method == "POST":
                return _ok(201, await self._crud.create(item_id, fields, subject))
            if method == "DELETE":
                count = await self._crud.delete_many(item_id, params.get("filter"), subject)
                return _ok(200, {"deleted": count})
        elif len(rest) == 2:
            plural, id = rest
            item_id = await self._item_id(plural, subject)
            if method == "GET":
                return _ok(200, await self._crud.get_one(item_id, id, params, subject))
            if method == "PUT":
                return _ok(200, await self._crud.update(item_id, id, fields, subject))
            if method == "DELETE":
                await self._crud.delete(item_id, id, subject)
                return _ok(200, None)
        raise NotFound("not found")

    async def _route_drafts(
        self, method: str, rest: list, params: dict, fields: Any, subject: dict | None
    ) -> HttpResponse:
        if len(rest) == 2:
            plural, draft = rest
            item_id = await self._item_id(plural, subject)
            if method == "GET":
                return _ok(200, await self._drafts.get_many(item_id, draft, params, subject))
        elif len(rest) == 3:
            plural, id, draft = rest
            item_id = await self._item_id(plural, subject)
            if method == "GET":
                return _ok(200, await self._drafts.get_one(item_id, id, draft, params, subject))
            if method == "PUT":
                return _ok(200, await self._drafts.save(item_id, id, draft, fields, subject))
            if method == "DELETE":
                await self._drafts.discard(item_id, id, draft, subject)
                return _ok(200, None)
        elif len(rest) == 4 and rest[3] == "publish":
            plural, id, draft, _ = rest
            item_id = await self._item_id(plural, subject)
            if method == "POST":
                return _ok(200, await self._drafts.publish(item_id, id, draft, subject))
        raise NotFound("not found")

    async def _route_items(self, method: str, rest: list, subject: dict | None) -> HttpResponse:
        if method != "GET":
            raise NotFound("not found")
        if not rest:
            return _ok(200, await self._catalog.get_items(subject))
        if len(rest) == 1:
            (plural,) = rest
            return _ok(200, await self._catalog.get_item_by_plural(plural, subject))
        if len(rest) == 2:
            plural, action = rest
            item_id = await self._item_id(plural, subject)
            if action == "schema":
                return _ok(200, await self._catalog.get_schema(item_id, subject))
            if action == "empty":
                return _ok(200, await self._catalog.get_empty(item_id, subject))
        raise NotFound("not found")

    async def _route_services(
        self, method: str, rest: list, params: dict, fields: Any, subject: dict | None
    ) -> HttpResponse:
        services = list(self._services)
        if not rest or not services:
            raise NotFound("not found")
        name, extra_path = rest[0], rest[1:]
        result = await services[0].call(name, method, extra_path, params, fields, subject)
        return _ok(200, result.body, headers=result.headers)

    async def _item_id(self, plural: str, subject: dict | None) -> str:
        item = await self._catalog.get_item_by_plural(plural, subject)
        return item["id"]


def _segments(request: HttpRequest) -> list:
    return [segment for segment in request.sub_path.strip("/").split("/") if segment]


def _decode_body(request: HttpRequest) -> Any:
    if not request.body:
        return None
    try:
        return json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidRequest(f"invalid JSON body: {error}") from None


def _ok(status: int, payload: Any, headers: dict | None = None) -> HttpResponse:
    if isinstance(payload, dict) and "items" in payload and "total" in payload:
        meta = {"type": "array", "size": payload["total"]}
        data = payload["items"]
    elif isinstance(payload, list):
        meta = {"type": "array", "size": len(payload)}
        data = payload
    elif payload is None:
        meta = {"type": "object"}
        data = {}
    else:
        meta = {"type": "object", "size": 1}
        data = payload
    body = json.dumps({"status": status, "meta": meta, "data": data}).encode()
    return HttpResponse(status=status, body=body, content_type="application/json", headers=dict(headers or {}))


def _error(status: int, error: Exception | str) -> HttpResponse:
    message = error if isinstance(error, str) else str(error)
    body = json.dumps({"status": status, "meta": {"type": "object"}, "data": {"error": message}}).encode()
    return HttpResponse(status=status, body=body, content_type="application/json")


def _cross_origin(response: HttpResponse, origin: str | None, preflight: bool = False) -> HttpResponse:
    """the CORS headers letting a page of that allowed origin read the response; none for any other"""
    if origin is None:
        return response
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    if preflight:
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    return response
