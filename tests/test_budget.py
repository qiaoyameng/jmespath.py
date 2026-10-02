import threading

from tests import unittest

import jmespath
from jmespath import budget
from jmespath import exceptions
from jmespath import functions


class CustomFunctions(functions.Functions):
    @functions.signature({'types': ['array']})
    def _func_return_array(self, values):
        return list(values)

    @functions.signature({'types': ['expref']}, {'types': ['array']})
    def _func_swallow_errors(self, expression, value):
        try:
            result = []
            for item in value:
                result.append(expression.visit(expression.expression, item))
            return result
        except Exception:
            return 'swallowed'


class TestExecutionBudget(unittest.TestCase):
    def test_budget_limits_must_be_non_negative_integers(self):
        with self.assertRaises(TypeError):
            budget.ExecutionBudget(max_nodes='3')
        with self.assertRaises(ValueError):
            budget.ExecutionBudget(max_collection_elements=-1)

    def test_options_requires_execution_budget_instance(self):
        with self.assertRaises(TypeError):
            jmespath.Options(execution_budget={'max_nodes': 1})

    def test_budget_is_disabled_by_default(self):
        expression = jmespath.compile('[*].a[*]')
        data = [{'a': [1, 2]}, {'a': [3, 4]}]

        self.assertEqual(expression.search(data), [[1, 2], [3, 4]])

    def test_deep_projection_reports_node_budget_and_location(self):
        expression = jmespath.compile('[*].a[*]')
        data = [{'a': [1, 2]}, {'a': [3, 4]}]
        options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(max_nodes=7))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            expression.search(data, options)

        error = caught.exception
        self.assertEqual(error.category, 'node_evaluations')
        self.assertEqual(error.limit, 7)
        self.assertEqual(error.usage, 8)
        self.assertEqual(error.position, 5)
        self.assertEqual(error.node_type, 'field')
        self.assertIn('node_evaluations', str(error))
        self.assertIn('column 5', str(error))

    def test_flatten_reports_collection_budget_and_location(self):
        expression = jmespath.compile('items[]')
        data = {'items': [[1], [2], [3]]}
        options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(
                max_collection_elements=4))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            expression.search(data, options)

        error = caught.exception
        self.assertEqual(error.category, 'collection_elements')
        self.assertEqual(error.usage, 6)
        self.assertEqual(error.position, 5)
        self.assertEqual(error.node_type, 'flatten')

    def test_shallow_query_runs_after_budget_error(self):
        expression = jmespath.compile('[*].a[*]')
        data = [{'a': [1, 2]}, {'a': [3, 4]}]
        options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(max_nodes=3))

        with self.assertRaises(exceptions.BudgetExceededError):
            expression.search(data, options)

        shallow_options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(max_nodes=7))
        self.assertEqual(
            expression.search([{'a': [1]}], shallow_options), [[1]])

    def test_filter_conditions_share_query_budget(self):
        expression = jmespath.compile('[?enabled].name')
        data = [{'enabled': True, 'name': 'one'},
                {'enabled': False, 'name': 'two'},
                {'enabled': True, 'name': 'three'}]
        options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(max_nodes=3))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            expression.search(data, options)

        self.assertEqual(caught.exception.category, 'node_evaluations')
        self.assertEqual(caught.exception.position, 11)

    def test_expression_references_share_query_budget(self):
        expression = jmespath.compile('map(&name, @)')
        data = [{'name': 'one'}, {'name': 'two'}, {'name': 'three'}]
        options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(max_nodes=5))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            expression.search(data, options)

        self.assertEqual(caught.exception.category, 'node_evaluations')
        self.assertEqual(caught.exception.position, 5)

    def test_budget_error_passes_through_filter_truth_check(self):
        expression = jmespath.compile('[?items[*].id]')
        data = [{'items': [{'id': 1}, {'id': 2}]}]
        options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(max_nodes=4))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            expression.search(data, options)

        self.assertEqual(caught.exception.category, 'node_evaluations')
        self.assertEqual(caught.exception.node_type, 'field')

    def test_builtin_function_collection_results_share_budget(self):
        expression = jmespath.compile('values(@)')
        data = {'one': 1, 'two': 2, 'three': 3}
        options = jmespath.Options(
            execution_budget=budget.ExecutionBudget(
                max_collection_elements=2))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            expression.search(data, options)

        self.assertEqual(caught.exception.category, 'collection_elements')
        self.assertEqual(caught.exception.node_type, 'function_expression')
        self.assertEqual(caught.exception.position, 6)

    def test_custom_function_boundary_counts_arguments_and_result(self):
        expression = jmespath.compile('return_array(@)')
        data = [1, 2, 3]
        options = jmespath.Options(
            custom_functions=CustomFunctions(),
            execution_budget=budget.ExecutionBudget(
                max_collection_elements=5))

        with self.assertRaises(exceptions.BudgetExceededError) as caught:
            expression.search(data, options)

        self.assertEqual(caught.exception.category, 'collection_elements')
        self.assertEqual(caught.exception.usage, 6)

    def test_budget_error_is_not_swallowed_by_custom_function(self):
        expression = jmespath.compile('swallow_errors(&name, @)')
        data = [{'name': 'one'}, {'name': 'two'}, {'name': 'three'}]
        options = jmespath.Options(
            custom_functions=CustomFunctions(),
            execution_budget=budget.ExecutionBudget(max_nodes=5))

        with self.assertRaises(exceptions.BudgetExceededError):
            expression.search(data, options)

    def test_compiled_expression_can_be_called_concurrently(self):
        expression = jmespath.compile('[*].a[*]')
        errors = []

        def worker():
            small_options = jmespath.Options(
                execution_budget=budget.ExecutionBudget(max_nodes=10))
            large_options = jmespath.Options(
                execution_budget=budget.ExecutionBudget(max_nodes=1000))
            for _ in range(20):
                try:
                    expression.search(
                        [{'a': [1, 2]}, {'a': [3, 4]}], small_options)
                except exceptions.BudgetExceededError:
                    pass
                try:
                    result = expression.search(
                        [{'a': [1]}], large_options)
                    if result != [[1]]:
                        errors.append(result)
                except exceptions.BudgetExceededError as error:
                    errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
