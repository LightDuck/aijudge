from .models import ChainLink, Effect


class Chain:
    def __init__(self) -> None:
        self._links: list[ChainLink] = []
        self._resolved: list[ChainLink] = []

    def add_link(self, effect: Effect) -> ChainLink:
        link = ChainLink(link_number=len(self._links) + 1, effect=effect)
        self._links.append(link)
        return link

    @property
    def links(self) -> list[ChainLink]:
        return list(self._links)

    @property
    def pending_links(self) -> list[ChainLink]:
        return [link for link in self._links if link not in self._resolved]

    def resolution_order(self) -> list[ChainLink]:
        """Chain links resolve LIFO: the most recently added link resolves first."""
        return sorted(self.pending_links, key=lambda link: link.link_number, reverse=True)

    def resolve_next(self) -> ChainLink:
        order = self.resolution_order()
        if not order:
            raise ValueError("no pending chain links to resolve")
        next_link = order[0]
        self._resolved.append(next_link)
        return next_link
