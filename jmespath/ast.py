# AST nodes have this structure:
# {"type": <node type>", children: [], "value": ""}


def comparator(name, first, second, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {'type': 'comparator',
         'children': [first, second],
         'value': name})


def current_node(node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': 'current', 'children': []})


def expref(expression, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': 'expref', 'children': [expression]})


def function_expression(name, args, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {'type': 'function_expression', 'children': args, 'value': name})


def field(name, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {"type": "field", "children": [], "value": name})


def filter_projection(left, right, comparator, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({
        'type': 'filter_projection',
        'children': [left, right, comparator]
    })


def flatten(node, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': 'flatten', 'children': [node]})


def identity(node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({"type": "identity", 'children': []})


def index(index, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {"type": "index", "value": index, "children": []})


def index_expression(children, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': "index_expression", 'children': children})


def key_val_pair(key_name, node, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({
        "type": "key_val_pair",
        'children': [node],
        "value": key_name
    })


def literal(literal_value, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {'type': 'literal', 'value': literal_value, 'children': []})


def multi_select_dict(nodes, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({"type": "multi_select_dict", "children": nodes})


def multi_select_list(nodes, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({"type": "multi_select_list", "children": nodes})


def or_expression(left, right, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {'type': 'or_expression', 'children': [left, right]})


def and_expression(left, right, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {'type': 'and_expression', 'children': [left, right]})


def not_expression(expr, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': 'not_expression', 'children': [expr]})


def pipe(left, right, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': 'pipe', 'children': [left, right]})


def projection(left, right, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': 'projection', 'children': [left, right]})


def subexpression(children, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class({'type': 'subexpression', 'children': children})


def slice(start, end, step, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {'type': 'slice', 'children': [start, end, step]})


def value_projection(left, right, node_class=None):
    if node_class is None:
        node_class = dict
    return node_class(
        {'type': 'value_projection', 'children': [left, right]})
