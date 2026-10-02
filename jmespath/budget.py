from jmespath import exceptions


class ExecutionBudget(object):
    """Execution limits shared by an entire JMESPath search."""

    def __init__(self, max_nodes=None, max_collection_elements=None):
        self.max_nodes = self._validate_limit(max_nodes, 'max_nodes')
        self.max_collection_elements = self._validate_limit(
            max_collection_elements, 'max_collection_elements')

    def _validate_limit(self, value, name):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError('%s must be a non-negative integer' % name)
        if value < 0:
            raise ValueError('%s must be a non-negative integer' % name)
        return value

    @property
    def enabled(self):
        return (self.max_nodes is not None or
                self.max_collection_elements is not None)


class ExecutionBudgetMeter(object):
    """Per-search consumption for one execution budget."""

    NODE_EVALUATIONS = 'node_evaluations'
    COLLECTION_ELEMENTS = 'collection_elements'

    def __init__(self, budget, expression=None):
        self.budget = budget
        self.expression = expression
        self.usage = {
            self.NODE_EVALUATIONS: 0,
            self.COLLECTION_ELEMENTS: 0,
        }
        self.exceeded = False
        self.exceeded_error = None

    def charge_node(self, node, location=None):
        self._charge(
            self.NODE_EVALUATIONS, self.budget.max_nodes, 1, node, location)

    def charge_collection(self, value, node, location=None):
        if isinstance(value, (list, dict, tuple)):
            self.charge_elements(len(value), node, location)
        return value

    def charge_elements(self, amount, node, location=None):
        self._charge(
            self.COLLECTION_ELEMENTS,
            self.budget.max_collection_elements,
            amount,
            node,
            location)

    def _charge(self, category, limit, amount, node, location=None):
        self.usage[category] += amount
        if limit is not None and self.usage[category] > limit:
            self.exceeded = True
            position = getattr(node, 'start', None)
            if position is None and location is not None:
                position = getattr(location, 'start', None)
            error = exceptions.BudgetExceededError(
                category=category,
                limit=limit,
                usage=self.usage[category],
                expression=self.expression,
                position=position,
                node_type=node.get('type') if isinstance(node, dict) else None)
            self.exceeded_error = error
            raise error


class NullExecutionBudgetMeter(object):
    exceeded = False

    def charge_node(self, node, location=None):
        pass

    def charge_collection(self, value, node, location=None):
        return value

    def charge_elements(self, amount, node, location=None):
        pass
