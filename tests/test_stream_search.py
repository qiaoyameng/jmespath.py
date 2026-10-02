from tests import unittest

import jmespath


class CountingSource(object):
    def __init__(self, values):
        self._values = iter(values)
        self.read_count = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        self.read_count += 1
        return next(self._values)

    def close(self):
        self.closed = True


class TestStreamSearch(unittest.TestCase):
    def test_projection_is_lazy_and_closes_source_early(self):
        source = CountingSource([
            {'a': 1}, {'a': 2}, {'a': 3},
        ])
        results = jmespath.stream_search('[*].a', source)

        self.assertEqual(source.read_count, 0)
        self.assertEqual(next(results), 1)
        self.assertEqual(next(results), 2)
        results.close()

        self.assertEqual(source.read_count, 2)
        self.assertTrue(source.closed)

    def test_filter_is_single_pass(self):
        source = CountingSource([
            {'keep': False, 'a': 0},
            {'keep': True, 'a': 1},
            {'keep': True, 'a': 2},
            {'keep': True, 'a': 3},
        ])
        results = jmespath.stream_search('[?keep].a', source)

        self.assertEqual(next(results), 1)
        self.assertEqual(next(results), 2)
        results.close()

        self.assertEqual(source.read_count, 3)
        self.assertTrue(source.closed)

    def test_positive_finite_slice_is_single_pass(self):
        source = CountingSource([
            {'a': 0}, {'a': 1}, {'a': 2}, {'a': 3}, {'a': 4},
        ])
        results = jmespath.stream_search('[2:4].a', source)

        self.assertEqual(list(results), [2, 3])
        self.assertEqual(source.read_count, 4)
        self.assertTrue(source.closed)

    def test_empty_slice_does_not_consume_source(self):
        source = CountingSource([{'a': 0}, {'a': 1}])

        self.assertEqual(
            list(jmespath.stream_search('[5:3].a', source)),
            [],
        )
        self.assertEqual(source.read_count, 0)
        self.assertTrue(source.closed)

    def test_unsupported_expression_is_rejected_before_consuming_input(self):
        expressions = [
            'sort(@)',
            'length(@)',
            '[-1]',
            '[::-1]',
            '[:]',
            '*.a',
            '[*].a | [0]',
        ]
        for expression in expressions:
            source = CountingSource([{'a': 1}])
            with self.subTest(expression=expression):
                with self.assertRaises(
                        jmespath.exceptions.StreamUnsupportedError):
                    jmespath.stream_search(expression, source)
                self.assertEqual(source.read_count, 0)
                self.assertFalse(source.closed)

    def test_unsupported_nested_sort_is_rejected_before_consuming_input(self):
        source = CountingSource([{'values': [3, 1, 2]}])

        with self.assertRaises(jmespath.exceptions.StreamUnsupportedError):
            jmespath.stream_search('[*].sort(values)', source)

        self.assertEqual(source.read_count, 0)

    def test_null_projection_values_are_omitted_but_false_values_remain(self):
        source = [
            {'a': 1}, {'b': 2}, {'a': None}, {'a': 0}, {'a': False},
        ]

        self.assertEqual(
            list(jmespath.stream_search('[*].a', source)),
            [1, 0, False],
        )

    def test_filter_uses_jmespath_truthiness(self):
        source = [
            {'a': False}, {'a': 0}, {'a': ''}, {'a': []}, {'a': {}},
            {'a': None}, {'a': True}, {'a': 'yes'},
        ]

        self.assertEqual(
            list(jmespath.stream_search('[?a].a', source)),
            [0, True, 'yes'],
        )

    def test_nested_projections_are_not_flattened(self):
        source = [
            {'groups': [{'name': 'a'}, {'name': 'b'}]},
            {'groups': [{'name': 'c'}]},
        ]

        self.assertEqual(
            list(jmespath.stream_search('[*].groups[*].name', source)),
            [['a', 'b'], ['c']],
        )

    def test_nested_object_value_projection_is_supported_and_nested(self):
        source = [
            {'groups': {'x': {'name': 'a'}, 'y': {'name': 'b'}}},
            {'groups': {'z': {'name': 'c'}}},
        ]

        self.assertEqual(
            list(
                jmespath.stream_search('[*].groups.*.name', source)),
            [['a', 'b'], ['c']],
        )

    def test_root_flatten_only_flattens_top_level_lists(self):
        source = [
            [{'b': 1}, {'b': None}, {'c': 2}],
            [{'b': 3}],
            {'b': 4},
            None,
        ]

        self.assertEqual(
            list(jmespath.stream_search('[].b', source)),
            [1, 3, 4],
        )

    def test_root_flatten_passes_top_level_objects_through(self):
        source = [{'a': 1}, {'a': None}, None, {'a': 2}]

        self.assertEqual(list(jmespath.stream_search('[].a', source)), [1, 2])

    def test_nested_slice_projection_on_non_lists_returns_nothing(self):
        source = [{'a': 1}, {'a': 2}]

        self.assertEqual(list(jmespath.stream_search('[*][:2]', source)), [])

    def test_query_failure_closes_owned_source(self):
        source = CountingSource([{'a': 1}, {'a': 2}])
        results = jmespath.stream_search(
            '[*].unknown_function(@)', source)

        with self.assertRaises(jmespath.exceptions.UnknownFunctionError):
            next(results)

        self.assertEqual(source.read_count, 1)
        self.assertTrue(source.closed)

    def test_compiled_expression_provides_stream_search(self):
        source = CountingSource([{'a': 1}, {'a': 2}, {'a': 3}])
        expression = jmespath.compile('[*].a')
        results = expression.stream_search(source)

        self.assertEqual(next(results), 1)
        results.close()

        self.assertEqual(source.read_count, 1)
        self.assertTrue(source.closed)
