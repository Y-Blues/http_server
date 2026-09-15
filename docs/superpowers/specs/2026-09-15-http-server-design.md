# http_server natif : design

Date : 2026-09-15. Sous-projet 1 (premier adaptateur) de la reprise des dépôts YCappuccino, après `core`, `api`, `storage`, `endpoints_storage`, et les évolutions core C1 (`IHttpServlet`) et C2 (`@Layer`).

## Objectif

`http_server` traduit HTTP vers les cas d'usage `ycappuccino.endpoints_storage` (`ICrud`, `IDrafts`, `IItemCatalog`) : routage, authentification, décodage/encodage JSON, mapping des erreurs vers des codes HTTP. Il ne contient aucune logique métier — celle-ci reste dans `endpoints_storage`. L'appel de services (`endpoints_service`, sous-projet suivant) est hors périmètre de cette itération.

## Décisions

| Sujet | Décision |
|---|---|
| Style | Un seul composant natif `ApiServlet(IHttpServlet)`, routage interne par segments de chemin ; aucun décorateur |
| Servlet | S'appuie sur `ycappuccino.api.http.IHttpServlet` (core C1) : `path="/api"`, `handle(HttpRequest) -> HttpResponse` |
| Routage | Routes explicites (`/crud`, `/drafts`, `/items`), indépendantes de toute description swagger |
| Authentification | Nouveau port `IAuthentication` dans `api.http_server`, liste vivante (`list[IAuthentication]`), premier élément utilisé, sujet `None` si absent ou liste vide |
| Erreurs | `CrudError` d'`endpoints_storage` mappée vers 401/403/404/400 ; toute autre exception vers 500 sans détail interne dans le corps |
| Enveloppe JSON | Legacy : `{"status", "meta": {"type", "size"}, "data"}`, appliquée aux succès et aux erreurs |
| Upload | Corps JSON portant `content`/`content64` (déjà supporté par `storage`) ; pas d'analyse de vraies requêtes `multipart/form-data` dans cette itération |
| Paquet | Renommé `ycappuccino.http_server`, projet `ycappuccino-http-server` (legacy : projet `http`, paquet `ycappuccino.endpoints`) |

## 1. Contrat dans `api` (`ycappuccino.api.http_server`, nouveau module)

```python
from abc import ABC, abstractmethod
from typing import Optional

from ycappuccino.api.core_base import YCappuccinoComponent


class IAuthentication(YCappuccinoComponent, ABC):
    """decodes the subject of an HTTP request from its headers"""

    @abstractmethod
    async def authenticate(self, headers: dict) -> Optional[dict]:
        """subject ({"sub", "tid", ...}) decoded from the headers, or None when absent or invalid"""
```

Aucun autre type n'est nécessaire : `ApiServlet` construit ses réponses directement à partir de `ycappuccino.api.http.HttpResponse`.

## 2. `ApiServlet` (`http_server/.../servlet.py`)

```python
class ApiServlet(IHttpServlet):

    def __init__(
        self,
        crud: ICrud,
        drafts: IDrafts,
        catalog: IItemCatalog,
        authentications: list[IAuthentication],
        path: str = "/api",
    ):
        ...

    async def handle(self, request: HttpRequest) -> HttpResponse:
        ...

    async def start(self):
        pass

    async def stop(self):
        pass
```

Classe simple, testable sans framework : `handle` reçoit un `HttpRequest` construit à la main dans les tests, avec de faux `ICrud`/`IDrafts`/`IItemCatalog`/`IAuthentication`.

### 2.1 Déroulé de `handle`

1. `subject = await authentications[0].authenticate(request.headers)` si la liste n'est pas vide, sinon `None`.
2. Le `sub_path` est découpé en segments (`request.sub_path.strip("/").split("/")`, une chaîne vide donne une liste vide). Le premier segment (`"crud"`, `"drafts"`, `"items"`) sélectionne la famille de routes ; un premier segment absent ou inconnu donne `404`.
3. Le corps JSON (`request.body`) est décodé pour `POST`/`PUT` quand il n'est pas vide ; un JSON invalide devient une `InvalidRequest` (400), traitée comme les autres erreurs de la section 2.3.
4. Chaque route (section 3) résout le pluriel en `item_id` via `catalog.get_item_by_plural(plural, subject)` — une `NotFound` du catalogue devient la 404 de la route elle-même.
5. Le résultat de l'appel est enveloppé (section 2.4) et renvoyé en `HttpResponse` avec le code de succès approprié (`200` pour les lectures, mises à jour et publications, `201` pour `create`, `204`... non : toujours un corps JSON, donc `200` pour `delete`/`discard` aussi, jamais de `204` sans corps).

### 2.2 Paramètres de lecture

Pour une requête `GET`, `params = dict(request.query)` est transmis tel quel aux méthodes d'`ICrud`/`IDrafts` : leurs propres fonctions de parsing (`parse_filter`, etc., dans `endpoints_storage`) acceptent déjà du texte issu d'une query string. Une clé absente de la query n'est pas mise dans `params` (elle garde donc la valeur par défaut du cas d'usage).

### 2.3 Erreurs

```python
try:
    ...
except NotAuthenticated as error:
    return _error(401, error)
except Forbidden as error:
    return _error(403, error)
except NotFound as error:
    return _error(404, error)
except InvalidRequest as error:
    return _error(400, error)
except Exception as error:
    _logger.exception("unhandled error handling %s %s", request.method, request.path)
    return _error(500, "internal error")
```

`_error(status, error)` construit l'enveloppe `{"status": status, "meta": {"type": "object"}, "data": {"error": str(error)}}`. Le cas `500` ne renvoie jamais `str(error)` ni de trace : uniquement `"internal error"` ; l'exception réelle est journalisée via `IActivityLogger`/le logger du module.

### 2.4 Enveloppe des succès

```python
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
```

`delete`/`discard` (qui renvoient `None`) produisent `data: {}`. `_ok` ne couvre que trois formes : le dict `{"items", "total"}` d'une lecture multiple, une liste nue, et `None`. Toute autre forme de résultat (par exemple l'entier renvoyé par `delete_many`) doit être mise en forme par la route elle-même avant l'appel à `_ok` — `delete_many` appelle `_ok(200, {"deleted": count})`, jamais `_ok(200, count)`.

## 3. Table de routage

Chemins relatifs au préfixe `/api` de la servlet (`request.sub_path`). `<plural>` est résolu en `item_id` par `catalog.get_item_by_plural`.

| Méthode | Chemin | Segments (après split) | Appel |
|---|---|---|---|
| GET | `/crud/<plural>` | `["crud", plural]` | `crud.get_many(item_id, params, subject)` |
| GET | `/crud/<plural>/<id>` | `["crud", plural, id]` | `crud.get_one(item_id, id, params, subject)` |
| POST | `/crud/<plural>` | `["crud", plural]` | `crud.create(item_id, fields, subject)`, succès `201` |
| PUT | `/crud/<plural>/<id>` | `["crud", plural, id]` | `crud.update(item_id, id, fields, subject)` |
| DELETE | `/crud/<plural>/<id>` | `["crud", plural, id]` | `crud.delete(item_id, id, subject)` |
| DELETE | `/crud/<plural>` | `["crud", plural]` | `crud.delete_many(item_id, filter, subject)`, `filter` = `params.get("filter")` (JSON texte ou absent) ; succès : `data: {"deleted": n}` |
| GET | `/drafts/<plural>/<draft>` | `["drafts", plural, draft]` | `drafts.get_many(item_id, draft, params, subject)` |
| GET | `/drafts/<plural>/<id>/<draft>` | `["drafts", plural, id, draft]` | `drafts.get_one(item_id, id, draft, params, subject)` |
| PUT | `/drafts/<plural>/<id>/<draft>` | `["drafts", plural, id, draft]` | `drafts.save(item_id, id, draft, fields, subject)` |
| POST | `/drafts/<plural>/<id>/<draft>/publish` | `["drafts", plural, id, draft, "publish"]` | `drafts.publish(item_id, id, draft, subject)` |
| DELETE | `/drafts/<plural>/<id>/<draft>` | `["drafts", plural, id, draft]` | `drafts.discard(item_id, id, draft, subject)` |
| GET | `/items` | `["items"]` | `catalog.get_items(subject)` |
| GET | `/items/<plural>` | `["items", plural]` | `catalog.get_item_by_plural(plural, subject)` |
| GET | `/items/<plural>/schema` | `["items", plural, "schema"]` | `get_item_by_plural` puis `catalog.get_schema(item_id, subject)` |
| GET | `/items/<plural>/empty` | `["items", plural, "empty"]` | `get_item_by_plural` puis `catalog.get_empty(item_id, subject)` |

Une combinaison méthode/segments non listée, ou un nombre de segments incohérent avec la famille (`crud`/`drafts`/`items`), donne `404` (`data: {"error": "not found"}`), pas `500`.

## 4. Packaging et exemple

```
http_server/
  pyproject.toml
  README.md
  example/conf/application.yml
  example/library/__init__.py
  example/library/books.py
  src/main/python/ycappuccino/http_server/
    __init__.py
    servlet.py
  src/unittest/python/...
```

- **`pyproject.toml`** (uv, `uv_build`) : projet `ycappuccino-http-server`, module `ycappuccino.http_server`, racine `src/main/python`. Dépendances : `ycappuccino-api`, `ycappuccino-core`, `ycappuccino-storage`, `ycappuccino-endpoints-storage`, en sources locales éditables.
- **Supprimés** : `build.py`, `setup.py`, le bundle legacy `ycappuccino/endpoints/bundles/endpoints.py`, `conf/config.yaml`, les tests vides.
- **`.gitignore`** : `data`, `.venv`, `__pycache__`, `dist`, comme les autres dépôts migrés.
- **Exemple** : couche mémoire d'`endpoints_storage`, un modèle `Book`, `config.http_server.active: true` sur un port fixe (`9000`, comme l'exemple legacy). Un composant de démarrage crée un livre via `ICrud` (pas via HTTP, pour rester indépendant du serveur), puis le composant principal du README montre un appel HTTP réel avec `urllib`, dans le test du README.
- **README** : mise en place, table de routage, authentification (`IAuthentication`, ouvert par défaut sans implémentation), enveloppe et erreurs, test d'`ApiServlet` sans framework.

## 5. Tests

| Fichier | Contenu |
|---|---|
| `api` : `test_interfaces.py` | `IAuthentication` est une ABC async |
| `test_servlet.py` (`IsolatedAsyncioTestCase`, faux `ICrud`/`IDrafts`/`IItemCatalog`/`IAuthentication`) | chaque route du tableau, les codes de succès (`200`/`201`), le mapping des 4 erreurs `CrudError` + le `500` générique sans détail, `404` sur chemin inconnu ou segments incohérents, enveloppe `meta.type`/`size` pour liste et objet, `params` transmis tel quel depuis la query, corps JSON invalide → `400`, authentification absente vs présente |
| `test_http_server_framework.py` | démarrage du framework avec `endpoints_storage` (couche mémoire) + `http_server`, vraie requête HTTP via `urllib` (GET, POST, erreur 404, erreur 401 sur un item sécurisé sans `IAuthentication` publiée) |
| `test_readme.py` | les exemples du README s'exécutent |

## 6. Hors périmètre

- `/api/services/...` (endpoints_service, sous-projet suivant).
- Une vraie implémentation d'`IAuthentication` (permissions_app, sous-projet suivant) : le README documente une implémentation de démonstration minimale, pas livrée dans ce dépôt.
- L'analyse de vraies requêtes `multipart/form-data` : l'upload passe par un corps JSON avec `content`/`content64`, déjà géré par `storage`.
- La génération swagger (dépôt `swagger`, sous-projet suivant) : elle décrira ces routes une fois `http_server` et `endpoints_service` en place.

## 7. Risques

- **Pas de vraie authentification livrée ici** : tant que `permissions_app` n'existe pas, tous les items sécurisés restent inaccessibles par HTTP (fermé par défaut, cohérent avec `endpoints_storage`).
- **`multipart/form-data` non supporté** : un client existant qui envoyait un vrai formulaire multipart devra passer par `content64` en JSON ; assumé, il n'y a pas de client vivant à l'heure de cette migration.
- **Un seul segment de méthode HTTP par `IHttpServlet`** : `do_PATCH` n'existe pas (le mécanisme `core` ne génère que GET/POST/PUT/DELETE) ; non nécessaire pour ces routes.
