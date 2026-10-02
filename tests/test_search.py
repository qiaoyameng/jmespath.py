import sys
import decimal
from tests import unittest, OrderedDict

import jmespath
import jmespath.functions


class TestSearchOptions(unittest.TestCase):
    def test_can_provide_dict_cls(self):
        result = jmespath.search(
            '{a: a, b: b, c: c}.*',
            {'c': 'c', 'b': 'b', 'a': 'a', 'd': 'd'},
            options=jmespath.Options(dict_cls=OrderedDict))
        self.assertEqual(result, ['a', 'b', 'c'])

    def test_can_provide_custom_functions(self):
        class CustomFunctions(jmespath.functions.Functions):
            @jmespath.functions.signature(
                {'types': ['number']},
                {'types': ['number']})
            def _func_custom_add(self, x, y):
                return x + y

            @jmespath.functions.signature(
                {'types': ['number']},
                {'types': ['number']})
            def _func_my_subtract(self, x, y):
                return x - y


        options = jmespath.Options(custom_functions=CustomFunctions())
        self.assertEqual(
            jmespath.search('custom_add(`1`, `2`)', {}, options=options),
            3
        )
        self.assertEqual(
            jmespath.search('my_subtract(`10`, `3`)', {}, options=options),
            7
        )
        # Should still be able to use the original functions without
        # any interference from the CustomFunctions class.
        self.assertEqual(
            jmespath.search('length(`[1, 2]`)', {}), 2
        )



class TestPythonSpecificCases(unittest.TestCase):
    def test_can_compare_strings(self):
        # This is python specific behavior that's not in the official spec
        # yet, but this was regression from 0.9.0 so it's been added back.
        self.assertTrue(jmespath.search('a < b', {'a': '2016', 'b': '2017'}))

    @unittest.skipIf(not hasattr(sys, 'maxint'), 'Test requires long() type')
    def test_can_handle_long_ints(self):
        result = sys.maxint + 1
        self.assertEqual(jmespath.search('[?a >= `1`].a', [{'a': result}]),
                         [result])

    def test_can_handle_decimals_as_numeric_type(self):
        result = decimal.Decimal('3')
        self.assertEqual(jmespath.search('[?a >= `1`].a', [{'a': result}]),
                         [result])


class TestSearchTrace(unittest.TestCase):
    EXPRESSION = (
        'items[?probe_left(active) || probe_right(included)].'
        'owner.name'
    )

    def setUp(self):
        self.data = {
            'items': [
                {'active': True, 'owner': {'name': 'first'}},
                {'active': False, 'included': False,
                 'owner': {'name': 'filtered'}},
                {'active': False, 'included': True,
                 'owner': {'name': 'second'}},
                {'active': True, 'owner': {'name': None}},
                {'included': True, 'owner': {'name': 'third'}},
            ]
        }

    def _functions(self):
        class CountedFunctions(jmespath.functions.Functions):
            def __init__(self):
                self.left_calls = 0
                self.right_calls = 0

            @jmespath.functions.signature({'types': []})
            def _func_probe_left(self, value):
                self.left_calls += 1
                return value

            @jmespath.functions.signature({'types': []})
            def _func_probe_right(self, value):
                self.right_calls += 1
                return value

        return CountedFunctions()

    def test_trace_explains_missing_null_and_filter(self):
        functions = self._functions()
        options = jmespath.Options(custom_functions=functions)
        result, events = jmespath.search_with_trace(
            self.EXPRESSION, self.data, options=options)

        self.assertEqual(result, [
            'first', 'second', 'third',
        ])
        self.assertEqual(
            [event['type'] for event in events],
            ['filter_not_passed', 'explicit_null', 'missing_field'])
        self.assertEqual(
            [event['input_path'] for event in events],
            ['$.items[1]', '$.items[3].owner.name', '$.items[4].active'])
        self.assertEqual(events[1]['field'], 'name')
        self.assertEqual(events[2]['field'], 'active')
        self.assertTrue(all(
            0 <= event['expression_start'] <= event['expression_end']
            <= len(self.EXPRESSION)
            for event in events
            if event['type'] != 'trace_truncated'))
        self.assertEqual(functions.left_calls, 5)
        self.assertEqual(functions.right_calls, 3)
        for event in events:
            self.assertNotIn('value', event)
            self.assertNotIn('first', event.values())
            self.assertNotIn('filtered', event.values())

    def test_trace_does_not_add_function_calls_or_change_result(self):
        normal_functions = self._functions()
        normal_options = jmespath.Options(custom_functions=normal_functions)
        normal_result = jmespath.search(
            self.EXPRESSION, self.data, options=normal_options)

        traced_functions = self._functions()
        traced_options = jmespath.Options(custom_functions=traced_functions)
        traced_result, _ = jmespath.search_with_trace(
            self.EXPRESSION, self.data, options=traced_options)

        self.assertEqual(traced_result, normal_result)
        self.assertEqual(
            traced_functions.left_calls, normal_functions.left_calls)
        self.assertEqual(
            traced_functions.right_calls, normal_functions.right_calls)
        self.assertEqual(traced_functions.left_calls, 5)
        self.assertEqual(traced_functions.right_calls, 3)

    def test_trace_truncation_does_not_change_execution(self):
        functions = self._functions()
        options = jmespath.Options(custom_functions=functions)
        result, events = jmespath.search_with_trace(
            self.EXPRESSION, self.data, options=options, trace_limit=2)

        self.assertEqual(result, [
            'first', 'second', 'third',
        ])
        self.assertEqual(len(events), 3)
        self.assertEqual(events[-1]['type'], 'trace_truncated')
        self.assertEqual(functions.left_calls, 5)
        self.assertEqual(functions.right_calls, 3)
