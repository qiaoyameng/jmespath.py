import sys
import decimal
from tests import unittest, OrderedDict

import jmespath
import jmespath.functions
from jmespath import exceptions


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


class TestSearchBindings(unittest.TestCase):
    EXPRESSION = 'items[?tenant == $tenant && amount >= $threshold]'
    DATA = {
        'items': [
            {'tenant': 'alpha', 'amount': 10},
            {'tenant': 'alpha"\'`', 'amount': 20},
            {'tenant': 'beta', 'amount': 30},
        ]
    }

    def test_reuses_compilation_with_interleaved_bindings(self):
        expression = jmespath.compile(self.EXPRESSION)
        alpha_bindings = {'tenant': 'alpha"\'`', 'threshold': 15}
        beta_bindings = {'tenant': 'beta', 'threshold': 25}

        self.assertEqual(
            expression.search(self.DATA, bindings=alpha_bindings),
            [{'tenant': 'alpha"\'`', 'amount': 20}])
        self.assertEqual(
            expression.search(self.DATA, bindings=beta_bindings),
            [{'tenant': 'beta', 'amount': 30}])
        self.assertEqual(
            expression.search(self.DATA,
                               bindings={'tenant': 'alpha"\'`',
                                         'threshold': 5}),
            [{'tenant': 'alpha"\'`', 'amount': 20}])

    def test_search_accepts_bindings(self):
        self.assertEqual(
            jmespath.search(self.EXPRESSION, self.DATA,
                            bindings={'tenant': 'beta', 'threshold': 30}),
            [{'tenant': 'beta', 'amount': 30}])

    def test_missing_binding_is_distinct_from_null(self):
        expression = jmespath.compile('foo == $value')

        self.assertTrue(expression.search({'foo': None},
                                          bindings={'value': None}))
        with self.assertRaises(exceptions.MissingBindingError):
            expression.search({'foo': None})
        with self.assertRaises(KeyError):
            expression.search({'foo': None})

    def test_parameter_does_not_shadow_field(self):
        expression = jmespath.compile('{field: value, parameter: $value}')

        self.assertIsNone(jmespath.search('value', {},
                                          bindings={'value': 'from-binding'}))
        self.assertEqual(
            expression.search({'value': 'from-data'},
                              bindings={'value': 'from-binding'}),
            {'field': 'from-data', 'parameter': 'from-binding'})

    def test_binding_available_in_expression_reference(self):
        expression = jmespath.compile(
            'map(&[amount, $bonus], records)')

        self.assertEqual(
            expression.search({'records': [{'amount': 1}, {'amount': 2}]},
                              bindings={'bonus': 10}),
            [[1, 10], [2, 10]])

    def test_binding_values_are_not_evaluated_as_expressions(self):
        expression = jmespath.compile('value == $value')

        self.assertTrue(
            expression.search({'value': 'foo.bar | `injected`'},
                              bindings={'value': 'foo.bar | `injected`'}))


class TestBindingParser(unittest.TestCase):
    def test_parameter_ast_is_cached_without_binding_values(self):
        parsed_1 = jmespath.compile('foo == $bar')
        parsed_2 = jmespath.compile('foo == $bar')

        self.assertIs(parsed_1.parsed, parsed_2.parsed)
        self.assertEqual(
            parsed_1.parsed['children'][1],
            {'type': 'parameter', 'children': [], 'value': 'bar'})

    def test_parameter_cannot_be_function_name(self):
        with self.assertRaises(exceptions.ParseError):
            jmespath.compile('$foo(@)')
