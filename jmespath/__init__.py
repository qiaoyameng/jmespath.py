from jmespath import parser
from jmespath import analysis
from jmespath.visitor import Options

__version__ = '1.1.0'


def compile(expression):
    return parser.Parser().parse(expression)


def analyze_fields(expression):
    return compile(expression).analyze_fields()


def search(expression, data, options=None):
    return parser.Parser().parse(expression).search(data, options=options)
