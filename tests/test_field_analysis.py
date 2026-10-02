import unittest

import jmespath
from jmespath import functions


ANY_FIELD = 'any_field'
ANY_DESCENDANT_FIELDS = 'any_descendant_fields'


class TrackingDict(dict):
    def __init__(self, value, path, reads):
        super(TrackingDict, self).__init__(value)
        self._path = path
        self._reads = reads

    def _read(self, name, value):
        path = self._path + (name,)
        self._reads.add(path)
        return _wrap(value, path, self._reads)

    def __getitem__(self, name):
        return self._read(name, super(TrackingDict, self).__getitem__(name))

    def get(self, name, default=None):
        if super(TrackingDict, self).__contains__(name):
            return self._read(name, super(TrackingDict, self).get(name))
        self._reads.add(self._path + (name,))
        return default

    def values(self):
        self._reads.add(self._path + ('*',))
        return [_wrap(value, self._path + (name,), self._reads)
                for name, value in super(TrackingDict, self).items()]

    def keys(self):
        self._reads.add(self._path + ('*',))
        return list(super(TrackingDict, self).keys())

    def items(self):
        self._reads.add(self._path + ('*',))
        return [(name, self._read(name, value))
                for name, value in super(TrackingDict, self).items()]

    def __iter__(self):
        self._reads.add(self._path + ('*',))
        return super(TrackingDict, self).__iter__()

    def __len__(self):
        self._reads.add(self._path + ('*',))
        return super(TrackingDict, self).__len__()

    def __contains__(self, name):
        self._reads.add(self._path + (name,))
        return super(TrackingDict, self).__contains__(name)


TrackingDict.__name__ = 'dict'


class TrackingList(list):
    def __init__(self, value, path, reads):
        super(TrackingList, self).__init__(value)
        self._path = path
        self._reads = reads

    def __getitem__(self, index):
        value = super(TrackingList, self).__getitem__(index)
        if isinstance(index, slice):
            return [_wrap(item, self._path, self._reads) for item in value]
        return _wrap(value, self._path, self._reads)

    def __iter__(self):
        for value in super(TrackingList, self).__iter__():
            yield _wrap(value, self._path, self._reads)


TrackingList.__name__ = 'list'


def _wrap(value, path, reads):
    if isinstance(value, dict):
        return TrackingDict(value, path, reads)
    if isinstance(value, list):
        return TrackingList(value, path, reads)
    return value


def internal_path(path):
    result = []
    for segment in path:
        if segment['type'] == 'field':
            result.append(segment['name'])
        elif segment['type'] == ANY_FIELD:
            result.append('*')
        else:
            result.append('**')
    return tuple(result)


def path_covers(pattern, actual):
    pattern_index = 0
    actual_index = 0
    while pattern_index < len(pattern):
        segment = pattern[pattern_index]
        if segment == '**':
            return True
        if actual_index == len(actual):
            return False
        if segment == '*' or segment == actual[actual_index]:
            pattern_index += 1
            actual_index += 1
        else:
            return False
    return True


class ExplodingFunctions(functions.Functions):
    @functions.signature({'types': []})
    def _func_inspect(self, value):
        raise AssertionError('custom function must not be invoked')


class FieldAnalysisCases(unittest.TestCase):
    def assert_runtime_reads_covered(self, expression, datasets):
        parsed = jmespath.compile(expression)
        analysis = parsed.analyze_fields()
        possible = [internal_path(path) for path in analysis['possible_paths']]
        for dataset in datasets:
            reads = set()
            parsed.search(_wrap(dataset, (), reads))
            for actual in reads:
                self.assertTrue(
                    any(path_covers(pattern, actual) for pattern in possible),
                    '%r accessed %r, static paths=%r' % (
                        expression, actual, possible))

    def test_result_has_stable_structure(self):
        analysis = jmespath.compile('"a.b"."c-d"').analyze_fields()
        expected = [
            [{'type': 'field', 'name': 'a.b'}],
            [{'type': 'field', 'name': 'a.b'},
             {'type': 'field', 'name': 'c-d'}],
        ]
        self.assertEqual(analysis['possible_paths'], expected)
        self.assertEqual(analysis['unconditional_paths'], expected)
        self.assertEqual(analysis.to_dict(), {
            'possible_paths': expected,
            'unconditional_paths': expected,
        })
        self.assertTrue(all(isinstance(segment, dict)
                            for path in analysis['possible_paths']
                            for segment in path))

    def test_projection_filter_slice_and_flatten(self):
        datasets = {
            'projection': [
                {'items': [
                    {'name': 'one', 'age': 1},
                    {'name': 'two', 'age': 2}]},
                {'items': []},
            ],
            'filter': [
                {'items': [
                    {'name': 'one', 'active': True},
                    {'name': 'two', 'active': False}]},
                {'items': []},
            ],
            'slice': [
                {'items': [
                    {'name': 'one'}, {'name': 'two'}, {'name': 'three'}]},
                {'items': []},
            ],
            'flatten': [
                {'items': [[{'name': 'one'}], [{'name': 'two'}]]},
                {'items': []},
            ],
        }
        cases = {
            'projection': 'items[*].name',
            'filter': 'items[?active == `true`].name',
            'slice': 'items[0:2].name',
            'flatten': 'items[].name',
        }
        for name, expression in cases.items():
            self.assert_runtime_reads_covered(expression, datasets[name])

    def test_object_and_value_projections(self):
        datasets = [
            {'maps': {
                'one': {'name': 'a', 'unused': 1},
                'two': {'name': 'b'}}},
            {'maps': {}},
            {'names': {'one': 'x', 'two': 'y'},
             'unused': {}},
        ]
        self.assert_runtime_reads_covered('maps.*.name', datasets[:2])
        self.assert_runtime_reads_covered('*', [datasets[1], datasets[2]])

    def test_pipe_and_short_circuiting(self):
        datasets = [
            {'item': {'name': 'present', 'age': 3},
             'fallback': 'other'},
            {'item': {}, 'fallback': 'other'},
            {'item': {'name': 'present'}, 'fallback': 'other'},
        ]
        self.assert_runtime_reads_covered('item | name', datasets[:2])
        self.assert_runtime_reads_covered('item.name || fallback', datasets)
        self.assert_runtime_reads_covered('item.name && item.age', datasets)

        analysis = jmespath.compile('item.name || fallback').analyze_fields()
        possible = [internal_path(path)
                    for path in analysis['possible_paths']]
        unconditional = [internal_path(path)
                         for path in analysis['unconditional_paths']]
        self.assertIn(('fallback',), possible)
        self.assertNotIn(('fallback',), unconditional)
        self.assertIn(('item', 'name'), unconditional)

    def test_builtin_functions_and_projections(self):
        datasets = [
            {'items': [
                {'name': 'one', 'age': 2},
                {'name': 'two', 'age': 1}]},
            {'items': []},
        ]
        self.assert_runtime_reads_covered(
            'sort_by(items, &age)[*].name', datasets)
        object_datasets = [
            {'maps': {'one': {'name': 'a'}, 'two': {'name': 'b'}}},
            {'maps': {}},
        ]
        self.assert_runtime_reads_covered('values(maps)', object_datasets)
        self.assert_runtime_reads_covered('keys(maps)', object_datasets)
        self.assert_runtime_reads_covered('length(maps)', object_datasets)

    def test_unknown_function_with_current_is_wildcard(self):
        function_options = jmespath.Options(
            custom_functions=ExplodingFunctions())
        parsed = jmespath.compile('inspect(@)')
        analysis = parsed.analyze_fields()
        self.assertEqual(analysis['unconditional_paths'], [])
        self.assertEqual(analysis['possible_paths'], [
            [{'type': ANY_DESCENDANT_FIELDS}]])

        # Analyzing takes no options and does not resolve any function
        # arguments, while searching with this function would deliberately fail.
        self.assertRaises(
            AssertionError,
            lambda: parsed.search({}, options=function_options))

    def test_unknown_function_argument_is_conservative(self):
        analysis = jmespath.compile(
            'item.details | inspect(@)').analyze_fields()
        possible = [internal_path(path)
                    for path in analysis['possible_paths']]
        self.assertIn(('item', 'details', '**'), possible)
        self.assertNotIn(('item', 'details', '**'), [
            internal_path(path)
            for path in analysis['unconditional_paths']])

    def test_unknown_expression_reference_is_conservative(self):
        analysis = jmespath.compile('map(&inspect(@), items)').analyze_fields()
        possible = [internal_path(path)
                    for path in analysis['possible_paths']]
        self.assertIn(('items',), possible)
        self.assertIn(('items', '**'), possible)
        self.assertNotIn(('items', '**'), [
            internal_path(path)
            for path in analysis['unconditional_paths']])


if __name__ == '__main__':
    unittest.main()
