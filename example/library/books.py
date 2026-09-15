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
