from jmespath import parser
from jmespath.visitor import Options
from jmespath.tracing import Tracer, TraceResult

__version__ = '1.1.0'


def compile(expression):
    return parser.Parser().parse(expression)


def search(expression, data, options=None):
    return parser.Parser().parse(expression).search(data, options=options)


def search_traced(expression, data, options=None,
                  max_events=Tracer.DEFAULT_MAX_EVENTS):
    """Evaluate the expression and explain missing results.

    Same as ``search()``, but returns a
    :class:`jmespath.tracing.TraceResult` that pairs the query result
    with a bounded list of trace events explaining why elements are
    absent from the result.  Query execution is identical to
    ``search()``; functions are never re-executed for tracing.
    """
    return parser.Parser().parse(expression).search_traced(
        data, options=options, max_events=max_events)
