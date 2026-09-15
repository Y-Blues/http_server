"""
ApiServlet: HTTP adapter over the endpoints_storage use cases (ICrud, IDrafts, IItemCatalog).
"""

import json
import logging

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
        path: str = "/api",
    ):
        self._crud = crud
        self._drafts = drafts
        self._catalog = catalog
        self._authentications = authentications

    async def start(self):
        pass

    async def stop(self):
        pass

    async def handle(self, request: HttpRequest) -> HttpResponse:
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

    async def _authenticate(self, request):
        authentications = list(self._authentications)
        if not authentications:
            return None
        return await authentications[0].authenticate(request.headers)

    async def _route(self, method, segments, params, fields, subject):
        if not segments:
            raise NotFound("not found")
        family, rest = segments[0], segments[1:]
        if family == "crud":
            return await self._route_crud(method, rest, params, fields, subject)
        if family == "drafts":
            return await self._route_drafts(method, rest, params, fields, subject)
        if family == "items":
            return await self._route_items(method, rest, subject)
        raise NotFound("not found")

    async def _route_crud(self, method, rest, params, fields, subject):
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

    async def _route_drafts(self, method, rest, params, fields, subject):
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

    async def _route_items(self, method, rest, subject):
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

    async def _item_id(self, plural, subject):
        item = await self._catalog.get_item_by_plural(plural, subject)
        return item["id"]


def _segments(request) -> list:
    return [segment for segment in request.sub_path.strip("/").split("/") if segment]


def _decode_body(request):
    if not request.body:
        return None
    try:
        return json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidRequest(f"invalid JSON body: {error}") from None


def _ok(status, payload) -> HttpResponse:
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
    return HttpResponse(status=status, body=body, content_type="application/json")


def _error(status, error) -> HttpResponse:
    message = error if isinstance(error, str) else str(error)
    body = json.dumps({"status": status, "meta": {"type": "object"}, "data": {"error": message}}).encode()
    return HttpResponse(status=status, body=body, content_type="application/json")
