import dataclasses
from collections import defaultdict
from graphlib import TopologicalSorter

from django.db.models import Model, Q
from django.db.models.query import QuerySet


@dataclasses.dataclass
class Node:
    edges: dict[type[Model], list[str]] = dataclasses.field(
        default_factory=lambda: defaultdict(list)
    )
    queryset: QuerySet = dataclasses.field(default_factory=Q)
    depth: int = 9999


def build_relation_graph(query: QuerySet) -> list[tuple[type[Model], QuerySet]]:
    """
    This takes as input a django `QuerySet`, like `Repository.objects.filter(repoid=123)`.

    It then walks the django relation graph, resolving all the models that have a relationship **to** the input model,
    returning those models along with a `QuerySet` that allows either querying or deleting those models.

    The returned list is in topological sorting order, so related models are always sorted before models they depend on.
    """
    nodes: dict[type[Model], Node] = defaultdict(Node)
    graph: TopologicalSorter[type[Model]] = TopologicalSorter()

    def process_model(model: type[Model]):
        if model in nodes:
            return
        if not (meta := model._meta):
            return

        for field in meta.get_fields(include_hidden=True):
            if not field.is_relation:
                continue

            if field.one_to_many or field.one_to_one:
                # Most likely the reverse of a `ForeignKey`
                # <https://docs.djangoproject.com/en/5.1/ref/models/fields/#django.db.models.Field.one_to_many>

                if not hasattr(field, "field"):
                    # I believe this is the actual *forward* definition of a `OneToOne`
                    continue

                # this should be the actual `ForeignKey` definition:
                actual_field = field.field
                if actual_field.model == model:
                    # this field goes from *this* model to another, but we are interested in the reverse actually
                    continue

                related_model = actual_field.model
                related_model_field = actual_field.name

                graph.add(model, related_model)
                nodes[model].edges[related_model].append(related_model_field)
                process_model(related_model)

            elif field.many_to_many:
                if not hasattr(field, "through"):
                    # we want to delete all related records on the join table
                    continue

                related_model = field.through
                join_meta = related_model._meta
                for field in join_meta.get_fields(include_hidden=True):
                    if not field.is_relation or field.model != model:
                        continue

                    related_model_field = actual_field.name

                    graph.add(model, related_model)
                    nodes[model].edges[related_model].append(related_model_field)
                    process_model(related_model)

    process_model(query.model)

    # the topological sort yields models in the order we want to run deletions
    sorted_models = list(graph.static_order())

    # but for actually building the querysets, we prefer the order from root to leafs
    nodes[query.model].queryset = query
    nodes[query.model].depth = 0
    for model in reversed(sorted_models):
        node = nodes[model]
        depth = node.depth + 1

        for related_model, related_fields in node.edges.items():
            related_node = nodes[related_model]

            if depth < related_node.depth:
                filter = Q()
                for field in related_fields:
                    filter = filter | Q(**{f"{field}__in": node.queryset})

                related_node.queryset = related_model.objects.filter(filter)
                related_node.depth = depth

    return [(model, nodes[model].queryset) for model in sorted_models]
