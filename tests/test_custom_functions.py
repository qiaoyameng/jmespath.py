import unittest

import jmespath
from jmespath import exceptions
from jmespath import functions
from jmespath import visitor


class CustomFunctions(functions.Functions):
    @functions.signature({'types': ['string', 'array', 'object', 'null']})
    def _func_length0(self, s):
        return 0 if s is None else len(s)


class TestCustomFunctions(unittest.TestCase):
    def setUp(self):
        self.options = jmespath.Options(custom_functions=CustomFunctions())

    def test_null_to_nonetype(self):
        data = {
            'a': {
                'b': [1, 2, 3]
            }
        }

        self.assertEqual(jmespath.search('length0(a.b)', data, self.options), 3)
        self.assertEqual(jmespath.search('length0(a.c)', data, self.options), 0)


class LazyFunctions(functions.Functions):
    def __init__(self):
        self.call_count = 0
        self.captured_argument = None
        self.evaluation_errors = []

    @functions.signature({'types': ['boolean']},
                         {'types': [], 'lazy': True},
                         {'types': [], 'lazy': True})
    def _func_choose(self, condition, when_true, when_false):
        selected = when_true if condition else when_false
        selected.evaluate()
        return selected.evaluate()

    @functions.signature({'types': []})
    def _func_count_calls(self, value):
        self.call_count += 1
        return value

    @functions.signature({'types': ['number']})
    def _func_boom(self, value):
        raise AssertionError('unselected branch was evaluated')

    @functions.signature({'types': []})
    def _func_always_error(self, value):
        raise ValueError('boom')

    @functions.signature({'types': [], 'lazy': True})
    def _func_capture(self, argument):
        self.captured_argument = argument
        return None

    @functions.signature({'types': [], 'lazy': True})
    def _func_evaluate_twice(self, argument):
        first_error = None
        second_error = None
        try:
            argument.evaluate()
        except Exception as exc:
            first_error = exc
        try:
            argument.evaluate()
        except Exception as exc:
            second_error = exc
        self.evaluation_errors = [first_error, second_error]
        return None

    @functions.signature({'types': ['number']}, {'types': [], 'lazy': True})
    def _func_normal_before_lazy(self, value, argument):
        argument.evaluate()
        return value

    @functions.signature({'types': [], 'lazy': True})
    def _func_is_lazy_argument(self, argument):
        return isinstance(argument, functions.LazyArgument)


class TestLazyArguments(unittest.TestCase):
    def setUp(self):
        self.functions = LazyFunctions()
        self.options = jmespath.Options(custom_functions=self.functions)

    def test_only_selected_branch_is_evaluated_once(self):
        result = jmespath.search(
            'choose(`true`, count_calls(@), boom(@))',
            {'selected': True}, self.options)

        self.assertEqual(result, {'selected': True})
        self.assertEqual(self.functions.call_count, 1)

    def test_unselected_branch_type_is_validated_lazily(self):
        result = jmespath.search(
            'choose(`false`, boom(`"not a number"`), count_calls(@))',
            {'selected': False}, self.options)

        self.assertEqual(result, {'selected': False})

    def test_selected_lazy_argument_type_error_is_raised_on_evaluation(self):
        with self.assertRaises(exceptions.JMESPathTypeError):
            jmespath.search(
                'choose(`true`, boom(`"not a number"`), count_calls(@))',
                {}, self.options)

    def test_exception_is_evaluated_once_and_reused(self):
        jmespath.search(
            'evaluate_twice(always_error(@))', {}, self.options)

        self.assertEqual(len(self.functions.evaluation_errors), 2)
        self.assertIs(self.functions.evaluation_errors[0],
                      self.functions.evaluation_errors[1])

    def test_lazy_argument_expires_after_function_returns(self):
        jmespath.search('capture(@)', {'data': 1}, self.options)

        with self.assertRaises(RuntimeError):
            self.functions.captured_argument.evaluate()

    def test_normal_arguments_are_still_evaluated_eagerly(self):
        with self.assertRaises(ValueError):
            jmespath.search(
                'normal_before_lazy(always_error(@), count_calls(@))',
                {}, self.options)
        self.assertEqual(self.functions.call_count, 0)

    def test_lazy_argument_is_distinct_from_expression_reference(self):
        self.assertTrue(jmespath.search(
            'is_lazy_argument(&foo)', {}, self.options))
        jmespath.search('capture(@)', {}, self.options)
        self.assertIsInstance(self.functions.captured_argument,
                              functions.LazyArgument)

    def test_expression_reference_still_passes_type_check(self):
        captured = []

        class ExpressionFunctions(functions.Functions):
            @functions.signature({'types': ['expref']})
            def _func_capture_expref(self, expression):
                captured.append(expression)
                return not isinstance(expression, functions.LazyArgument)

        options = jmespath.Options(custom_functions=ExpressionFunctions())
        self.assertTrue(jmespath.search(
            'capture_expref(&foo)', {}, options))
        self.assertIsInstance(captured[0], visitor._Expression)
