from jmespath import exceptions
from jmespath import visitor


_SORT_FUNCTIONS = frozenset(['sort', 'sort_by'])


def compile_stream_plan(node, expression=None):
    return _PlanBuilder(expression).compile(node)


def stream_search_plan(plan, data, options=None):
    interpreter = visitor.TreeInterpreter(options)
    source = iter(data)
    try:
        if plan['kind'] == 'projection':
            yield from _project(source, interpreter, plan)
        else:
            yield from _filter(source, interpreter, plan)
    finally:
        close = getattr(source, 'close', None)
        if close is not None:
            close()


def _project(source, interpreter, plan):
    for element in _read_source(source, plan['source']):
        current = interpreter.visit(plan['right'], element)
        if current is not None:
            yield current


def _filter(source, interpreter, plan):
    for element in _read_source(source, plan['source']):
        current_condition = interpreter.visit(plan['condition'], element)
        if interpreter._is_true(current_condition):
            current = interpreter.visit(plan['right'], element)
            if current is not None:
                yield current


def _read_source(source, source_plan):
    if source_plan is None:
        yield from source
    elif source_plan[0] == 'slice':
        _, start, stop, step = source_plan
        if start < stop:
            for index, element in enumerate(source):
                if index < start:
                    continue
                if (index - start) % step != 0:
                    continue
                if index >= stop:
                    break
                yield element
                if index + step >= stop:
                    break
    else:
        yield from _flatten(source)


def _flatten(values):
    for value in values:
        if not isinstance(value, list):
            if value is not None:
                yield value
            continue
        for element in value:
            if isinstance(element, list):
                for nested in element:
                    yield nested
            else:
                yield element


class _PlanBuilder(object):
    def __init__(self, expression):
        self.expression = expression

    def compile(self, node):
        node_type = node['type']
        if node_type == 'projection':
            left, right = node['children']
            return {
                'kind': 'projection',
                'source': self._compile_source(left),
                'right': self._item_expression(right),
            }
        if node_type == 'filter_projection':
            left, right, condition = node['children']
            if left['type'] != 'identity':
                self._unsupported()
            return {
                'kind': 'filter_projection',
                'source': None,
                'right': self._item_expression(right),
                'condition': self._item_expression(condition),
            }
        self._unsupported()

    def _compile_source(self, node):
        if node['type'] == 'identity':
            return None
        flatten_identity = (
            node['type'] == 'flatten' and
            self._is_identity(node['children'][0])
        )
        if flatten_identity:
            return ('flatten',)
        if node['type'] == 'index_expression':
            left, right = node['children']
            if self._is_identity(left) and right['type'] == 'slice':
                return ('slice',) + self._finite_slice(right)
        self._unsupported()

    def _finite_slice(self, node):
        start, stop, step = node['children']
        if step is not None and step <= 0:
            self._unsupported()
        if start is not None and start < 0:
            self._unsupported()
        if stop is None or stop < 0:
            self._unsupported()
        if start is None:
            start = 0
        if stop < start:
            stop = start
        return start, stop, step or 1

    def _item_expression(self, node):
        self._validate_item(node)
        return node

    def _validate_item(self, node):
        node_type = node['type']
        if node_type == 'function_expression':
            if node['value'] in _SORT_FUNCTIONS:
                self._unsupported()
        elif node_type == 'index' and node['value'] < 0:
            self._unsupported()
        elif node_type == 'slice':
            self._validate_item_slice(node)

        for child in node.get('children', []):
            if not isinstance(child, dict):
                continue
            self._validate_item(child)

    def _validate_item_slice(self, node):
        start, stop, step = node['children']
        if step is not None and step <= 0:
            self._unsupported()
        if (start is not None and start < 0) or (stop is not None and
                                                 stop < 0):
            self._unsupported()

    def _is_identity(self, node):
        return node['type'] == 'identity'

    def _unsupported(self):
        raise exceptions.StreamUnsupportedError(self.expression)
