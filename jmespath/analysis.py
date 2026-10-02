from jmespath import functions
from jmespath import visitor


ANY_FIELD = object()
ANY_INDEX = object()


class FieldAccessAnalysis(object):
    """Static field access information for a JMESPath expression."""

    __slots__ = ('possible', 'unconditional')

    def __init__(self, possible, unconditional):
        self.possible = frozenset(possible)
        self.unconditional = frozenset(unconditional)

    def to_dict(self):
        return {
            'possible': [self._path_to_dict(path)
                         for path in self._sorted(self.possible)],
            'unconditional': [self._path_to_dict(path)
                              for path in self._sorted(self.unconditional)],
        }

    def covers(self, path):
        path = tuple(path)
        for candidate in self.possible:
            if len(candidate) > len(path):
                continue
            for candidate_segment, path_segment in zip(candidate, path):
                if candidate_segment is ANY_FIELD:
                    if not isinstance(path_segment, str):
                        break
                elif candidate_segment is ANY_INDEX:
                    if (not isinstance(path_segment, int) and
                            path_segment != '*'):
                        break
                elif candidate_segment != path_segment:
                    break
            else:
                return True
        return False

    def __eq__(self, other):
        return (isinstance(other, FieldAccessAnalysis) and
                self.possible == other.possible and
                self.unconditional == other.unconditional)

    def __repr__(self):
        return 'FieldAccessAnalysis(possible=%r, unconditional=%r)' % (
            self.possible, self.unconditional)

    @staticmethod
    def _path_to_dict(path):
        serialized = []
        for segment in path:
            if segment is ANY_FIELD:
                serialized.append({'type': 'any_field'})
            elif segment is ANY_INDEX:
                serialized.append({'type': 'any_index'})
            else:
                serialized.append(segment)
        return serialized

    @staticmethod
    def _sorted(paths):
        def sort_key(path):
            return tuple(
                (1, '') if segment is ANY_FIELD else
                (2, '') if segment is ANY_INDEX else
                (0, segment)
                for segment in path
            )
        return sorted(paths, key=sort_key)


def analyze_fields(ast):
    return FieldAccessAnalyzer().analyze(ast)


class FieldAccessAnalyzer(visitor.Visitor):
    def __init__(self):
        super(FieldAccessAnalyzer, self).__init__()
        self._possible = set()
        self._unconditional = set()

    def analyze(self, node):
        root = (((), False),)
        result_sources = self.visit(node, root)
        if node['type'] == 'current':
            self._mark_whole(result_sources, False)
        if node['type'] == 'field':
            self._mark_field(result_sources, False)
        if node['type'] in ('subexpression', 'index_expression'):
            self._mark_terminal_field(
                node['children'][-1], result_sources)
        return FieldAccessAnalysis(self._possible, self._unconditional)

    def visit_subexpression(self, node, sources):
        current = sources
        for child in node['children']:
            current = self.visit(child, current)
        return current

    def visit_index_expression(self, node, sources):
        return self.visit_subexpression(node, sources)

    def visit_field(self, node, sources):
        result = []
        name = node['value']
        for path, conditional in sources:
            field_path = path + (name,)
            self._record(field_path, conditional)
            result.append((field_path, conditional))
        return tuple(result)

    def visit_current(self, node, sources):
        return sources

    def visit_identity(self, node, sources):
        return sources

    def visit_literal(self, node, sources):
        return ()

    def visit_index(self, node, sources):
        for path, _ in sources:
            self._record(path + (ANY_INDEX,), True)
        return sources

    def visit_slice(self, node, sources):
        return sources

    def visit_flatten(self, node, sources):
        return self.visit(node['children'][0], sources)

    def visit_projection(self, node, sources):
        left = self.visit(node['children'][0], sources)
        self._mark_index(self._conditional(left))
        projected = self._conditional(left)
        return self.visit(node['children'][1], projected)

    def visit_value_projection(self, node, sources):
        left = self.visit(node['children'][0], sources)
        projected = []
        for path, conditional in left:
            wildcard_path = path + (ANY_FIELD,)
            self._record(wildcard_path, conditional)
            projected.append((wildcard_path, True))
        projected_sources = tuple(projected)
        return self.visit(node['children'][1], projected_sources)

    def visit_filter_projection(self, node, sources):
        left = self.visit(node['children'][0], sources)
        self._mark_index(self._conditional(left))
        elements = self._conditional(left)
        self.visit(node['children'][2], elements)
        return self.visit(node['children'][1], elements)

    def visit_comparator(self, node, sources):
        self.visit(node['children'][0], sources)
        self.visit(node['children'][1], sources)
        return ()

    def visit_or_expression(self, node, sources):
        left = self.visit(node['children'][0], sources)
        right = self.visit(
            node['children'][1], self._conditional(sources))
        self._mark_branch_result(node['children'][0], left)
        self._mark_branch_result(node['children'][1], right)
        return self._conditional(left) + right

    def visit_and_expression(self, node, sources):
        left = self.visit(node['children'][0], sources)
        right = self.visit(
            node['children'][1], self._conditional(sources))
        self._mark_branch_result(node['children'][0], left)
        self._mark_branch_result(node['children'][1], right)
        return self._conditional(left) + right

    def visit_not_expression(self, node, sources):
        self.visit(node['children'][0], sources)
        return ()

    def visit_pipe(self, node, sources):
        left = self.visit(node['children'][0], sources)
        right_node = node['children'][1]
        right = self.visit(right_node, left)
        if right_node['type'] in (
                'field', 'subexpression', 'index_expression'):
            self._mark_terminal_field(
                right_node['children'][-1]
                if right_node['type'] != 'field' else right_node,
                right)
        return right

    def visit_multi_select_list(self, node, sources):
        for child in node['children']:
            if child['type'] in ('current', 'identity'):
                self._mark_field(sources, False)
            self.visit(child, sources)
        return ()

    def visit_multi_select_dict(self, node, sources):
        for child in node['children']:
            value = child['children'][0]
            if value['type'] in ('current', 'identity'):
                self._mark_field(sources, False)
            self.visit(child, sources)
        return ()

    def visit_key_val_pair(self, node, sources):
        return self.visit(node['children'][0], sources)

    def visit_expref(self, node, sources):
        return ()

    def visit_function_expression(self, node, sources):
        name = node['value']
        args = node['children']
        resolved = []
        expression_refs = []
        for arg in args:
            if arg['type'] == 'expref':
                resolved.append(None)
                expression_refs.append(arg['children'][0])
            else:
                resolved.append(self.visit(arg, sources))

        if name not in functions.Functions.FUNCTION_TABLE:
            return self._visit_unknown_function(
                sources, resolved, expression_refs)

        if name == 'map' and len(args) >= 2:
            input_sources = self._conditional(resolved[1])
            self._mark_index(input_sources)
            return self.visit(args[0]['children'][0], input_sources)

        if name in ('sort_by', 'min_by', 'max_by') and resolved:
            array_sources = self._conditional(resolved[0])
            self._mark_index(array_sources)
            for expression in expression_refs:
                self.visit(expression, array_sources)
            return array_sources

        if name == 'merge':
            for arg_sources in resolved:
                for path, conditional in arg_sources:
                    self._record(path + (ANY_FIELD,), conditional)
            return ()

        if name == 'values':
            result = []
            for arg_sources in resolved:
                for path, _ in arg_sources:
                    wildcard_path = path + (ANY_FIELD,)
                    self._record(wildcard_path, False)
                    result.append((wildcard_path, True))
            return tuple(result)

        if name == 'keys':
            for arg_sources in resolved:
                for path, conditional in arg_sources:
                    self._record(path + (ANY_FIELD,), conditional)
            return ()

        if name == 'not_null':
            result = ()
            for arg_sources in resolved:
                self._mark_whole(arg_sources, False)
                result += self._conditional(arg_sources)
            return result

        if name == 'to_array':
            result = ()
            for arg_sources in resolved:
                result += arg_sources
            return result

        if name in ('reverse', 'sort'):
            result = ()
            for arg_sources in resolved:
                conditional_sources = self._conditional(arg_sources)
                self._mark_index(conditional_sources)
                result += conditional_sources
            return result

        return ()

    def _visit_unknown_function(self, sources, resolved, expression_refs):
        candidates = ()
        for arg_sources in resolved:
            if arg_sources is None:
                continue
            candidates += self._conditional(arg_sources)
            self._mark_whole(arg_sources, False)

        call_sources = ()
        if expression_refs:
            call_sources = self._conditional(sources)
        result = candidates
        for expression in expression_refs:
            if self._uses_current(expression):
                self._mark_whole(call_sources, True)
            result += self.visit(expression, call_sources)
        return result

    def _uses_current(self, node):
        if node['type'] == 'current':
            return True
        if node['type'] == 'expref':
            return False
        return any(self._uses_current(child) for child in node['children'])

    def _record(self, path, conditional):
        if not path:
            return
        self._possible.add(path)
        if not conditional:
            self._unconditional.add(path)

    def _mark_whole(self, sources, force_conditional):
        for path, conditional in sources:
            self._mark_whole_path(
                path, conditional or force_conditional)

    def _mark_whole_path(self, path, conditional):
        if not path or path[-1] is not ANY_FIELD:
            self._record(path + (ANY_FIELD,), conditional)
        if not path or path[-1] is not ANY_INDEX:
            self._record(path + (ANY_INDEX,), conditional)

    def _mark_field(self, sources, force_conditional):
        for path, conditional in sources:
            self._record(
                path + (ANY_FIELD,),
                conditional or force_conditional)

    def _mark_terminal_field(self, node, sources):
        if node['type'] == 'field':
            self._mark_field(sources, False)
        elif node['type'] in ('subexpression', 'index_expression'):
            self._mark_terminal_field(node['children'][-1], sources)

    def _mark_branch_result(self, node, sources):
        self._mark_terminal_field(node, sources)

    def _mark_index(self, sources):
        for path, conditional in sources:
            self._record(path + (ANY_INDEX,), conditional)

    @staticmethod
    def _conditional(sources):
        return tuple((path, True) for path, _ in sources)
