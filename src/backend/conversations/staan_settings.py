"""Staan (European Search Perspective) settings for the web_search_staan tool."""

from configurations import values


class StaanSettings:
    """Staan settings for the web_search_staan tool.

    Staan is the EU-sovereign search API by European Search Perspective
    (the Ecosia × Qwant joint venture): https://staan.ai / https://docs.staan.ai
    """

    STAAN_API_KEY = values.Value(
        None,
        environ_name="STAAN_API_KEY",
        environ_prefix=None,
    )
    STAAN_API_TIMEOUT = values.IntegerValue(
        # Staan recommends 8-10s when snippet enrichment is enabled.
        10,
        environ_name="STAAN_API_TIMEOUT",
        environ_prefix=None,
    )
    STAAN_SEARCH_MARKET = values.Value(
        # Documented markets: fr-fr, en-us, de-de, en-uk. No nl-nl yet —
        # tune this once Staan ships a Dutch market.
        "en-us",
        environ_name="STAAN_SEARCH_MARKET",
        environ_prefix=None,
    )
    # Number of scored content chunks requested per result (1-10).
    STAAN_MAX_SNIPPETS = values.IntegerValue(
        3,
        environ_name="STAAN_MAX_SNIPPETS",
        environ_prefix=None,
    )
    # Minimum relevance score (0-1) for returned chunks.
    STAAN_MIN_SCORE = values.FloatValue(
        0.1,
        environ_name="STAAN_MIN_SCORE",
        environ_prefix=None,
    )
