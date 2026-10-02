from jmespath import parser
from jmespath.visitor import Options

__version__ = '1.1.0'


def compile(expression):
    return parser.Parser().parse(expression)


def search(expression, data, options=None):
    return parser.Parser().parse(expression).search(data, options=options)


def search_with_trace(expression, data, options=None, trace_limit=100):
    compiled = parser.Parser(enable_locations=True).parse(expression)
    return compiled.search_with_trace(
        data, options=options, trace_limit=trace_limit)
