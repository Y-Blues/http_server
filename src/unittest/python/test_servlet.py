import json
import unittest

from servlet_fixtures import FakeAuthentication, SUBJECT, create_servlet

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

    async def test_authentication_is_called_with_the_request_headers(self):
        authentication = FakeAuthentication(subject={"sub": "alice"})
        servlet, _, _, _ = create_servlet(authentications=[authentication])

        await servlet.handle(request(sub_path="/unknown", headers={"authorization": "Bearer x"}))

        self.assertEqual(authentication.calls, [{"authorization": "Bearer x"}])

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


if __name__ == "__main__":
    unittest.main()
