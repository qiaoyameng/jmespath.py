import json

from tests import unittest

import jmespath
import jmespath.functions
from jmespath.tracing import TraceResult, Tracer


# Five elements, each exercising a different situation:
#   0: value present
#   1: explicit null on the leaf field
#   2: explicit null on an intermediate field
#   3: intermediate field missing entirely
#   4: leaf field missing entirely
ITEMS = {
    'items': [
        {'owner': {'name': 'alice'}},
        {'owner': {'name': None}},
        {'owner': None},
        {},
        {'owner': {}},
    ],
}


class CountingFunctions(jmespath.functions.Functions):
    def __init__(self):
        super(CountingFunctions, self).__init__()
        self.calls = []

    @jmespath.functions.signature({'types': []})
    def _func_count_me(self, value):
        self.calls.append(value)
        return value


class TestSearchTraced(unittest.TestCase):
    def test_result_matches_plain_search(self):
        traced = jmespath.search_traced('items[*].owner.name', ITEMS)
        self.assertIsInstance(traced, TraceResult)
        self.assertEqual(traced.result, ['alice'])
        self.assertEqual(
            traced.result, jmespath.search('items[*].owner.name', ITEMS))
        self.assertFalse(traced.truncated)

    def test_plain_search_is_unchanged(self):
        result = jmespath.search('items[*].owner.name', ITEMS)
        self.assertEqual(result, ['alice'])
        self.assertNotIsInstance(result, TraceResult)

    def test_explains_missing_fields(self):
        traced = jmespath.search_traced('items[*].owner.name', ITEMS)
        missing = [e for e in traced.events
                   if e['kind'] == 'missing_field']
        paths = [e['path'] for e in missing]
        self.assertIn(['items', 3, 'owner'], paths)
        self.assertIn(['items', 4, 'owner', 'name'], paths)

    def test_explains_explicit_nulls(self):
        traced = jmespath.search_traced('items[*].owner.name', ITEMS)
        nulls = [e for e in traced.events if e['kind'] == 'explicit_null']
        paths = [e['path'] for e in nulls]
        self.assertIn(['items', 1, 'owner', 'name'], paths)
        self.assertIn(['items', 2, 'owner'], paths)

    def test_explains_omitted_elements(self):
        traced = jmespath.search_traced('items[*].owner.name', ITEMS)
        omitted = [e for e in traced.events if e['kind'] == 'omitted']
        self.assertEqual(
            [e['path'] for e in omitted],
            [['items', 1], ['items', 2], ['items', 3], ['items', 4]])

    def test_events_record_expression_position(self):
        traced = jmespath.search_traced('items[*].owner.name', ITEMS)
        self.assertTrue(traced.events)
        for event in traced.events:
            self.assertTrue(event['expression'])
        missing_owner = [e for e in traced.events
                         if e['path'] == ['items', 3, 'owner']]
        self.assertEqual(len(missing_owner), 1)
        self.assertEqual(missing_owner[0]['expression'][-1],
                         'field:owner')

    def test_events_do_not_contain_data_values(self):
        traced = jmespath.search_traced('items[*].owner.name', ITEMS)
        for event in traced.events:
            self.assertEqual(
                set(event), {'kind', 'path', 'expression', 'detail'})
        self.assertNotIn('alice', json.dumps(traced.events))

    def test_filter_excluded_events(self):
        data = {'items': [{'name': 'a', 'keep': True},
                          {'name': 'b', 'keep': False},
                          {'name': 'c'}]}
        traced = jmespath.search_traced('items[?keep].name', data)
        self.assertEqual(traced.result, ['a'])
        excluded = [e for e in traced.events
                    if e['kind'] == 'filter_excluded']
        self.assertEqual([e['path'] for e in excluded],
                         [['items', 1], ['items', 2]])

    def test_value_projection_events(self):
        data = {'owners': {'a': {'name': 'x'}, 'b': {'name': None}}}
        traced = jmespath.search_traced('owners.*.name', data)
        self.assertEqual(traced.result, ['x'])
        nulls = [e for e in traced.events if e['kind'] == 'explicit_null']
        self.assertEqual([e['path'] for e in nulls],
                         [['owners', 'b', 'name']])
        omitted = [e for e in traced.events if e['kind'] == 'omitted']
        self.assertEqual([e['path'] for e in omitted], [['owners', 'b']])

    def test_truncation_marks_result_but_keeps_executing(self):
        traced = jmespath.search_traced(
            'items[*].owner.name', ITEMS, max_events=2)
        self.assertTrue(traced.truncated)
        self.assertEqual(len(traced.events), 2)
        self.assertEqual(traced.result, ['alice'])

    def test_unlimited_events(self):
        traced = jmespath.search_traced(
            'items[*].owner.name', ITEMS, max_events=None)
        self.assertFalse(traced.truncated)
        self.assertEqual(len(traced.events),
                         len(jmespath.search_traced(
                             'items[*].owner.name', ITEMS,
                             max_events=1000).events))

    def test_compiled_expression_search_traced(self):
        parsed = jmespath.compile('items[*].owner.name')
        traced = parsed.search_traced(ITEMS)
        self.assertIsInstance(traced, TraceResult)
        self.assertEqual(traced.result, ['alice'])

    def test_functions_are_not_reexecuted_for_tracing(self):
        data = {'items': [{'x': 1}, {'y': 2}, {'x': None}, {'x': 3}]}
        expression = 'items[*].count_me(x)'

        plain_functions = CountingFunctions()
        plain = jmespath.search(
            expression, data,
            options=jmespath.Options(custom_functions=plain_functions))

        traced_functions = CountingFunctions()
        traced = jmespath.search_traced(
            expression, data,
            options=jmespath.Options(custom_functions=traced_functions))

        self.assertEqual(plain, [1, 3])
        self.assertEqual(traced.result, plain)
        self.assertEqual(traced_functions.calls, plain_functions.calls)
        self.assertEqual(len(traced_functions.calls), 4)

    def test_short_circuit_is_not_reexecuted_for_tracing(self):
        expression = 'count_me(`1`) || count_me(`2`)'

        plain_functions = CountingFunctions()
        plain = jmespath.search(
            expression, {},
            options=jmespath.Options(custom_functions=plain_functions))

        traced_functions = CountingFunctions()
        traced = jmespath.search_traced(
            expression, {},
            options=jmespath.Options(custom_functions=traced_functions))

        self.assertEqual(plain, 1)
        self.assertEqual(traced.result, plain)
        self.assertEqual(plain_functions.calls, [1])
        self.assertEqual(traced_functions.calls, plain_functions.calls)

    def test_tracer_default_max_events(self):
        tracer = Tracer()
        self.assertEqual(tracer.max_events, Tracer.DEFAULT_MAX_EVENTS)
        self.assertEqual(tracer.events, [])
        self.assertFalse(tracer.truncated)
