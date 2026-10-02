from collections.abc import Mapping

from jmespath import visitor


class _TracedExpression(visitor._Expression):
    def visit(self, node, *args, **kwargs):
        depth = len(self.interpreter._path)
        try:
            return self.interpreter.visit(node, *args, **kwargs)
        finally:
            del self.interpreter._path[depth:]


class TracingTreeInterpreter(visitor.TreeInterpreter):
    def __init__(self, options=None, trace_limit=100):
        super(TracingTreeInterpreter, self).__init__(options)
        if trace_limit < 1:
            raise ValueError('trace_limit must be greater than zero')
        self._trace_limit = trace_limit
        self._path = []
        self.events = []
        self.truncated = False

    def visit_expref(self, node, value):
        return _TracedExpression(node['children'][0], self)

    def visit_subexpression(self, node, value):
        depth = len(self._path)
        result = value
        for child in node['children']:
            result = self.visit(child, result)
        del self._path[depth:]
        return result

    def visit_pipe(self, node, value):
        depth = len(self._path)
        result = value
        for child in node['children']:
            result = self.visit(child, result)
        del self._path[depth:]
        return result

    def visit_index_expression(self, node, value):
        depth = len(self._path)
        result = value
        for child in node['children']:
            result = self.visit(child, result)
        del self._path[depth:]
        return result

    def visit_field(self, node, value):
        field_name = node['value']
        get = getattr(value, 'get', None)
        if get is None:
            return None
        try:
            field_value = get(field_name)
        except AttributeError:
            return None
        is_mapping = isinstance(value, Mapping)
        try:
            field_present = field_name in value if is_mapping else True
        except TypeError:
            field_present = True
        self._path.append(field_name)
        if is_mapping and not field_present:
            self._record(node, 'missing_field', field=field_name)
            return None
        if is_mapping and field_value is None:
            self._record(node, 'explicit_null', field=field_name)
        return field_value

    def visit_index(self, node, value):
        result = super(TracingTreeInterpreter, self).visit_index(node, value)
        if isinstance(value, list):
            index = node['value']
            if index < 0:
                index += len(value)
            if 0 <= index < len(value):
                self._path.append(index)
        return result

    def visit_comparator(self, node, value):
        depth = len(self._path)
        left = self.visit(node['children'][0], value)
        del self._path[depth:]
        right = self.visit(node['children'][1], value)
        del self._path[depth:]
        comparator_func = self.COMPARATOR_FUNC[node['value']]
        if node['value'] in self._EQUALITY_OPS:
            return comparator_func(left, right)
        if not (visitor._is_comparable(left) and
                visitor._is_comparable(right)):
            return None
        return comparator_func(left, right)

    def visit_function_expression(self, node, value):
        depth = len(self._path)
        resolved_args = []
        for child in node['children']:
            del self._path[depth:]
            resolved_args.append(self.visit(child, value))
        del self._path[depth:]
        return self._functions.call_function(node['value'], resolved_args)

    def visit_filter_projection(self, node, value):
        base_depth = len(self._path)
        base = self.visit(node['children'][0], value)
        if not isinstance(base, list):
            del self._path[base_depth:]
            return None
        projected_depth = len(self._path)
        comparator_node = node['children'][2]
        collected = []
        for index, element in enumerate(base):
            del self._path[projected_depth:]
            self._path.append(index)
            item_depth = len(self._path)
            matched = self._is_true(self.visit(comparator_node, element))
            del self._path[item_depth:]
            if not matched:
                self._record(comparator_node, 'filter_not_passed')
                continue
            current = self.visit(node['children'][1], element)
            if current is not None:
                collected.append(current)
        del self._path[base_depth:]
        return collected

    def visit_flatten(self, node, value):
        base_depth = len(self._path)
        base = self.visit(node['children'][0], value)
        if not isinstance(base, list):
            del self._path[base_depth:]
            return None
        projected_depth = len(self._path)
        merged_list = []
        for index, element in enumerate(base):
            del self._path[projected_depth:]
            self._path.append(index)
            if isinstance(element, list):
                for inner_index in range(len(element)):
                    self._path.append(inner_index)
                    merged_list.append(element[inner_index])
                    self._path.pop()
            else:
                merged_list.append(element)
        del self._path[base_depth:]
        return merged_list

    def visit_projection(self, node, value):
        base_depth = len(self._path)
        base = self.visit(node['children'][0], value)
        if not isinstance(base, list):
            del self._path[base_depth:]
            return None
        projected_depth = len(self._path)
        collected = []
        for index, element in enumerate(base):
            del self._path[projected_depth:]
            self._path.append(index)
            current = self.visit(node['children'][1], element)
            if current is not None:
                collected.append(current)
        del self._path[base_depth:]
        return collected

    def visit_value_projection(self, node, value):
        base_depth = len(self._path)
        base = self.visit(node['children'][0], value)
        if not hasattr(base, 'values'):
            del self._path[base_depth:]
            return None
        try:
            values = base.values()
        except AttributeError:
            del self._path[base_depth:]
            return None
        projected_depth = len(self._path)
        collected = []
        for key, element in values:
            del self._path[projected_depth:]
            self._path.append(key)
            current = self.visit(node['children'][1], element)
            if current is not None:
                collected.append(current)
        del self._path[base_depth:]
        return collected

    def visit_or_expression(self, node, value):
        depth = len(self._path)
        matched = self.visit(node['children'][0], value)
        if self._is_false(matched):
            del self._path[depth:]
            matched = self.visit(node['children'][1], value)
        del self._path[depth:]
        return matched

    def visit_and_expression(self, node, value):
        depth = len(self._path)
        matched = self.visit(node['children'][0], value)
        if self._is_false(matched):
            del self._path[depth:]
            return matched
        del self._path[depth:]
        matched = self.visit(node['children'][1], value)
        del self._path[depth:]
        return matched

    def visit_not_expression(self, node, value):
        depth = len(self._path)
        original_result = self.visit(node['children'][0], value)
        del self._path[depth:]
        if visitor._is_actual_number(original_result) and original_result == 0:
            return False
        return not original_result

    def visit_multi_select_dict(self, node, value):
        if value is None:
            return None
        depth = len(self._path)
        collected = self._dict_cls()
        for child in node['children']:
            del self._path[depth:]
            collected[child['value']] = self.visit(child, value)
        del self._path[depth:]
        return collected

    def visit_multi_select_list(self, node, value):
        if value is None:
            return None
        depth = len(self._path)
        collected = []
        for child in node['children']:
            del self._path[depth:]
            collected.append(self.visit(child, value))
        del self._path[depth:]
        return collected

    def visit_key_val_pair(self, node, value):
        depth = len(self._path)
        result = self.visit(node['children'][0], value)
        del self._path[depth:]
        return result

    def _record(self, node, event_type, field=None):
        if len(self.events) >= self._trace_limit and not self.truncated:
            self.events.append({'type': 'trace_truncated'})
            self.truncated = True
        if self.truncated:
            return
        event = {
            'type': event_type,
            'expression_start': node.get('start', 0),
            'expression_end': node.get('end', 0),
            'input_path': self._render_path(),
        }
        if field is not None:
            event['field'] = field
        self.events.append(event)

    def _render_path(self):
        rendered = '$'
        for segment in self._path:
            if isinstance(segment, int):
                rendered += '[%d]' % segment
            elif isinstance(segment, str) and segment.isidentifier():
                rendered += '.' + segment
            else:
                escaped = str(segment).replace(
                    '\\', '\\\\').replace("'", "\\'")
                rendered += "['%s']" % escaped
        return rendered
