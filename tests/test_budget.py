import threading

from tests import unittest

import jmespath
from jmespath import functions
from jmespath import exceptions


class CustomFunctions(functions.Functions):
    @functions.signature({'types': []})
    def _func_make_list(self, value):
        return list(range(30))

    @functions.signature({'types': []})
    def _func_identity_value(self, value):
        return value


class TestExecutionBudget(unittest.TestCase):
    def deep_projection_data(self):
        return {
            'items': [
                {
                    'children': [
                        {'tags': ['one', 'two']},
                        {'tags': ['three']},
                    ],
                },
                {
                    'children': [
                        {'tags': ['four', 'five']},
                    ],
                },
            ]
        }

    def options(self, **limits):
        return jmespath.Options(
            execution_budget=jmespath.ExecutionBudget(**limits))

    def test_deep_projection_reports_node_budget_and_position(self):
        expression = 'items[*].children[*].tags[*]'
        parsed = jmespath.compile(expression)

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            parsed.search(
                self.deep_projection_data(),
                self.options(node_evaluations=4))

        error = caught.exception
        self.assertEqual(error.category, 'node_evaluations')
        self.assertEqual(error.limit, 4)
        self.assertEqual(error.used, 5)
        self.assertEqual(error.usage['node_evaluations'], 5)
        self.assertEqual(error.usage['intermediate_elements'], 4)
        self.assertEqual(error.node_type, 'projection')
        self.assertEqual(error.position, 25)
        self.assertEqual(error.end_position, 28)
        self.assertIn('children[*].tags[*]', str(error))

    def test_flatten_reports_large_intermediate_result(self):
        expression = 'items[].tag'
        data = {
            'items': [
                [{'tag': index * 2}, {'tag': index * 2 + 1}]
                for index in range(80)
            ]
        }

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            jmespath.search(
                expression, data,
                self.options(intermediate_elements=100))

        error = caught.exception
        self.assertEqual(error.category, 'intermediate_elements')
        self.assertEqual(error.limit, 100)
        self.assertEqual(error.used, 240)
        self.assertEqual(error.node_type, 'flatten')
        self.assertEqual(error.position, 5)
        self.assertEqual(error.end_position, 7)
        self.assertEqual(error.usage['node_evaluations'], 3)

    def test_failed_budget_does_not_affect_follow_up_shallow_search(self):
        parsed = jmespath.compile('items[*].children[*].tags[*]')
        options = self.options(
            node_evaluations=4,
            intermediate_elements=1000)

        with self.assertRaises(exceptions.BudgetExceededError):
            parsed.search(self.deep_projection_data(), options)

        shallow = jmespath.compile('name')
        result = shallow.search(
            {'name': 'ok'}, options)

        self.assertEqual(result, 'ok')

    def test_filter_condition_shares_budget_with_projection(self):
        data = [{'ok': True, 'name': 'a'}] * 20

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            jmespath.search(
                '[?ok].name', data,
                self.options(node_evaluations=8))

        self.assertEqual(caught.exception.category, 'node_evaluations')
        self.assertIn(caught.exception.node_type,
                      ('field', 'current', 'projection', 'identity'))

    def test_expression_reference_uses_calling_interpreter_budget(self):
        data = [{'name': 'a'}] * 10

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            jmespath.search(
                'map(&name, @)', data,
                self.options(node_evaluations=12))

        error = caught.exception
        self.assertEqual(error.category, 'node_evaluations')
        self.assertEqual(error.node_type, 'field')
        self.assertEqual(error.position, 5)
        self.assertGreaterEqual(error.usage['node_evaluations'], 13)

    def test_builtin_function_return_collection_is_counted(self):
        data = list(range(20))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            jmespath.search(
                'reverse(@)', data,
                self.options(intermediate_elements=10))

        error = caught.exception
        self.assertEqual(error.category, 'intermediate_elements')
        self.assertEqual(error.used, 20)
        self.assertEqual(error.node_type, 'current')
        self.assertEqual(error.position, 8)

    def test_builtin_function_shares_the_current_budget(self):
        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            jmespath.search(
                'length(keys(@))', {'a': 1},
                self.options(node_evaluations=1))

        self.assertEqual(caught.exception.category, 'node_evaluations')
        self.assertEqual(caught.exception.node_type, 'function_expression')
        self.assertEqual(caught.exception.used, 2)

    def test_custom_function_return_collection_is_boundary(self):
        options = jmespath.Options(
            custom_functions=CustomFunctions(),
            execution_budget=jmespath.ExecutionBudget(
                intermediate_elements=10))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            jmespath.search('make_list(@)', None, options)

        error = caught.exception
        self.assertEqual(error.category, 'intermediate_elements')
        self.assertEqual(error.used, 30)
        self.assertEqual(error.node_type, 'function_expression')

    def test_budget_error_is_not_swallowed_by_type_check(self):
        with self.assertRaises(exceptions.BudgetExceededError):
            jmespath.search(
                'avg(@)', list(range(20)),
                self.options(intermediate_elements=10))

    def test_zero_node_budget_reports_expression_position(self):
        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            jmespath.search(
                'foo.bar', {'foo': {'bar': 'ok'}},
                self.options(node_evaluations=0))

        error = caught.exception
        self.assertEqual(error.node_type, 'subexpression')
        self.assertEqual(error.position, 0)
        self.assertIn('"foo.bar"', str(error))

    def test_compiled_expression_calls_have_independent_budgets(self):
        parsed = jmespath.compile('[*]')
        data = list(range(100))
        errors = []
        results = []
        barrier = threading.Barrier(2)

        def worker():
            options = self.options(
                node_evaluations=300,
                intermediate_elements=1000)
            try:
                barrier.wait()
                for _ in range(20):
                    results.append(parsed.search(data, options))
            except exceptions.BudgetExceededError as error:
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 40)

    def test_without_budget_preserves_existing_behavior(self):
        result = jmespath.search(
            'items[?enabled].name | [0]',
            {'items': [{'enabled': True, 'name': 'first'},
                       {'enabled': False, 'name': 'second'}]})

        self.assertEqual(result, 'first')


if __name__ == '__main__':
    unittest.main()
