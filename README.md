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

from ycappuccino.api.endpoints_storage import IItemCatalog
from ycappuccino.api.http import HttpRequest
from ycappuccino.http_server.servlet import ApiServlet


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
