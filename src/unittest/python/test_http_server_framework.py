import json
import unittest
import urllib.error
import urllib.request

from ycappuccino.core.framework import Framework
from ycappuccino.core.testing import TemporaryApplication, wait_until

PORT = 18090

APPLICATION = {
    "conf/application.yml": """
        name: httpservertest
        bundle_prefix:
          - ycappuccino.storage
          - ycappuccino.endpoints_storage
          - ycappuccino.endpoints_service
          - ycappuccino.http_server
          - PACKAGE
        layers:
          ycappuccino_storage_memory:
            active: true
        config:
          http_server:
            active: true
            port: {port}
            ip: localhost
          shell:
            console: false
    """.replace("{port}", str(PORT)),
    "PACKAGE/__init__.py": "",
    "PACKAGE/books.py": """
        from ycappuccino.api.decorators import Item, Property
        from ycappuccino.api.models import Model


        @Item(collection="books", name="PACKAGE_book", plural="PACKAGE_books")
        class Book(Model):

            def __init__(self, a_dict=None):
                super().__init__(a_dict)
                self._title = None

            @Property(name="title")
            def title(self, a_value):
                self._title = a_value
    """,
    "PACKAGE/echo.py": """
        from ycappuccino.api.endpoints_service import IExposedService, ServiceResult


        class Echo(IExposedService):
            name = "echo"
            secure = False

            def __init__(self):
                pass

            async def call(self, method, extra_path, params, body, subject):
                return ServiceResult(body={"echo": body})

            async def start(self):
                pass

            async def stop(self):
                pass
    """,
}


class TestHttpServerInFramework(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = TemporaryApplication(APPLICATION).open()
        cls.addClassCleanup(cls.app.close)
        cls.framework = Framework()
        cls.framework.init(cls.app.yml_path)
        cls.addClassCleanup(cls.framework.stop)
        wait_until(lambda: cls.framework.context.get_service_reference("ApiServlet"))
        cls.plural = cls.app.package + "_books"

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://localhost:{PORT}{path}", data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_create_then_read_a_book(self):
        status, created = self.call(
            "POST", f"/api/crud/{self.plural}", body=b'{"_id": "dune", "title": "Dune"}'
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["data"]["title"], "Dune")

        status, page = self.call("GET", f"/api/crud/{self.plural}")
        self.assertEqual(status, 200)
        self.assertEqual(page["meta"], {"type": "array", "size": 1})

    def test_unknown_route_is_a_404(self):
        status, body = self.call("GET", "/api/unknown")

        self.assertEqual(status, 404)
        self.assertIn("error", body["data"])

    def test_items_catalog_lists_the_application_item(self):
        status, body = self.call("GET", "/api/items")

        self.assertEqual(status, 200)
        self.assertIn(self.plural, [item["plural"] for item in body["data"]])

    def test_service_route(self):
        status, body = self.call("POST", "/api/services/echo", body=b'{"msg": "hi"}')

        self.assertEqual(status, 200)
        self.assertEqual(body["data"], {"echo": {"msg": "hi"}})


if __name__ == "__main__":
    unittest.main()
