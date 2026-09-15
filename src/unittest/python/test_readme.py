"""
The examples of README.md, kept runnable.
"""

import unittest

from ycappuccino.api.endpoints_storage import IItemCatalog
from ycappuccino.api.http import HttpRequest
from ycappuccino.api.http_server import IAuthentication
from ycappuccino.http_server.servlet import ApiServlet


# section "Authentification"
class DemoAuthentication(IAuthentication):
    async def authenticate(self, headers):
        token = headers.get("authorization", "").removeprefix("Bearer ")
        return {"sub": "alice", "tid": "acme"} if token == "demo" else None

    async def start(self):
        pass

    async def stop(self):
        pass


# section "Tester avec http_server"
class FakeCrud:
    async def get_many(self, item_id, params=None, subject=None):
        return {"items": [], "total": 0}

    async def start(self):
        pass

    async def stop(self):
        pass


class FakeItemCatalog(IItemCatalog):
    async def get_items(self, subject=None):
        return []

    async def get_item(self, item_id, subject=None):
        return {}

    async def get_item_by_plural(self, plural, subject=None):
        return {"id": "book", "plural": plural}

    async def get_schema(self, item_id, subject=None):
        return {}

    async def get_empty(self, item_id, subject=None):
        return None

    async def start(self):
        pass

    async def stop(self):
        pass


class TestReadmeExamples(unittest.IsolatedAsyncioTestCase):

    async def test_authentication_section(self):
        auth = DemoAuthentication()

        self.assertIsNone(await auth.authenticate({}))
        self.assertEqual(await auth.authenticate({"authorization": "Bearer demo"}), {"sub": "alice", "tid": "acme"})

    async def test_testing_section(self):
        servlet = ApiServlet(FakeCrud(), None, FakeItemCatalog(), [])

        request = HttpRequest(
            method="GET", path="/api/crud/books", prefix="/api", sub_path="/crud/books",
            query={}, headers={},
        )
        response = await servlet.handle(request)

        self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
