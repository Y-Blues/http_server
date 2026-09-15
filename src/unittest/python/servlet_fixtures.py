"""
Fake use cases shared by the ApiServlet tests.
"""

from ycappuccino.api.endpoints_service import IServiceEndpoint, ServiceResult
from ycappuccino.api.endpoints_storage import ICrud, IDrafts, IItemCatalog, NotFound
from ycappuccino.api.http_server import IAuthentication

SUBJECT = {"sub": "alice", "tid": "acme"}


class FakeCrud(ICrud):

    def __init__(self):
        self.calls = []
        self.error = None

    def _record(self, *call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    async def get_one(self, item_id, id, params=None, subject=None):
        self._record("get_one", item_id, id, params, subject)
        return {"_id": id, "item_id": item_id}

    async def get_many(self, item_id, params=None, subject=None):
        self._record("get_many", item_id, params, subject)
        return {"items": [{"_id": "a"}, {"_id": "b"}], "total": 2}

    async def create(self, item_id, fields, subject=None):
        self._record("create", item_id, fields, subject)
        return {"_id": "new", **fields}

    async def update(self, item_id, id, fields, subject=None):
        self._record("update", item_id, id, fields, subject)
        return {"_id": id, **fields}

    async def delete(self, item_id, id, subject=None):
        self._record("delete", item_id, id, subject)

    async def delete_many(self, item_id, filter, subject=None):
        self._record("delete_many", item_id, filter, subject)
        return 3

    async def start(self):
        pass

    async def stop(self):
        pass


class FakeDrafts(IDrafts):

    def __init__(self):
        self.calls = []
        self.error = None

    def _record(self, *call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    async def get_one(self, item_id, id, draft, params=None, subject=None):
        self._record("get_one", item_id, id, draft, params, subject)
        return {"_id": id, "_draft": draft}

    async def get_many(self, item_id, draft, params=None, subject=None):
        self._record("get_many", item_id, draft, params, subject)
        return {"items": [{"_id": "a", "_draft": draft}], "total": 1}

    async def save(self, item_id, id, draft, fields, subject=None):
        self._record("save", item_id, id, draft, fields, subject)
        return {"_id": id, "_draft": draft, **fields}

    async def publish(self, item_id, id, draft, subject=None):
        self._record("publish", item_id, id, draft, subject)
        return {"_id": id}

    async def discard(self, item_id, id, draft, subject=None):
        self._record("discard", item_id, id, draft, subject)

    async def start(self):
        pass

    async def stop(self):
        pass


class FakeItemCatalog(IItemCatalog):

    def __init__(self, items=None):
        self.items = items if items is not None else {"books": {"id": "book", "plural": "books"}}
        self.calls = []
        self.error = None

    def _record(self, *call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    async def get_items(self, subject=None):
        self._record("get_items", subject)
        return list(self.items.values())

    async def get_item(self, item_id, subject=None):
        self._record("get_item", item_id, subject)
        for item in self.items.values():
            if item["id"] == item_id:
                return item
        raise NotFound(item_id)

    async def get_item_by_plural(self, plural, subject=None):
        self._record("get_item_by_plural", plural, subject)
        if plural not in self.items:
            raise NotFound(plural)
        return self.items[plural]

    async def get_schema(self, item_id, subject=None):
        self._record("get_schema", item_id, subject)
        return {"type": "object"}

    async def get_empty(self, item_id, subject=None):
        self._record("get_empty", item_id, subject)
        return {"_id": "empty"}

    async def start(self):
        pass

    async def stop(self):
        pass


class FakeAuthentication(IAuthentication):

    def __init__(self, subject=None):
        self.subject = subject
        self.calls = []

    async def authenticate(self, headers):
        self.calls.append(headers)
        return self.subject

    async def start(self):
        pass

    async def stop(self):
        pass


class FakeServiceEndpoint(IServiceEndpoint):

    def __init__(self):
        self.calls = []
        self.error = None
        self.result = ServiceResult(body={"ok": True})

    async def call(self, name, method, extra_path, params, body, subject):
        self.calls.append((name, method, extra_path, params, body, subject))
        if self.error is not None:
            raise self.error
        return self.result

    async def start(self):
        pass

    async def stop(self):
        pass


def create_servlet(subject=None, authentications=None, services=None):
    """a servlet wired to fresh fakes; returns (servlet, crud, drafts, catalog)"""
    from ycappuccino.http_server.servlet import ApiServlet

    crud, drafts, catalog = FakeCrud(), FakeDrafts(), FakeItemCatalog()
    if authentications is None:
        authentications = [FakeAuthentication(subject)]
    return ApiServlet(crud, drafts, catalog, authentications, services or []), crud, drafts, catalog
