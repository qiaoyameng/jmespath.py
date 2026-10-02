from jmespath import functions as functions_module
from jmespath.visitor import Visitor


FIELD = 'field'
ANY_FIELD = 'any_field'
ANY_DESCENDANT_FIELDS = 'any_descendant_fields'

_WILDCARD = (ANY_FIELD, None)
_DESCENDANTS = (ANY_DESCENDANT_FIELDS, None)


class FieldAccessAnalysis(dict):
    """Field paths accessed by a compiled JMESPath expression."""

    def __init__(self, possible_paths, unconditional_paths):
        super(FieldAccessAnalysis, self).__init__(
            possible_paths=possible_paths,
            unconditional_paths=unconditional_paths)
        self.possible_paths = possible_paths
        self.unconditional_paths = unconditional_paths

    def to_dict(self):
        return {
            'possible_paths': self.possible_paths,
            'unconditional_paths': self.unconditional_paths,
        }


class FieldAccessAnalyzer(Visitor):
    def __init__(self):
        super(FieldAccessAnalyzer, self).__init__()
        self._possible = set()
        self._unconditional = set()
        self._builtin_functions = set(
            functions_module.Functions.FUNCTION_TABLE)

    def analyze(self, node):
        self._possible = set()
        self._unconditional = set()
        sources = self.visit(node, {(): True})
        for path, guaranteed in sources.items():
            if not path:
                self._record_subtree(path, guaranteed)
                continue
            self._retain_source(path, guaranteed)
        return FieldAccessAnalysis(
            [self._public_path(path) for path in self._sorted(self._possible)],
            [self._public_path(path)
             for path in self._sorted(self._unconditional)])

    def visit_current(self, node, sources):
        return dict(sources)

    def visit_identity(self, node, sources):
        return dict(sources)

    def visit_literal(self, node, sources):
        return {}

    def visit_expref(self, node, sources):
        return {}

    def visit_field(self, node, sources):
        result = {}
        segment = (FIELD, node['value'])
        for source, guaranteed in sources.items():
            if source and source[-1][0] == ANY_DESCENDANT_FIELDS:
                path = source
            else:
                path = source + (segment,)
            self._record_path(path, guaranteed)
            if path in result:
                result[path] = result[path] and guaranteed
            else:
                result[path] = guaranteed
        return result

    def visit_subexpression(self, node, sources):
        result = sources
        for child in node['children']:
            result = self.visit(child, result)
        return result

    def visit_index_expression(self, node, sources):
        result = sources
        for child in node['children']:
            result = self.visit(child, result)
        return result

    def visit_index(self, node, sources):
        return dict(sources)

    def visit_slice(self, node, sources):
        return dict(sources)

    def visit_flatten(self, node, sources):
        return self.visit(node['children'][0], sources)

    def visit_projection(self, node, sources):
        projected = self.visit(node['children'][0], sources)
        return self.visit(node['children'][1], projected)

    def visit_filter_projection(self, node, sources):
        projected = self.visit(node['children'][0], sources)
        self.visit(node['children'][2], projected)
        conditional = self._with_guarantee(projected, False)
        return self.visit(node['children'][1], conditional)

    def visit_value_projection(self, node, sources):
        projected = self.visit(node['children'][0], sources)
        values = {}
        for source, guaranteed in projected.items():
            path = source + (_WILDCARD,)
            self._record_path(path, guaranteed)
            values[path] = guaranteed
        return self.visit(node['children'][1], values)

    def visit_pipe(self, node, sources):
        left = self.visit(node['children'][0], sources)
        return self.visit(node['children'][1], left)

    def visit_key_val_pair(self, node, sources):
        return self.visit(node['children'][0], sources)

    def visit_multi_select_dict(self, node, sources):
        return self._visit_multi_select(node, sources)

    def visit_multi_select_list(self, node, sources):
        return self._visit_multi_select(node, sources)

    def visit_comparator(self, node, sources):
        left = self.visit(node['children'][0], sources)
        right = self.visit(node['children'][1], sources)
        for path, guaranteed in self._merge(left, right).items():
            if not path:
                self._record_subtree(path, guaranteed)
                continue
            self._record_path(path, guaranteed)
        return {}

    def visit_not_expression(self, node, sources):
        result = self.visit(node['children'][0], sources)
        for path in result:
            self._record_path(path, False)
        return {}

    def visit_or_expression(self, node, sources):
        left = self.visit(node['children'][0], sources)
        for path in left:
            self._record_path(path, False)
        conditional_sources = self._with_guarantee(sources, False)
        right = self.visit(node['children'][1], conditional_sources)
        for path in right:
            self._record_path(path, False)
        return self._with_guarantee(self._merge(left, right), False)

    def visit_and_expression(self, node, sources):
        left = self.visit(node['children'][0], sources)
        for path in left:
            self._record_path(path, False)
        conditional_sources = self._with_guarantee(sources, False)
        right = self.visit(node['children'][1], conditional_sources)
        for path in right:
            self._record_path(path, False)
        return self._with_guarantee(self._merge(left, right), False)

    def visit_function_expression(self, node, sources):
        argument_sources = []
        expression_refs = []
        for child in node['children']:
            if child['type'] == 'expref':
                expression_refs.append(child['children'][0])
            else:
                argument_sources.append(self.visit(child, sources))

        name = node['value']
        if name not in self._builtin_functions:
            return self._visit_unknown_function(
                argument_sources, expression_refs, sources)

        if name == 'map':
            if argument_sources and expression_refs:
                return self.visit(expression_refs[0], argument_sources[0])
            return {}
        if name in ('sort_by', 'min_by', 'max_by'):
            if argument_sources and expression_refs:
                self.visit(expression_refs[0], argument_sources[0])
            guaranteed = name == 'sort_by'
            return self._with_guarantee(argument_sources[0], guaranteed)
        if name == 'merge':
            result = {}
            for argument in argument_sources:
                for path, guaranteed in argument.items():
                    self._record_path(path, guaranteed)
                result = self._merge(result, argument)
            return result
        if name == 'values':
            result = {}
            for argument in argument_sources:
                for source, guaranteed in argument.items():
                    path = source + (_WILDCARD,)
                    self._record_path(path, guaranteed)
                    result[path] = guaranteed
            return result
        if name == 'keys':
            for argument in argument_sources:
                for source, guaranteed in argument.items():
                    self._record_path(source + (_WILDCARD,), guaranteed)
            return {}
        if name == 'contains':
            self._visit_contains(node, argument_sources)
            return {}
        if name in ('length', 'to_string'):
            for argument in argument_sources:
                for path, guaranteed in argument.items():
                    self._record_path(path, guaranteed)
                    self._record_subtree(path, False)
            return {}
        if name == 'type':
            for argument in argument_sources:
                for path, guaranteed in argument.items():
                    self._record_path(path, guaranteed)
            return {}
        if name in ('reverse', 'sort'):
            result = {}
            for argument in argument_sources:
                result = self._merge(result, argument)
            return result
        if name == 'not_null':
            result = {}
            for argument in argument_sources:
                result = self._merge(result, argument)
            return self._with_guarantee(result, False)
        if name == 'to_array':
            result = {}
            for argument in argument_sources:
                result = self._merge(result, argument)
            return result
        return {}

    def _visit_multi_select(self, node, sources):
        for child in node['children']:
            result = self.visit(child, sources)
            for path, guaranteed in result.items():
                if not path:
                    self._record_subtree(path, guaranteed)
                    continue
                self._retain_source(path, guaranteed)
        return {}

    def _visit_unknown_function(self, argument_sources, expression_refs,
                                sources):
        for argument in argument_sources:
            for path in argument:
                self._record_subtree(path, False)

        result = {}
        candidates = [self._with_guarantee(sources, False)]
        candidates.extend(self._with_guarantee(argument, False)
                          for argument in argument_sources)
        for expression in expression_refs:
            for candidate in candidates:
                result = self._merge(
                    result, self.visit(expression, candidate))
        for argument in argument_sources:
            result = self._merge(result, argument)
        return self._with_guarantee(result, False)

    def _visit_contains(self, node, argument_sources):
        if not argument_sources:
            return
        subject = argument_sources[0]
        search_node = node['children'][1]
        if (search_node['type'] == 'literal' and
                isinstance(search_node['value'], str)):
            segment = (FIELD, search_node['value'])
            for source in subject:
                self._record_path(source + (segment,), False)
        else:
            for path, guaranteed in subject.items():
                self._record_path(path, guaranteed)
                self._record_subtree(path, False)

    def _record_path(self, path, guaranteed):
        for index in range(1, len(path) + 1):
            prefix = path[:index]
            self._possible.add(prefix)
            if guaranteed:
                self._unconditional.add(prefix)

    def _record_subtree(self, path, guaranteed):
        self._record_path(path + (_DESCENDANTS,), guaranteed)

    def _retain_source(self, path, guaranteed):
        if path[-1][0] == ANY_DESCENDANT_FIELDS:
            self._record_path(path, guaranteed)
        elif path[-1][0] == ANY_FIELD:
            self._record_path(path, guaranteed)
            self._record_subtree(path, guaranteed)
        else:
            self._record_path(path, guaranteed)

    @staticmethod
    def _with_guarantee(sources, guaranteed):
        return {path: guaranteed for path in sources}

    @staticmethod
    def _merge(left, right):
        result = dict(left)
        for path, guaranteed in right.items():
            if path in result:
                result[path] = result[path] and guaranteed
            else:
                result[path] = guaranteed
        return result

    @staticmethod
    def _sorted(paths):
        def key(path):
            result = []
            for kind, value in path:
                if kind == FIELD:
                    result.append((0, value))
                elif kind == ANY_FIELD:
                    result.append((1, ''))
                else:
                    result.append((2, ''))
            return result
        return sorted(paths, key=key)

    @staticmethod
    def _public_path(path):
        result = []
        for kind, value in path:
            if kind == FIELD:
                result.append({'type': FIELD, 'name': value})
            elif kind == ANY_FIELD:
                result.append({'type': ANY_FIELD})
            else:
                result.append({'type': ANY_DESCENDANT_FIELDS})
        return result


def analyze_fields(expression):
    from jmespath import parser
    return parser.Parser().parse(expression).analyze_fields()
