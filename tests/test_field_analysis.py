import unittest

import jmespath
from jmespath import functions


ANY_FIELD = {'type': 'any_field'}
ANY_INDEX = {'type': 'any_index'}


class CountingFunctions(functions.Functions):
    def __init__(self):
        self.calls = []

    @functions.signature({'types': []})
    def _func_spy(self, value):
        self.calls.append(value)
        return value

    @functions.signature({'types': ['expref']})
    def _func_spy_ref(self, expression):
        self.calls.append(expression)
        return expression


class TrackingDict(dict):
    def __init__(self, value=None, path=(), accessed=None):
        super(TrackingDict, self).__init__()
        object.__setattr__(self, '_tracked_path', path)
        object.__setattr__(self, '_accessed', accessed)
        if value is not None:
            for key, child in value.items():
                self[key] = self._wrap(child, path + (key,), accessed)

    def __setattr__(self, name, value):
        pass

    def get(self, key, default=None):
        self._accessed.add(self._tracked_path + (key,))
        value = super(TrackingDict, self).get(key, default)
        if isinstance(value, TrackingDict):
            object.__setattr__(value, '_tracked_path',
                               self._tracked_path + (key,))
            object.__setattr__(value, '_accessed', self._accessed)
        if isinstance(value, TrackingList):
            object.__setattr__(value, '_tracked_path',
                               self._tracked_path + (key,))
            object.__setattr__(value, '_accessed', self._accessed)
        return value

    @classmethod
    def _wrap(cls, value, path=(), accessed=None):
        if isinstance(value, dict) and not isinstance(value, TrackingDict):
            value = cls(value, path, accessed)
        elif isinstance(value, list):
            value = TrackingList(
                [cls._wrap(item, path, accessed) for item in value],
                path, accessed)
        if isinstance(value, TrackingDict):
            object.__setattr__(value, '_accessed', accessed)
        return value

    @classmethod
    def track(cls, value):
        accessed = set()
        tracked = cls._wrap(value, (), accessed)
        cls._attach(tracked, (), accessed)
        return tracked, accessed

    @classmethod
    def _attach(cls, value, path, accessed):
        if isinstance(value, TrackingDict):
            object.__setattr__(value, '_tracked_path', path)
            object.__setattr__(value, '_accessed', accessed)
            for key, child in value.items():
                cls._attach(child, path + (key,), accessed)
        elif isinstance(value, list):
            for child in super(TrackingList, value).__iter__():
                cls._attach(child, path, accessed)


TrackingDict.__name__ = 'dict'


class TrackingList(list):
    def __init__(self, value, path=(), accessed=None):
        super(TrackingList, self).__init__(value)
        self._tracked_path = path
        self._accessed = accessed

    def __getitem__(self, index):
        value = super(TrackingList, self).__getitem__(index)
        if isinstance(index, int):
            self._accessed.add(self._tracked_path + (index,))
        else:
            self._accessed.add(self._tracked_path + ('*',))
        if isinstance(value, (TrackingDict, TrackingList)):
            value._tracked_path = self._tracked_path
            value._accessed = self._accessed
        return value

    def __iter__(self):
        self._accessed.add(self._tracked_path + ('*',))
        for value in super(TrackingList, self).__iter__():
            if isinstance(value, (TrackingDict, TrackingList)):
                value._tracked_path = self._tracked_path
                value._accessed = self._accessed
            yield value


TrackingList.__name__ = 'list'


class TestFieldAnalysis(unittest.TestCase):
    def assert_paths(self, expression, possible, unconditional):
        analysis = jmespath.compile(expression).analyze_fields()
        result = analysis.to_dict()
        self.assertEqual(
            sorted(result['possible'], key=repr),
            sorted(possible, key=repr))
        self.assertEqual(
            sorted(result['unconditional'], key=repr),
            sorted(unconditional, key=repr))
        return analysis

    def test_stable_result_structure(self):
        analysis = jmespath.compile('foo.bar').analyze_fields()
        self.assertEqual(analysis.to_dict(), {
            'possible': [['foo'], ['foo', 'bar'],
                         ['foo', 'bar', ANY_FIELD]],
            'unconditional': [['foo'], ['foo', 'bar'],
                              ['foo', 'bar', ANY_FIELD]],
        })

    def test_quoted_field_names_are_not_split(self):
        self.assert_paths(
            '"a.b"."c-d"',
            [['a.b'], ['a.b', 'c-d'], ['a.b', 'c-d', ANY_FIELD]],
            [['a.b'], ['a.b', 'c-d'], ['a.b', 'c-d', ANY_FIELD]])

    def test_projection_and_filter_are_conditional(self):
        self.assert_paths(
            'items[*].name',
            [['items'], ['items', 'name'], ['items', ANY_INDEX]],
            [['items']])
        self.assert_paths(
            'items[?score > `1`].name',
            [['items'], ['items', 'name'], ['items', 'score'],
             ['items', ANY_INDEX]],
            [['items']])

    def test_slice_and_index_are_conditional(self):
        self.assert_paths(
            'items[0:2].name',
            [['items'], ['items', 'name'], ['items', ANY_INDEX]],
            [['items']])
        self.assert_paths(
            'items[0].name',
            [['items'], ['items', 'name'],
             ['items', 'name', ANY_FIELD], ['items', ANY_INDEX]],
            [['items'], ['items', 'name'],
             ['items', 'name', ANY_FIELD]])

    def test_short_circuit_paths(self):
        self.assert_paths(
            'a || b',
            [['a'], ['a', ANY_FIELD], ['b'], ['b', ANY_FIELD]],
            [['a'], ['a', ANY_FIELD]])
        self.assert_paths(
            'a && b',
            [['a'], ['a', ANY_FIELD], ['b'], ['b', ANY_FIELD]],
            [['a'], ['a', ANY_FIELD]])
        self.assert_paths(
            'a.b || c.d',
            [['a'], ['a', 'b'], ['a', 'b', ANY_FIELD],
             ['c'], ['c', 'd'], ['c', 'd', ANY_FIELD]],
            [['a'], ['a', 'b'], ['a', 'b', ANY_FIELD]])

    def test_pipe_keeps_left_hand_context(self):
        self.assert_paths(
            'a.b | c',
            [['a'], ['a', 'b'], ['a', 'b', 'c'],
             ['a', 'b', 'c', ANY_FIELD]],
            [['a'], ['a', 'b'], ['a', 'b', 'c'],
             ['a', 'b', 'c', ANY_FIELD]])

    def test_object_projection_uses_wildcard_path(self):
        self.assert_paths(
            'a.*.name',
            [['a'], ['a', ANY_FIELD], ['a', ANY_FIELD, 'name']],
            [['a'], ['a', ANY_FIELD]])
        self.assert_paths(
            '*',
            [[ANY_FIELD]],
            [[ANY_FIELD]])
        self.assert_paths(
            '[*].name',
            [[ANY_INDEX], ['name']],
            [])

    def test_current_passthrough_covers_all_child_fields(self):
        self.assert_paths(
            '@',
            [[ANY_FIELD], [ANY_INDEX]],
            [[ANY_FIELD], [ANY_INDEX]])

    def test_unknown_function_with_current_covers_everything(self):
        analysis = self.assert_paths(
            'spy(@)',
            [[ANY_FIELD], [ANY_INDEX]],
            [[ANY_FIELD], [ANY_INDEX]])
        self.assertTrue(analysis.covers(['spy']))
        self.assertFalse(any(path == ('spy',) for path in analysis.possible))

    def test_unknown_function_expression_reference_covers_current(self):
        self.assert_paths(
            'spy_ref(&name)',
            [['name']],
            [])
        self.assert_paths(
            'spy_ref(&@)',
            [[ANY_FIELD], [ANY_INDEX]],
            [])

    def test_unknown_function_does_not_use_function_name_as_field(self):
        analysis = jmespath.compile('spy(@.name)').analyze_fields()
        self.assertFalse(any(path == ('spy',) for path in analysis.possible))
        self.assertTrue(analysis.covers(['name']))
        self.assertTrue(analysis.covers(['name', 'anything']))

    def test_unknown_function_value_is_conservatively_expanded(self):
        analysis = jmespath.compile('spy(foo)').analyze_fields()
        self.assertTrue(analysis.covers(['foo', 'name']))
        self.assertTrue(analysis.covers(['foo', 0, 'name']))
        self.assertFalse(any(
            path == ('spy',) for path in analysis.possible))

    def test_analysis_does_not_call_custom_functions(self):
        custom_functions = CountingFunctions()
        options = jmespath.Options(custom_functions=custom_functions)
        parsed = jmespath.compile('spy(@)')

        analysis = parsed.analyze_fields()

        self.assertEqual(custom_functions.calls, [])
        self.assertTrue(analysis.covers(['anything']))
        parsed.search({'anything': 'value'}, options)
        self.assertEqual(len(custom_functions.calls), 1)

    def test_runtime_field_reads_are_always_covered(self):
        data = {
            'a.b': {'c-d': 'quoted'},
            'a': {
                'b': 1,
                'c': {'d': 2},
                'items': [
                    {'name': 'one', 'score': 1},
                    {'name': 'two', 'score': 2},
                ],
            },
            'items': [
                {'name': 'one', 'score': 1},
                {'name': 'two', 'score': 2},
            ],
            'numbers': [3, 4],
            'one': {'id': 'one'},
            'two': {'id': 'two'},
            'missing': None,
        }
        expressions = [
            '"a.b"."c-d"',
            'a.b',
            'a.c | d',
            'a.items[*].score',
            'items[*].name',
            'items[?score > `1`].name',
            'items[0:1][*].name',
            'items[0].name',
            'missing || a.b',
            'a.items[*] | [0].name',
            'sort_by(items,&score)[0].name',
            'map(&name, items)',
            'merge(one,two).id',
            'values(a)',
            'items[].name',
            '{name: items[0].name, number: numbers[0]}',
        ]
        for expression in expressions:
            parsed = jmespath.compile(expression)
            analysis = parsed.analyze_fields()
            tracked, accessed = TrackingDict.track(data)
            parsed.search(tracked)
            for path in accessed:
                self.assertTrue(
                    analysis.covers(path),
                    '%s missed %r; result=%r' % (
                        expression, path, analysis.to_dict()))

    def test_runtime_array_reads_are_covered(self):
        expressions = ['[*].name', '[?score > `1`].name', '[0].name']
        data = [
            {'name': 'one', 'score': 1},
            {'name': 'two', 'score': 2},
        ]
        for expression in expressions:
            parsed = jmespath.compile(expression)
            analysis = parsed.analyze_fields()
            tracked, accessed = TrackingDict.track(data)
            parsed.search(tracked)
            for path in accessed:
                self.assertTrue(
                    analysis.covers(path),
                    '%s missed %r; result=%r' % (
                        expression, path, analysis.to_dict()))


if __name__ == '__main__':
    unittest.main()
