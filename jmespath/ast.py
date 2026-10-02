# AST nodes have this structure:
# {"type": <node type>", children: [], "value": ""}


class ASTNode(dict):
    def __init__(self, *args, **kwargs):
        super(ASTNode, self).__init__(*args, **kwargs)
        self.start = None
        self.end = None


_UNSET = object()


def _node(node_type, children=None, value=_UNSET):
    node = ASTNode({'type': node_type,
                    'children': [] if children is None else children})
    if value is not _UNSET:
        node['value'] = value
    return node


def comparator(name, first, second):
    return _node('comparator', [first, second], name)


def current_node():
    return _node('current')


def expref(expression):
    return _node('expref', [expression])


def function_expression(name, args):
    return _node('function_expression', args, name)


def field(name):
    return _node('field', value=name)


def filter_projection(left, right, comparator):
    return _node('filter_projection', [left, right, comparator])


def flatten(node):
    return _node('flatten', [node])


def identity():
    return _node('identity')


def index(index):
    return _node('index', value=index)


def index_expression(children):
    return _node('index_expression', children)


def key_val_pair(key_name, node):
    return _node('key_val_pair', [node], key_name)


def literal(literal_value):
    return _node('literal', value=literal_value)


def multi_select_dict(nodes):
    return _node('multi_select_dict', nodes)


def multi_select_list(nodes):
    return _node('multi_select_list', nodes)


def or_expression(left, right):
    return _node('or_expression', [left, right])


def and_expression(left, right):
    return _node('and_expression', [left, right])


def not_expression(expr):
    return _node('not_expression', [expr])


def pipe(left, right):
    return _node('pipe', [left, right])


def projection(left, right):
    return _node('projection', [left, right])


def subexpression(children):
    return _node('subexpression', children)


def slice(start, end, step):
    return _node('slice', [start, end, step])


def value_projection(left, right):
    return _node('value_projection', [left, right])
