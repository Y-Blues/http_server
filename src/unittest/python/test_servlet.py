import json
import unittest

from servlet_fixtures import FakeAuthentication, FakeServiceEndpoint, SUBJECT, create_servlet

from ycappuccino.api.endpoints_service import ServiceResult
from ycappuccino.api.http import HttpRequest
from ycappuccino.http_server.servlet import _decode_body, _error, _ok, _segments


def request(method="GET", sub_path="", query=None, headers=None, body=b""):
    return HttpRequest(
        method=method, path="/api" + sub_path, prefix="/api", sub_path=sub_path,
        query=query or {}, headers=headers or {}, body=body,
    )


class TestSegmentsAndBody(unittest.TestCase):

    def test_segments(self):
        self.assertEqual(_segments(request(sub_path="")), [])
        self.assertEqual(_segments(request(sub_path="/")), [])
        self.assertEqual(_segments(request(sub_path="/crud/books")), ["crud", "books"])
        self.assertEqual(_segments(request(sub_path="/crud/books/")), ["crud", "books"])

    def test_decode_body(self):
        self.assertIsNone(_decode_body(request(body=b"")))
        self.assertEqual(_decode_body(request(body=b'{"title": "Dune"}')), {"title": "Dune"})

    def test_decode_body_rejects_invalid_json(self):
        from ycappuccino.api.endpoints_storage import InvalidRequest

        with self.assertRaises(InvalidRequest):
            _decode_body(request(body=b"{not json"))


class TestEnvelope(unittest.TestCase):

    def test_ok_wraps_a_get_many_shaped_payload_as_an_array(self):
        response = _ok(200, {"items": [{"_id": "a"}], "total": 5})

        body = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(body, {"status": 200, "meta": {"type": "array", "size": 5}, "data": [{"_id": "a"}]})

    def test_ok_wraps_a_plain_list(self):
        body = json.loads(_ok(200, [{"id": "book"}]).body)

        self.assertEqual(body, {"status": 200, "meta": {"type": "array", "size": 1}, "data": [{"id": "book"}]})

    def test_ok_wraps_none_as_an_empty_object(self):
        body = json.loads(_ok(200, None).body)

        self.assertEqual(body, {"status": 200, "meta": {"type": "object"}, "data": {}})

    def test_ok_wraps_a_dict_as_an_object(self):
        body = json.loads(_ok(200, {"_id": "dune"}).body)

        self.assertEqual(body, {"status": 200, "meta": {"type": "object", "size": 1}, "data": {"_id": "dune"}})

    def test_error_never_exposes_more_than_the_message(self):
        body = json.loads(_error(500, "internal error").body)

        self.assertEqual(body, {"status": 500, "meta": {"type": "object"}, "data": {"error": "internal error"}})


class TestHandleBasics(unittest.IsolatedAsyncioTestCase):
    """behaviors common to every route: authentication, unmatched path, malformed body"""

    async def test_authentication_sees_the_whole_request(self):
        authentication = FakeAuthentication(subject={"sub": "alice"})
        servlet, _, _, _ = create_servlet(authentications=[authentication])

        await servlet.handle(request("POST", sub_path="/unknown", headers={"authorization": "Bearer x"}, body=b"{}"))

        self.assertEqual(authentication.calls, [({"authorization": "Bearer x"}, "POST", "/api/unknown", b"{}")])

    async def test_the_first_provider_recognizing_the_request_wins(self):
        declines, accepts, never_asked = (
            FakeAuthentication(subject=None),
            FakeAuthentication(subject={"peer": "backend-1"}),
            FakeAuthentication(subject={"sub": "mallory"}),
        )
        services = FakeServiceEndpoint()
        servlet, _, _, _ = create_servlet(authentications=[declines, accepts, never_asked], services=[services])

        await servlet.handle(request("POST", sub_path="/services/ping"))

        self.assertEqual(services.calls[0][5], {"peer": "backend-1"})
        self.assertEqual(never_asked.calls, [])

    async def test_no_provider_recognizing_the_request_means_anonymous(self):
        services = FakeServiceEndpoint()
        servlet, _, _, _ = create_servlet(
            authentications=[FakeAuthentication(subject=None), FakeAuthentication(subject=None)], services=[services]
        )

        await servlet.handle(request("POST", sub_path="/services/ping"))

        self.assertIsNone(services.calls[0][5])

    async def test_no_authentication_service_means_anonymous(self):
        servlet, _, _, _ = create_servlet(authentications=[])

        response = await servlet.handle(request(sub_path="/unknown"))

        self.assertEqual(response.status, 404)

    async def test_empty_and_unknown_paths_are_not_found(self):
        servlet, _, _, _ = create_servlet()

        for sub_path in ("", "/unknown"):
            with self.subTest(sub_path=sub_path):
                response = await servlet.handle(request(sub_path=sub_path))
                self.assertEqual(response.status, 404)

    async def test_invalid_json_body_is_a_bad_request(self):
        servlet, _, _, _ = create_servlet()

        response = await servlet.handle(request(method="POST", sub_path="/crud/books", body=b"{bad"))

        self.assertEqual(response.status, 400)


class TestCrudRoutes(unittest.IsolatedAsyncioTestCase):

    async def test_get_many(self):
        servlet, crud, _, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/crud/books", query={"limit": "5"}))

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)["meta"], {"type": "array", "size": 2})
        self.assertEqual(crud.calls, [("get_many", "book", {"limit": "5"}, None)])

    async def test_get_one(self):
        servlet, crud, _, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/crud/books/dune"))

        self.assertEqual(json.loads(response.body)["data"], {"_id": "dune", "item_id": "book"})
        self.assertEqual(crud.calls, [("get_one", "book", "dune", {}, None)])

    async def test_create_returns_201(self):
        servlet, crud, _, _ = create_servlet()

        response = await servlet.handle(
            request(method="POST", sub_path="/crud/books", body=b'{"title": "Dune"}')
        )

        self.assertEqual(response.status, 201)
        self.assertEqual(crud.calls, [("create", "book", {"title": "Dune"}, None)])

    async def test_update(self):
        servlet, crud, _, _ = create_servlet()

        response = await servlet.handle(
            request(method="PUT", sub_path="/crud/books/dune", body=b'{"pages": 413}')
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(crud.calls, [("update", "book", "dune", {"pages": 413}, None)])

    async def test_delete(self):
        servlet, crud, _, _ = create_servlet()

        response = await servlet.handle(request(method="DELETE", sub_path="/crud/books/dune"))

        self.assertEqual(json.loads(response.body)["data"], {})
        self.assertEqual(crud.calls, [("delete", "book", "dune", None)])

    async def test_delete_many_wraps_the_count(self):
        servlet, crud, _, _ = create_servlet()

        response = await servlet.handle(
            request(method="DELETE", sub_path="/crud/books", query={"filter": '{"pages": {"$gt": 300}}'})
        )

        self.assertEqual(json.loads(response.body)["data"], {"deleted": 3})
        self.assertEqual(
            crud.calls, [("delete_many", "book", '{"pages": {"$gt": 300}}', None)]
        )

    async def test_subject_is_forwarded(self):
        servlet, crud, _, _ = create_servlet(subject=SUBJECT)

        await servlet.handle(request(sub_path="/crud/books/dune"))

        self.assertEqual(crud.calls, [("get_one", "book", "dune", {}, SUBJECT)])

    async def test_unknown_plural_is_not_found(self):
        servlet, _, _, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/crud/unknown/dune"))

        self.assertEqual(response.status, 404)

    async def test_crud_errors_are_mapped(self):
        from ycappuccino.api.endpoints_storage import Forbidden

        servlet, crud, _, _ = create_servlet()
        crud.error = Forbidden("no")

        response = await servlet.handle(request(sub_path="/crud/books/dune"))

        self.assertEqual(response.status, 403)

    async def test_wrong_method_for_path_is_not_found(self):
        servlet, _, _, _ = create_servlet()

        response = await servlet.handle(request(method="PUT", sub_path="/crud/books"))

        self.assertEqual(response.status, 404)


class TestDraftRoutes(unittest.IsolatedAsyncioTestCase):

    async def test_get_many(self):
        servlet, _, drafts, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/drafts/books/review"))

        self.assertEqual(json.loads(response.body)["meta"], {"type": "array", "size": 1})
        self.assertEqual(drafts.calls, [("get_many", "book", "review", {}, None)])

    async def test_get_one(self):
        servlet, _, drafts, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/drafts/books/dune/review"))

        self.assertEqual(json.loads(response.body)["data"], {"_id": "dune", "_draft": "review"})
        self.assertEqual(drafts.calls, [("get_one", "book", "dune", "review", {}, None)])

    async def test_save(self):
        servlet, _, drafts, _ = create_servlet()

        response = await servlet.handle(
            request(method="PUT", sub_path="/drafts/books/dune/review", body=b'{"title": "v2"}')
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(drafts.calls, [("save", "book", "dune", "review", {"title": "v2"}, None)])

    async def test_publish(self):
        servlet, _, drafts, _ = create_servlet()

        response = await servlet.handle(request(method="POST", sub_path="/drafts/books/dune/review/publish"))

        self.assertEqual(response.status, 200)
        self.assertEqual(drafts.calls, [("publish", "book", "dune", "review", None)])

    async def test_discard(self):
        servlet, _, drafts, _ = create_servlet()

        response = await servlet.handle(request(method="DELETE", sub_path="/drafts/books/dune/review"))

        self.assertEqual(json.loads(response.body)["data"], {})
        self.assertEqual(drafts.calls, [("discard", "book", "dune", "review", None)])

    async def test_not_found_error_is_mapped(self):
        from ycappuccino.api.endpoints_storage import NotFound

        servlet, _, drafts, _ = create_servlet()
        drafts.error = NotFound("no draft")

        response = await servlet.handle(request(method="DELETE", sub_path="/drafts/books/dune/review"))

        self.assertEqual(response.status, 404)


class TestItemRoutes(unittest.IsolatedAsyncioTestCase):

    async def test_get_items(self):
        servlet, _, _, catalog = create_servlet()

        response = await servlet.handle(request(sub_path="/items"))

        self.assertEqual(json.loads(response.body)["data"], [{"id": "book", "plural": "books"}])
        self.assertEqual(catalog.calls, [("get_items", None)])

    async def test_get_item_by_plural(self):
        servlet, _, _, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/items/books"))

        self.assertEqual(json.loads(response.body)["data"], {"id": "book", "plural": "books"})

    async def test_schema(self):
        servlet, _, _, catalog = create_servlet()

        response = await servlet.handle(request(sub_path="/items/books/schema"))

        self.assertEqual(json.loads(response.body)["data"], {"type": "object"})
        self.assertIn(("get_schema", "book", None), catalog.calls)

    async def test_empty(self):
        servlet, _, _, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/items/books/empty"))

        self.assertEqual(json.loads(response.body)["data"], {"_id": "empty"})

    async def test_non_get_is_not_found(self):
        servlet, _, _, _ = create_servlet()

        response = await servlet.handle(request(method="POST", sub_path="/items"))

        self.assertEqual(response.status, 404)

    async def test_unknown_plural_is_not_found(self):
        servlet, _, _, _ = create_servlet()

        response = await servlet.handle(request(sub_path="/items/unknown"))

        self.assertEqual(response.status, 404)


class TestServiceRoutes(unittest.IsolatedAsyncioTestCase):

    async def test_call_forwards_method_extra_path_params_body_and_subject(self):
        services = FakeServiceEndpoint()
        servlet, _, _, _ = create_servlet(subject=SUBJECT, services=[services])

        response = await servlet.handle(
            request(method="POST", sub_path="/services/echo/x/y", query={"q": "1"}, body=b'{"msg": "hi"}')
        )

        self.assertEqual(json.loads(response.body)["data"], {"ok": True})
        self.assertEqual(
            services.calls, [("echo", "POST", ["x", "y"], {"q": "1"}, {"msg": "hi"}, SUBJECT)]
        )

    async def test_result_headers_are_reported_on_the_response(self):
        services = FakeServiceEndpoint()
        services.result = ServiceResult(body={}, headers={"set-cookie": "a=b"})
        servlet, _, _, _ = create_servlet(services=[services])

        response = await servlet.handle(request(method="POST", sub_path="/services/login"))

        self.assertEqual(response.headers.get("set-cookie"), "a=b")

    async def test_no_service_name_is_not_found(self):
        servlet, _, _, _ = create_servlet(services=[FakeServiceEndpoint()])

        response = await servlet.handle(request(sub_path="/services"))

        self.assertEqual(response.status, 404)

    async def test_no_service_endpoint_registered_is_not_found(self):
        servlet, _, _, _ = create_servlet(services=[])

        response = await servlet.handle(request(sub_path="/services/echo"))

        self.assertEqual(response.status, 404)

    async def test_service_errors_are_mapped(self):
        from ycappuccino.api.endpoints_storage import Forbidden

        services = FakeServiceEndpoint()
        services.error = Forbidden("no")
        servlet, _, _, _ = create_servlet(services=[services])

        response = await servlet.handle(request(method="POST", sub_path="/services/secret"))

        self.assertEqual(response.status, 403)



WEB = "http://localhost:8304"


class TestCrossOrigin(unittest.IsolatedAsyncioTestCase):
    """a page served by another origin (a web front process) calling this API"""

    async def test_an_allowed_origin_gets_the_cors_headers_on_every_response(self):
        servlet, _, _, _ = create_servlet(SUBJECT, allowed_origins=f"{WEB}, http://other.example")

        response = await servlet.handle(request("GET", "/crud/books", headers={"origin": WEB}))

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], WEB)
        self.assertEqual(response.headers["Vary"], "Origin")

    async def test_an_error_response_carries_them_too(self):
        servlet, _, _, _ = create_servlet(SUBJECT, allowed_origins=WEB)

        response = await servlet.handle(request("GET", "/nowhere", headers={"origin": WEB}))

        self.assertEqual(response.status, 404)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], WEB)

    async def test_the_preflight_of_an_allowed_origin_is_answered_without_reaching_the_use_cases(self):
        servlet, crud, _, _ = create_servlet(SUBJECT, allowed_origins=WEB)

        response = await servlet.handle(request("OPTIONS", "/crud/books", headers={
            "origin": WEB, "access-control-request-method": "POST",
            "access-control-request-headers": "authorization, content-type",
        }))

        self.assertEqual(response.status, 204)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], WEB)
        self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
        self.assertEqual(response.headers["Access-Control-Allow-Headers"], "Authorization, Content-Type")
        self.assertEqual(crud.calls, [])

    async def test_another_origin_gets_no_cors_header(self):
        servlet, _, _, _ = create_servlet(SUBJECT, allowed_origins=WEB)

        response = await servlet.handle(request("GET", "/crud/books", headers={"origin": "http://evil.example"}))
        preflight = await servlet.handle(request("OPTIONS", "/crud/books", headers={"origin": "http://evil.example"}))

        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertEqual(preflight.status, 204)
        self.assertNotIn("Access-Control-Allow-Origin", preflight.headers)

    async def test_without_configuration_nothing_changes(self):
        servlet, _, _, _ = create_servlet(SUBJECT)

        response = await servlet.handle(request("GET", "/crud/books", headers={"origin": WEB}))

        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
