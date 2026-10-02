from jmespath import parser
from jmespath.visitor import Options

__version__ = '1.1.0'


def compile(expression):
    return parser.Parser().parse(expression)


def search(expression, data, options=None):
    return parser.Parser().parse(expression).search(data, options=options)


def stream_search(expression, data, options=None):
    return parser.Parser().parse(expression).stream_search(
        data, options=options)
