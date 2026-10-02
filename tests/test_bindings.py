from tests import unittest

import jmespath
from jmespath import ast
from jmespath import exceptions
from jmespath import lexer
from jmespath import parser


class TestLexerBindParameter(unittest.TestCase):
    def setUp(self):
        self.lexer = lexer.Lexer()

    def tokens(self, expression):
        return [{'type': t['type'], 'value': t['value']}
                for t in self.lexer.tokenize(expression)
                if t['type'] != 'eof']

    def test_bind_parameter_token(self):
        self.assertEqual(
            self.tokens('$tenant'),
            [{'type': 'bindparameter', 'value': 'tenant'}])

    def test_bind_parameter_with_underscores_and_digits(self):
        self.assertEqual(
            self.tokens('$my_param_2'),
            [{'type': 'bindparameter', 'value': 'my_param_2'}])

    def test_dollar_alone_is_invalid(self):
        with self.assertRaises(exceptions.LexerError):
            self.tokens('$')

    def test_dollar_requires_identifier(self):
        for expression in ['$1x', '$.x', '$"x"']:
            with self.assertRaises(exceptions.LexerError):
                self.tokens(expression)


class TestParserBindParameter(unittest.TestCase):
    def setUp(self):
        self.parser = parser.Parser()

    def test_parses_bind_parameter_node(self):
        parsed = self.parser.parse('$threshold')
        self.assertEqual(parsed.parsed, ast.bind_parameter('threshold'))

    def test_bind_parameter_in_filter(self):
        parsed = self.parser.parse('[?tenant == $tenant]')
        condition = parsed.parsed['children'][2]
        self.assertEqual(condition['type'], 'comparator')
        self.assertEqual(condition['children'][1],
                         ast.bind_parameter('tenant'))

    def test_bind_parameter_as_function_name_is_invalid(self):
        with self.assertRaises(exceptions.ParseError):
            self.parser.parse('$foo(`1`)')

    def test_bind_parameter_in_multi_select_hash(self):
        parsed = self.parser.parse('{a: $x, b: b}')
        nodes = parsed.parsed['children']
        self.assertEqual(nodes[0]['children'][0], ast.bind_parameter('x'))

    def test_compilation_cache_stores_structure_only(self):
        first = self.parser.parse('[?a > $limit]')
        second = self.parser.parse('[?a > $limit]')
        self.assertIs(first, second)
        first.search([{'a': 1}], bindings={'limit': 0})
        # Executing with bindings must not mutate the cached structure.
        self.assertEqual(second.parsed, first.parsed)
        self.assertEqual(
            first.parsed['children'][2]['children'][1],
            ast.bind_parameter('limit'))


class TestSearchBindings(unittest.TestCase):
    DATA = [
        {'tenant': 'ac"me', 'usage': 10, 'name': 'a'},
        {'tenant': 'ac"me', 'usage': 50, 'name': 'b'},
        {'tenant': 'q`uote', 'usage': 30, 'name': 'c'},
        {'tenant': 'q`uote', 'usage': 99, 'name': 'd'},
    ]
    EXPRESSION = '[?tenant == $tenant && usage > $limit].name'

    def test_filter_with_bound_strings_and_numbers(self):
        compiled = jmespath.compile(self.EXPRESSION)
        self.assertEqual(
            compiled.search(self.DATA,
                            bindings={'tenant': 'ac"me', 'limit': 20}),
            ['b'])
        self.assertEqual(
            compiled.search(self.DATA,
                            bindings={'tenant': 'q`uote', 'limit': 40}),
            ['d'])

    def test_reused_compilation_interleaved_bindings(self):
        compiled = jmespath.compile(self.EXPRESSION)
        results = []
        for _ in range(3):
            results.append(compiled.search(
                self.DATA,
                bindings={'tenant': 'ac"me', 'limit': 20}))
            results.append(compiled.search(
                self.DATA,
                bindings={'tenant': 'q`uote', 'limit': 40}))
        self.assertEqual(
            results,
            [['b'], ['d'], ['b'], ['d'], ['b'], ['d']])

    def test_missing_binding_is_an_error(self):
        compiled = jmespath.compile('$missing')
        with self.assertRaises(exceptions.UndefinedBindingError) as cm:
            compiled.search({})
        self.assertEqual(cm.exception.binding_name, 'missing')

    def test_missing_binding_only_errors_when_referenced(self):
        compiled = jmespath.compile('a || $unused')
        self.assertEqual(compiled.search({'a': 'value'},
                                         bindings={'other': None}),
                         'value')

    def test_null_binding_is_distinct_from_missing(self):
        compiled = jmespath.compile('a == $x')
        with self.assertRaises(exceptions.UndefinedBindingError):
            compiled.search({'a': None})
        self.assertTrue(compiled.search({'a': None},
                                        bindings={'x': None}))
        self.assertFalse(compiled.search({'a': 1},
                                         bindings={'x': None}))

    def test_binding_names_do_not_shadow_field_names(self):
        # The parameter resolves from bindings for every element, while
        # the field with the same name is only read from the data.
        compiled = jmespath.compile('[?tenant == $tenant]')
        data = [{'tenant': 'wrong'}, {'tenant': 'right'}]
        self.assertEqual(compiled.search(data,
                                         bindings={'tenant': 'right'}),
                         [{'tenant': 'right'}])
        self.assertEqual(compiled.search(data,
                                         bindings={'tenant': 'wrong'}),
                         [{'tenant': 'wrong'}])
        # A field expression only reads data, never bindings.
        self.assertEqual(
            jmespath.search('tenant', {'tenant': 'from-data'},
                            bindings={'tenant': 'from-binding'}),
            'from-data')

    def test_binding_value_is_not_reparsed(self):
        # Strings that look like numbers/literals stay strings.
        compiled = jmespath.compile('$x == `1`')
        self.assertFalse(compiled.search({}, bindings={'x': '1'}))
        compiled = jmespath.compile('$x')
        self.assertEqual(compiled.search({}, bindings={'x': 'null'}),
                         'null')
        # A value containing expression syntax is plain data.
        self.assertEqual(
            compiled.search({}, bindings={'x': 'a.b || `evil`'}),
            'a.b || `evil`')

    def test_extra_bindings_are_ignored(self):
        compiled = jmespath.compile('$x')
        self.assertEqual(compiled.search({},
                                         bindings={'x': 1, 'y': 2}), 1)

    def test_bindings_are_execution_scoped(self):
        compiled = jmespath.compile('$x')
        self.assertEqual(compiled.search({}, bindings={'x': 1}), 1)
        with self.assertRaises(exceptions.UndefinedBindingError):
            compiled.search({})
        self.assertEqual(compiled.search({}, bindings={'x': 2}), 2)

    def test_bound_value_used_as_function_argument(self):
        compiled = jmespath.compile('starts_with($s, $prefix)')
        self.assertTrue(compiled.search(
            {}, bindings={'s': 'he"llo`', 'prefix': 'he"'}))
        self.assertFalse(compiled.search(
            {}, bindings={'s': 'hello', 'prefix': 'x'}))

    def test_expref_sees_callers_bindings(self):
        compiled = jmespath.compile('map(&a == $target, items)')
        result = compiled.search(
            {'items': [{'a': 1}, {'a': 2}, {'a': 3}]},
            bindings={'target': 2})
        self.assertEqual(result, [False, True, False])
        self.assertEqual(
            jmespath.search('map(&a > $limit, items)',
                            {'items': [{'a': 1}, {'a': 10}]},
                            bindings={'limit': 5}),
            [False, True])

    def test_null_binding_in_ordering_comparator_yields_none(self):
        self.assertEqual(
            jmespath.search('[?a > $x].a',
                            [{'a': 1}, {'a': 2}],
                            bindings={'x': None}),
            [])

    def test_search_helper_accepts_bindings(self):
        self.assertEqual(jmespath.search('$name', None,
                                         bindings={'name': 'a"b`c'}),
                         'a"b`c')

    def test_bind_parameter_works_without_bindings_argument(self):
        self.assertEqual(jmespath.search('foo', {'foo': 1}), 1)

    def test_subexpression_on_bound_value(self):
        compiled = jmespath.compile('$obj.inner')
        self.assertEqual(compiled.search({},
                                         bindings={'obj': {'inner': 7}}),
                         7)
        with self.assertRaises(exceptions.UndefinedBindingError):
            compiled.search({})


if __name__ == '__main__':
    unittest.main()
