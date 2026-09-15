# http_server natif : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adaptateur HTTP natif (`ApiServlet`) traduisant les routes REST vers `ICrud`/`IDrafts`/`IItemCatalog` d'`endpoints_storage`, avec authentification optionnelle (`IAuthentication`), mapping d'erreurs et enveloppe JSON legacy.

**Architecture:** Un seul composant `ApiServlet(IHttpServlet)`, sans décorateur, routant en interne par segments de chemin (`crud`/`drafts`/`items`). Le contrat `IAuthentication` vit dans `api.http_server`. Le corps est bâti en modules focalisés dans un seul fichier (`servlet.py`, découpage en méthodes privées par famille de route), testé sans Pelix avec de faux cas d'usage, plus une intégration framework réelle.

**Tech Stack:** Python ≥ 3.10, uv, Pelix/iPOPO 3, `ycappuccino.api.http` (`IHttpServlet`), `ycappuccino.api.endpoints_storage`, unittest (`IsolatedAsyncioTestCase`), `urllib` (stdlib, test d'intégration).

**Spec:** `http_server/docs/superpowers/specs/2026-09-15-http-server-design.md`

## Global Constraints

- Chemins relatifs à la racine du workspace `/home/apisu/Documents/perso/repositories` ; `api`, `core`, `storage`, `endpoints_storage`, `http_server` sont des dépôts git séparés.
- Commande de test, lancée depuis le dépôt concerné : `uv run python -m unittest discover -s src/unittest/python`.
- `requires-python = ">=3.10"`.
- **Aucun décorateur sur les classes de composants.**
- Enveloppe JSON de succès : `{"status", "meta": {"type": "object"|"array", "size"?}, "data"}` ; enveloppe d'erreur : même forme, `data: {"error": "<message>"}`. Le `500` ne renvoie jamais le message réel de l'exception ni de trace, seulement `"internal error"`.
- Mapping d'erreurs : `NotAuthenticated`→401, `Forbidden`→403, `NotFound`→404, `InvalidRequest`→400, toute autre exception→500 (journalisée).
- `authentications: list[IAuthentication]` (liste vivante) ; son premier élément est utilisé, sujet `None` si la liste est vide.
- Une combinaison méthode/chemin non reconnue par le routeur donne `404`, jamais `500`.
- Committer après la revue de chaque tâche, jamais pendant qu'un sous-agent travaille encore dans le même dépôt ; messages de commit courts, sans ligne d'attribution.

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `api/src/main/python/ycappuccino/api/http_server.py` (créé) | `IAuthentication` |
| `http_server/pyproject.toml` (réécrit) | projet uv `ycappuccino-http-server` |
| `http_server/src/main/python/ycappuccino/http_server/servlet.py` | `ApiServlet` : dispatch, aides `_ok`/`_error`/`_segments`/`_decode_body` |
| `http_server/src/unittest/python/servlet_fixtures.py` | faux `ICrud`/`IDrafts`/`IItemCatalog`/`IAuthentication` |
| `http_server/example/`, `README.md` | exemple exécutable et documentation |

---

### Task 1: api, contrat `IAuthentication`

**Files:**
- Create: `api/src/main/python/ycappuccino/api/http_server.py`
- Test: `api/src/unittest/python/test_interfaces.py` (ajout d'une classe)

**Interfaces:**
- Produces: `ycappuccino.api.http_server.IAuthentication(YCappuccinoComponent, ABC)` avec `async def authenticate(self, headers: dict) -> Optional[dict]`.

- [ ] **Step 1: Write the failing test**

Ajouter à `api/src/unittest/python/test_interfaces.py`, avant `if __name__ == "__main__":` :

```python
class TestHttpServerInterfaces(unittest.TestCase):

    def test_authentication_is_an_abstract_coroutine(self):
        from ycappuccino.api.http_server import IAuthentication

        self.assertTrue(issubclass(IAuthentication, YCappuccinoComponent))
        self.assertTrue(inspect.isabstract(IAuthentication))
        self.assertTrue(inspect.iscoroutinefunction(IAuthentication.authenticate))
```

- [ ] **Step 2: Run test to verify it fails**

Run (depuis `api`) : `uv run python -m unittest discover -s src/unittest/python -p test_interfaces.py`
Expected: `ModuleNotFoundError: No module named 'ycappuccino.api.http_server'`.

- [ ] **Step 3: Implement**

`api/src/main/python/ycappuccino/api/http_server.py` :

```python
"""
api.http_server: authentication port used by HTTP adapters (http_server, and later others).
"""

from abc import ABC, abstractmethod
from typing import Optional

from ycappuccino.api.core_base import YCappuccinoComponent


class IAuthentication(YCappuccinoComponent, ABC):
    """decodes the subject of an HTTP request from its headers"""

    @abstractmethod
    async def authenticate(self, headers: dict) -> Optional[dict]:
        """subject decoded from the headers, or None when absent or invalid"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run (depuis `api`) : `uv run python -m unittest discover -s src/unittest/python`
Expected: `OK`.

---

### Task 2: http_server, projet uv, fixtures, squelette de la servlet

**Files:**
- Modify: `http_server/pyproject.toml` (tout le fichier), `http_server/.gitignore` (tout le fichier)
- Modify: `http_server/src/main/python/ycappuccino/http_server/__init__.py` (tout le fichier)
- Delete (`git rm`) : `build.py`, `setup.py`, `data/log/`, `example/__init__.py`, `src/main/python/ycappuccino/endpoints/` (tout le dossier), `src/unittest/`
- Create: `http_server/src/main/python/ycappuccino/http_server/servlet.py`
- Create: `http_server/src/unittest/python/servlet_fixtures.py`
- Test: `http_server/src/unittest/python/test_servlet.py`

**Interfaces:**
- Consumes (Task 1) : `IAuthentication` ; `ycappuccino.api.http` (`HttpRequest`, `HttpResponse`, `IHttpServlet`) ; `ycappuccino.api.endpoints_storage` (`ICrud`, `IDrafts`, `IItemCatalog`, `CrudError`, `NotAuthenticated`, `Forbidden`, `NotFound`, `InvalidRequest`).
- Produces:
  - `ApiServlet(crud: ICrud, drafts: IDrafts, catalog: IItemCatalog, authentications: list[IAuthentication], path: str = "/api")` implémentant `IHttpServlet` ; `handle(request)` authentifie, décode le corps JSON, segmente `sub_path`, route (pour l'instant `_route` lève toujours `NotFound`, rempli par les tâches 3 à 5), et mappe les erreurs.
  - fonctions de module `_segments(request) -> list[str]`, `_decode_body(request) -> dict | None`, `_ok(status, payload) -> HttpResponse`, `_error(status, error) -> HttpResponse`.
  - fixtures : `FakeCrud`, `FakeDrafts`, `FakeItemCatalog(items=None)`, `FakeAuthentication(subject=None)`, toutes avec `.calls` (liste des appels) et un attribut `.error` (si non `None`, chaque méthode le lève avant tout autre traitement).

- [ ] **Step 1: Replace the PyBuilder project**

```bash
cd http_server
git rm -q -r build.py setup.py data/log example/__init__.py src/main/python/ycappuccino/endpoints src/unittest
mkdir -p src/unittest/python
```

`http_server/pyproject.toml` :

```toml
[project]
name = "ycappuccino-http-server"
version = "0.1.0"
description = "YCappuccino http_server: HTTP adapter over the endpoints_storage use cases"
requires-python = ">=3.10"
dependencies = [
    "ycappuccino-api",
    "ycappuccino-core",
    "ycappuccino-storage",
    "ycappuccino-endpoints-storage",
]

[build-system]
requires = ["uv_build>=0.12.13,<0.13"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "ycappuccino.http_server"
module-root = "src/main/python"

[tool.uv.sources]
ycappuccino-api = { path = "../api", editable = true }
ycappuccino-core = { path = "../core", editable = true }
ycappuccino-storage = { path = "../storage", editable = true }
ycappuccino-endpoints-storage = { path = "../endpoints_storage", editable = true }
```

`http_server/.gitignore` :

```
data
.venv
__pycache__
dist
```

`http_server/src/main/python/ycappuccino/http_server/__init__.py` :

```python
"""HTTP adapter over the endpoints_storage use cases"""
```

Run (depuis `http_server`) : `uv sync`
Expected: environnement créé, les quatre dépendances locales installées en éditable.

- [ ] **Step 2: Write the fixtures**

`http_server/src/unittest/python/servlet_fixtures.py` :

```python
"""
Fake use cases shared by the ApiServlet tests.
"""

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


def create_servlet(subject=None, authentications=None):
    """a servlet wired to fresh fakes; returns (servlet, crud, drafts, catalog)"""
    from ycappuccino.http_server.servlet import ApiServlet

    crud, drafts, catalog = FakeCrud(), FakeDrafts(), FakeItemCatalog()
    if authentications is None:
        authentications = [FakeAuthentication(subject)]
    return ApiServlet(crud, drafts, catalog, authentications), crud, drafts, catalog
```

- [ ] **Step 3: Write the failing test**

`http_server/src/unittest/python/test_servlet.py` :

```python
import json
import unittest

from servlet_fixtures import FakeAuthentication, create_servlet

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run test to verify it fails**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python`
Expected: `ModuleNotFoundError: No module named 'ycappuccino.http_server.servlet'`.

- [ ] **Step 5: Implement**

`http_server/src/main/python/ycappuccino/http_server/servlet.py` :

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python`
Expected: `OK`.

---

### Task 3: http_server, routes `/crud`

**Files:**
- Modify: `http_server/src/main/python/ycappuccino/http_server/servlet.py` (`_route`, ajout de `_route_crud`)
- Modify: `http_server/src/unittest/python/test_servlet.py` (ajout d'une classe)

**Interfaces:**
- Consumes (Task 2) : `ApiServlet`, fixtures, `request()` helper du fichier de test.
- Produces: `_route` reconnaît `"crud"` comme premier segment et délègue à `_route_crud(method, rest, params, fields, subject)`, qui couvre les 6 routes `/crud` de la spec (section 3). Toute combinaison non couverte lève `NotFound`.

- [ ] **Step 1: Write the failing test**

Ajouter à `http_server/src/unittest/python/test_servlet.py`, avant `if __name__ == "__main__":` :

```python
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
```

Ajouter en tête du fichier, avec les autres imports : `from servlet_fixtures import SUBJECT` (à côté de l'import déjà présent des autres fixtures).

- [ ] **Step 2: Run test to verify it fails**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python -p test_servlet.py`
Expected: FAIL — `_route` lève toujours `NotFound`, donc tous les codes attendus (`200`/`201`) échouent, sauf les cas déjà `404`.

- [ ] **Step 3: Implement**

Dans `servlet.py`, remplacer :

```python
    async def _route(self, method, segments, params, fields, subject):
        raise NotFound("not found")
```

par :

```python
    async def _route(self, method, segments, params, fields, subject):
        if not segments:
            raise NotFound("not found")
        family, rest = segments[0], segments[1:]
        if family == "crud":
            return await self._route_crud(method, rest, params, fields, subject)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python`
Expected: `OK`.

---

### Task 4: http_server, routes `/drafts`

**Files:**
- Modify: `http_server/src/main/python/ycappuccino/http_server/servlet.py` (`_route`, ajout de `_route_drafts`)
- Modify: `http_server/src/unittest/python/test_servlet.py` (ajout d'une classe)

**Interfaces:**
- Consumes (Tasks 2, 3) : mêmes fixtures et helper `request()`.
- Produces: `_route_drafts(method, rest, params, fields, subject)` couvre les 5 routes `/drafts` de la spec, y compris le suffixe `/publish`.

- [ ] **Step 1: Write the failing test**

Ajouter à `http_server/src/unittest/python/test_servlet.py`, avant `if __name__ == "__main__":` :

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python -p test_servlet.py`
Expected: FAIL, tous les cas `/drafts` renvoient `404` (family inconnue).

- [ ] **Step 3: Implement**

Dans `servlet.py`, remplacer :

```python
        if family == "crud":
            return await self._route_crud(method, rest, params, fields, subject)
        raise NotFound("not found")
```

par :

```python
        if family == "crud":
            return await self._route_crud(method, rest, params, fields, subject)
        if family == "drafts":
            return await self._route_drafts(method, rest, params, fields, subject)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python`
Expected: `OK`.

---

### Task 5: http_server, routes `/items`

**Files:**
- Modify: `http_server/src/main/python/ycappuccino/http_server/servlet.py` (`_route`, ajout de `_route_items`)
- Modify: `http_server/src/unittest/python/test_servlet.py` (ajout d'une classe)

**Interfaces:**
- Consumes (Task 2) : mêmes fixtures et helper.
- Produces: `_route_items(method, rest, subject)` couvre les 4 routes `/items` de la spec ; toute méthode autre que `GET` lève `NotFound`.

- [ ] **Step 1: Write the failing test**

Ajouter à `http_server/src/unittest/python/test_servlet.py`, avant `if __name__ == "__main__":` :

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python -p test_servlet.py`
Expected: FAIL, `/items/...` renvoie `404` (family inconnue) au lieu des réponses attendues.

- [ ] **Step 3: Implement**

Dans `servlet.py`, remplacer :

```python
        if family == "drafts":
            return await self._route_drafts(method, rest, params, fields, subject)
        raise NotFound("not found")
```

par :

```python
        if family == "drafts":
            return await self._route_drafts(method, rest, params, fields, subject)
        if family == "items":
            return await self._route_items(method, rest, subject)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python`
Expected: `OK`.

---

### Task 6: http_server, intégration au framework et exemple

**Files:**
- Test: `http_server/src/unittest/python/test_http_server_framework.py`
- Modify: `http_server/example/conf/application.yml` (tout le fichier)
- Create: `http_server/example/library/__init__.py` (vide), `http_server/example/library/books.py`

**Interfaces:**
- Consumes (Tasks 1-5) : `ApiServlet` complet ; `ycappuccino.core.framework.Framework` ; `ycappuccino.core.testing.TemporaryApplication`, `wait_until`.

Le serveur HTTP réel (`pelix.http.basic`) n'est démarré que si `config.http_server.active: true` (voir `core/README.md`, section Servlets HTTP). Une requête HTTP passe par le pont synchrone de `core` : aucun `asyncio.run` n'est nécessaire côté test, seul `urllib` suffit.

- [ ] **Step 1: Write the integration test**

`http_server/src/unittest/python/test_http_server_framework.py` :

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the integration test**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python -p test_http_server_framework.py`
Expected: `OK`, 3 tests.

- [ ] **Step 3: Rebuild the example**

`http_server/example/conf/application.yml` :

```yaml
---
name: library
bundle_prefix:
  - ycappuccino.storage
  - ycappuccino.endpoints_storage
  - ycappuccino.http_server
  - library
layers:
  ycappuccino_storage_memory:
    active: true
config:
  http_server:
    active: true
    port: 9000
    ip: localhost
```

`http_server/example/library/__init__.py` : fichier vide.

`http_server/example/library/books.py` :

```python
"""
Example: a library exposed over HTTP through ApiServlet.
"""

from ycappuccino.api.decorators import Item, Property
from ycappuccino.api.models import Model


@Item(collection="books", name="book", plural="books")
class Book(Model):

    def __init__(self, a_dict=None):
        super().__init__(a_dict)
        self._title = None
        self._pages = None

    @Property(name="title")
    def title(self, a_value):
        self._title = a_value

    @Property(name="pages", type="integer", minimum=0)
    def pages(self, a_value):
        self._pages = a_value
```

- [ ] **Step 4: Run the example**

Run (dans `http_server/example`) :

```bash
rm -rf data
timeout -s INT 8 uv run --project .. ycappuccino < /dev/null &
sleep 2
curl -s -X POST http://localhost:9000/api/crud/books -d '{"_id": "dune", "title": "Dune", "pages": 412}'
curl -s http://localhost:9000/api/crud/books
wait
```

Expected: le `POST` renvoie `{"status": 201, ...}` avec `"data": {"_id": "dune", "title": "Dune", "pages": 412}` ; le `GET` renvoie `"meta": {"type": "array", "size": 1}`.

- [ ] **Step 5: Run all http_server tests**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python`
Expected: `OK`.

---

### Task 7: README et vérification finale

**Files:**
- Create: `http_server/README.md`
- Modify: `CLAUDE.md` (racine du workspace)

**Interfaces:**
- Consumes: tout ce qui précède.

- [ ] **Step 1: Write the README**

`http_server/README.md` :

````markdown
# ycappuccino-http-server

Adaptateur HTTP natif au-dessus des cas d'usage `ycappuccino-endpoints-storage` (`ICrud`, `IDrafts`, `IItemCatalog`) : une seule servlet, `ApiServlet`, monte les routes REST et traduit les erreurs en codes HTTP.

Conception : [docs/superpowers/specs/2026-09-15-http-server-design.md](docs/superpowers/specs/2026-09-15-http-server-design.md).

Prérequis : lire les README de [core](../core/README.md) (section « Servlets HTTP ») et d'[endpoints_storage](../endpoints_storage/README.md).

## Mise en place

```bash
uv add --editable ../http_server
```

`conf/application.yml` :

```yaml
name: library
bundle_prefix:
  - ycappuccino.storage
  - ycappuccino.endpoints_storage
  - ycappuccino.http_server
  - library
layers:
  ycappuccino_storage_memory:
    active: true
config:
  http_server:
    active: true
    port: 9000
```

`ApiServlet` se monte sur `/api`.

## Routes

| Méthode | Chemin | Cas d'usage |
|---|---|---|
| GET | `/api/crud/<pluriel>` | `ICrud.get_many` |
| GET | `/api/crud/<pluriel>/<id>` | `ICrud.get_one` |
| POST | `/api/crud/<pluriel>` | `ICrud.create` (`201`) |
| PUT | `/api/crud/<pluriel>/<id>` | `ICrud.update` |
| DELETE | `/api/crud/<pluriel>/<id>` | `ICrud.delete` |
| DELETE | `/api/crud/<pluriel>?filter=...` | `ICrud.delete_many` |
| GET | `/api/drafts/<pluriel>/<brouillon>` | `IDrafts.get_many` |
| GET | `/api/drafts/<pluriel>/<id>/<brouillon>` | `IDrafts.get_one` |
| PUT | `/api/drafts/<pluriel>/<id>/<brouillon>` | `IDrafts.save` |
| POST | `/api/drafts/<pluriel>/<id>/<brouillon>/publish` | `IDrafts.publish` |
| DELETE | `/api/drafts/<pluriel>/<id>/<brouillon>` | `IDrafts.discard` |
| GET | `/api/items` | `IItemCatalog.get_items` |
| GET | `/api/items/<pluriel>` | `IItemCatalog.get_item_by_plural` |
| GET | `/api/items/<pluriel>/schema` | `IItemCatalog.get_schema` |
| GET | `/api/items/<pluriel>/empty` | `IItemCatalog.get_empty` |

Une requête `GET`/`DELETE` transmet sa query string telle quelle en `params` (`filter`, `sort`, `limit`, `offset`, `expand`, `content`) ; une requête `POST`/`PUT` transmet son corps JSON décodé comme `fields`. Une combinaison méthode/chemin non listée répond `404`.

## Authentification

```python
from ycappuccino.api.http_server import IAuthentication


class DemoAuthentication(IAuthentication):
    async def authenticate(self, headers):
        token = headers.get("authorization", "").removeprefix("Bearer ")
        return {"sub": "alice", "tid": "acme"} if token == "demo" else None

    async def start(self):
        pass

    async def stop(self):
        pass
```

Sans aucune `IAuthentication` publiée, toutes les requêtes sont anonymes : les items publics restent accessibles, les items sécurisés répondent `401`/`403` selon les règles d'`endpoints_storage`. `permissions_app` fournira l'implémentation JWT.

## Erreurs et enveloppe

```json
{"status": 200, "meta": {"type": "object", "size": 1}, "data": {"_id": "dune", "title": "Dune"}}
```

Une liste : `"meta": {"type": "array", "size": <total>}`, `"data"` est le tableau. Les erreurs suivent la même forme, avec `"data": {"error": "<message>"}` :

| Erreur | Code |
|---|---|
| `NotAuthenticated` | 401 |
| `Forbidden` | 403 |
| `NotFound` | 404 |
| `InvalidRequest` | 400 |
| autre exception | 500, message générique, jamais de détail interne |

## Tester avec http_server

`ApiServlet` s'instancie directement, sans framework, avec de faux cas d'usage :

```python
import unittest

from ycappuccino.api.http import HttpRequest
from ycappuccino.http_server.servlet import ApiServlet


class FakeCrud:
    async def get_many(self, item_id, params=None, subject=None):
        return {"items": [], "total": 0}

    async def start(self):
        pass

    async def stop(self):
        pass


class TestApiServlet(unittest.IsolatedAsyncioTestCase):
    async def test_empty_list(self):
        servlet = ApiServlet(FakeCrud(), None, FakeItemCatalog(), [])

        request = HttpRequest(
            method="GET", path="/api/crud/books", prefix="/api", sub_path="/crud/books",
            query={}, headers={},
        )
        response = await servlet.handle(request)

        self.assertEqual(response.status, 200)
```

## Développer http_server

```bash
uv sync
uv run python -m unittest discover -s src/unittest/python
```

L'exemple `example/` se lance avec `cd example && uv run --project .. ycappuccino`.
````

- [ ] **Step 2: Write the README test**

`http_server/src/unittest/python/test_readme.py` :

```python
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
```

- [ ] **Step 3: Run the README test**

Run (depuis `http_server`) : `uv run python -m unittest discover -s src/unittest/python -p test_readme.py`
Expected: `OK`, 2 tests. Si un exemple ne fonctionne pas tel quel, corriger le README **et** le test pour qu'ils restent identiques.

- [ ] **Step 4: Update CLAUDE.md**

Dans `CLAUDE.md`, remplacer :

```markdown
- `endpoints_storage` → `ycappuccino.endpoints_storage`: transport-independent use cases `ICrud`, `IDrafts`, `IItemCatalog` over `IManager` (contract in `api/endpoints_storage.py`), authorized through the `IAuthorization` port. See `endpoints_storage/README.md`.
- The others are feature layers not yet migrated to the new framework: `endpoints_service`, `hosts`, `http_server`, `permissions_app`, `remote`, `scheduler`, `scripts`, `swagger`, `component-creator`.
```

par :

```markdown
- `endpoints_storage` → `ycappuccino.endpoints_storage`: transport-independent use cases `ICrud`, `IDrafts`, `IItemCatalog` over `IManager` (contract in `api/endpoints_storage.py`), authorized through the `IAuthorization` port. See `endpoints_storage/README.md`.
- `http_server` → `ycappuccino.http_server`: native HTTP adapter, a single `ApiServlet` (`ycappuccino.api.http.IHttpServlet`) routing to `endpoints_storage`'s use cases, subject decoded through the `IAuthentication` port (`api/http_server.py`). See `http_server/README.md`.
- The others are feature layers not yet migrated to the new framework: `endpoints_service`, `hosts`, `permissions_app`, `remote`, `scheduler`, `scripts`, `swagger`, `component-creator`.
```

Remplacer :

```markdown
Folder, project and package names don't always match: `http_server` is project `http` with package `ycappuccino.endpoints`, `permissions_app` is `permissions`, and `endpoints_service` is package `ycappuccino.endpoints_services`.
```

par :

```markdown
Folder, project and package names don't always match: `permissions_app` is project `permissions`, and `endpoints_service` is package `ycappuccino.endpoints_services`.
```

Remplacer :

```markdown
`api`, `core`, `storage` and `endpoints_storage` are built with **uv** (`pyproject.toml`, `uv_build` backend with `module-root = "src/main/python"` and a dotted `module-name`). `core` depends on `../api`, `storage` on `../api` and `../core`, and `endpoints_storage` on `../api`, `../core` and `../storage`, as editable path sources. The other repos still have PyBuilder `build.py`/`setup.py`.
```

par :

```markdown
`api`, `core`, `storage`, `endpoints_storage` and `http_server` are built with **uv** (`pyproject.toml`, `uv_build` backend with `module-root = "src/main/python"` and a dotted `module-name`). `core` depends on `../api`, `storage` on `../api` and `../core`, `endpoints_storage` on `../api`, `../core` and `../storage`, and `http_server` on all four, as editable path sources. The other repos still have PyBuilder `build.py`/`setup.py`.
```

- [ ] **Step 5: Final verification**

Run, depuis chaque dépôt, dans cet ordre :

```bash
cd api && uv run python -m unittest discover -s src/unittest/python
cd ../core && uv run python -m unittest discover -s src/unittest/python
cd ../storage && uv run python -m unittest discover -s src/unittest/python
cd ../endpoints_storage && uv run python -m unittest discover -s src/unittest/python
cd ../http_server && uv run python -m unittest discover -s src/unittest/python
```

Expected: `OK` pour les cinq dépôts (tests Mongo de `storage` ignorés sans Docker).
