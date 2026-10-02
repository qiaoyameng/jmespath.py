"""Optional query tracing that explains missing results.

This module implements an opt-in tracing layer used by
``jmespath.search_traced()`` and ``ParsedResult.search_traced()``.
It explains why elements are absent from a query result: missing
fields, explicit nulls, filter rejections and projection omissions.

Tracing is purely observational.  The interpreter records events while
it evaluates the expression exactly once, so custom functions and
short-circuited expressions are never re-executed to produce an
explanation, and the query result is identical to an untraced search.

Events never contain the actual data values (which may be sensitive).
Each event records only the event kind, the input path, the position
within the expression and a short human readable detail string.
"""


class Tracer(object):
    """Collects trace events during a single query evaluation.

    At most ``max_events`` events are recorded.  Once the limit is
    reached, ``truncated`` is set to True and further events are
    dropped, but query execution is unaffected.
    """

    #: Default upper bound on the number of recorded events.
    DEFAULT_MAX_EVENTS = 100

    def __init__(self, max_events=DEFAULT_MAX_EVENTS):
        self.max_events = max_events
        self.events = []
        self.truncated = False

    def record(self, kind, path, expression, detail):
        if self.max_events is not None and \
                len(self.events) >= self.max_events:
            self.truncated = True
            return
        self.events.append({
            'kind': kind,
            'path': list(path),
            'expression': list(expression),
            'detail': detail,
        })


class TraceResult(object):
    """The outcome of a traced query.

    :ivar result: The query result, identical to what
        ``jmespath.search()`` would return.
    :ivar events: A list of event dicts, each with the keys
        ``kind``, ``path``, ``expression`` and ``detail``.
    :ivar truncated: True if events were dropped because the
        ``max_events`` limit was reached.
    """

    def __init__(self, result, events, truncated):
        self.result = result
        self.events = events
        self.truncated = truncated

    def __repr__(self):
        return 'TraceResult(result=%r, events=%r, truncated=%r)' % (
            self.result, self.events, self.truncated)
