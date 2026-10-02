import unittest

import jmespath
from jmespath import exceptions, functions
from jmespath.visitor import _Expression


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
        self.count_calls = []
        self.stashed = None

    @functions.signature({'types': []})
    def _func_boom(self, value):
        raise RuntimeError('boom() must never be evaluated')

    @functions.signature({'types': []})
    def _func_count(self, value):
        self.count_calls.append(value)
        return 'counted-%s' % len(self.count_calls)

    @functions.signature(
        {'types': []},
        {'types': [], 'lazy': True},
        {'types': [], 'lazy': True})
    def _func_choose(self, condition, if_true, if_false):
        if condition:
            return if_true.resolve()
        return if_false.resolve()

    @functions.signature({'types': [], 'lazy': True})
    def _func_resolve_twice(self, handle):
        return [handle.resolve(), handle.resolve()]

    @functions.signature({'types': [], 'lazy': True})
    def _func_error_twice(self, handle):
        errors = []
        for _ in range(2):
            try:
                handle.resolve()
            except Exception as e:
                errors.append(e)
        return len(errors) == 2 and errors[0] is errors[1]

    @functions.signature({'types': [], 'lazy': True})
    def _func_stash(self, handle):
        self.stashed = handle
        return None

    @functions.signature({'types': ['string'], 'lazy': True})
    def _func_lazy_string(self, handle):
        return handle.resolve()

    @functions.signature({'types': ['string'], 'lazy': True})
    def _func_never_resolve(self, handle):
        return 'not-resolved'

    @functions.signature({'types': [], 'lazy': True})
    def _func_lazy_kind(self, handle):
        if isinstance(handle, _Expression):
            return 'expref'
        elif isinstance(handle, functions.LazyArgument):
            return 'lazy'
        return 'other'

    @functions.signature({'types': ['expref']})
    def _func_expref_kind(self, expref):
        if isinstance(expref, functions.LazyArgument):
            return 'lazy'
        elif isinstance(expref, _Expression):
            return 'expref'
        return 'other'


class TestLazyArguments(unittest.TestCase):
    def setUp(self):
        self.custom_functions = LazyFunctions()
        self.options = jmespath.Options(
            custom_functions=self.custom_functions)

    def search(self, expression, data=None):
        if data is None:
            data = {}
        return jmespath.search(expression, data, self.options)

    def test_unselected_branch_is_not_evaluated(self):
        result = self.search("choose(`true`, count('a'), boom('b'))")
        self.assertEqual(result, 'counted-1')
        self.assertEqual(self.custom_functions.count_calls, ['a'])

    def test_unselected_branch_is_not_evaluated_false(self):
        result = self.search("choose(`false`, boom('a'), count('b'))")
        self.assertEqual(result, 'counted-1')
        self.assertEqual(self.custom_functions.count_calls, ['b'])

    def test_resolving_twice_evaluates_once(self):
        result = self.search("resolve_twice(count('x'))")
        self.assertEqual(result, ['counted-1', 'counted-1'])
        self.assertEqual(self.custom_functions.count_calls, ['x'])

    def test_exceptions_are_memoized(self):
        self.assertTrue(self.search('error_twice(boom(`null`))'))

    def test_handle_expires_after_function_returns(self):
        self.search("stash('x')")
        stashed = self.custom_functions.stashed
        self.assertIsNotNone(stashed)
        with self.assertRaises(exceptions.LazyEvaluationError):
            stashed.resolve()

    def test_type_check_happens_on_resolve(self):
        # A lazy argument that is never resolved is never type checked,
        # even if the underlying value has the wrong type.
        result = self.search('never_resolve(`1`)')
        self.assertEqual(result, 'not-resolved')
        # Resolving a lazy argument with the wrong type raises.
        with self.assertRaises(exceptions.JMESPathTypeError):
            self.search('lazy_string(`1`)')
        self.assertEqual(self.search("lazy_string('ok')"), 'ok')

    def test_lazy_argument_is_not_an_expref(self):
        self.assertEqual(self.search("lazy_kind('x')"), 'lazy')
        self.assertEqual(self.search('expref_kind(&foo)'), 'expref')

    def test_normal_arguments_still_eager(self):
        # boom() is passed as a normal (non-lazy) argument, so eager
        # evaluation semantics are unchanged for regular parameters.
        with self.assertRaises(RuntimeError):
            self.search("count(boom('b'))")
