from jmespath import exceptions


class ExecutionBudget(object):
    """Per-search limits for JMESPath evaluation work."""
    NODE_EVALUATIONS = 'node_evaluations'
    INTERMEDIATE_ELEMENTS = 'intermediate_elements'

    def __init__(self, node_evaluations=None, intermediate_elements=None):
        self._limits = {
            self.NODE_EVALUATIONS: self._validate_limit(
                node_evaluations, self.NODE_EVALUATIONS),
            self.INTERMEDIATE_ELEMENTS: self._validate_limit(
                intermediate_elements, self.INTERMEDIATE_ELEMENTS),
        }

    @property
    def limits(self):
        return dict(self._limits)

    def _validate_limit(self, value, name):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError('%s must be an integer or None' % name)
        if value < 0:
            raise ValueError('%s must be greater than or equal to 0' % name)
        return value


class _BudgetMeter(object):
    def __init__(self, budget):
        self._limits = budget.limits
        self.usage = {
            ExecutionBudget.NODE_EVALUATIONS: 0,
            ExecutionBudget.INTERMEDIATE_ELEMENTS: 0,
        }

    def charge_visit(self, node, position, end_position, expression):
        self._charge(
            ExecutionBudget.NODE_EVALUATIONS, 1, node, position,
            end_position, expression)

    def charge_result(self, result, node, position, end_position, expression):
        if isinstance(result, (list, dict)):
            self._charge(
                ExecutionBudget.INTERMEDIATE_ELEMENTS, len(result),
                node, position, end_position, expression)

    def _charge(self, category, amount, node, position, end_position,
                expression):
        self.usage[category] += amount
        limit = self._limits[category]
        if limit is not None and self.usage[category] > limit:
            raise exceptions.BudgetExceededError(
                category=category,
                limit=limit,
                used=self.usage[category],
                usage=dict(self.usage),
                node_type=node['type'],
                position=position,
                end_position=end_position,
                expression=expression)
