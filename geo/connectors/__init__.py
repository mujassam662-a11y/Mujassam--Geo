from .base import STATUSES  # noqa: F401


def all_connectors(config, conn, transport=None):
    from .ga4 import GA4Connector
    from .gsc import GSCConnector
    from .clarity import ClarityConnector
    from .bing import BingConnector
    from .crawler import SiteCrawler
    from .ai_visibility import PerplexityProxy, ClaudeWebSearchProxy
    return [cls(config, conn, transport) for cls in
            (SiteCrawler, GA4Connector, GSCConnector, ClarityConnector, BingConnector, PerplexityProxy, ClaudeWebSearchProxy)]
