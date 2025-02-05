import dataclasses
from collections import defaultdict
from graphlib import TopologicalSorter

from django.db.models import Model
from django.db.models.expressions import Col, Expression
from django.db.models.lookups import Exact, In
from django.db.models.query import QuerySet
from shared.django_apps.bundle_analysis.models import CacheConfig
from shared.django_apps.codecov_auth.models import Owner, OwnerProfile
from shared.django_apps.core.models import Commit, Pull, Repository
from shared.django_apps.reports.models import DailyTestRollup, TestInstance
from shared.django_apps.user_measurements.models import UserMeasurement

# Relations referencing 0 through field 1 of model 2:
IGNORE_RELATIONS: set[tuple[type[Model], str, type[Model]]] = {
    (Owner, "default_org", OwnerProfile),
    (Owner, "bot", Owner),
    (Owner, "bot", Repository),
    (Owner, "author", Commit),
    (Owner, "author", Pull),
    (Repository, "forkid", Repository),
}

# Relations which have no proper foreign key:
UNDOCUMENTED_RELATIONS: list[tuple[type[Model], str, type[Model]]] = [
    (Repository, "repoid", TestInstance),
    (Repository, "repoid", DailyTestRollup),
    (Commit, "commit_id", UserMeasurement),
    (Owner, "owner_id", UserMeasurement),
    (Repository, "repo_id", UserMeasurement),
    (Repository, "repo_id", CacheConfig),
    # TODO: `UserMeasurement` also has `upload_id`, should we register that as well?
    # TODO: should we also include `SimpleMetric` here?
]


@dataclasses.dataclass
class Node:
    edges: dict[type[Model], list[str]] = dataclasses.field(
        default_factory=lambda: defaultdict(list)
    )
    querysets: list[QuerySet] = dataclasses.field(default_factory=list)
    depth: int = 9999


@dataclasses.dataclass
class ModelQueries:
    model: type[Model]
    querysets: list[QuerySet]


def build_relation_graph(query: QuerySet) -> list[ModelQueries]:
    """
    This takes as input a django `QuerySet`, like `Repository.objects.filter(repoid=123)`.

    It then walks the django relation graph, resolving all the models that have a relationship **to** the input model,
    returning those models along with a `QuerySet` that allows either querying or deleting those models.

    The returned list is in topological sorting order, so related models are always sorted before models they depend on.
    """
    nodes: dict[type[Model], Node] = defaultdict(Node)
    graph: TopologicalSorter[type[Model]] = TopologicalSorter()

    def process_relation(
        model: type[Model], related_model_field: str, related_model: type[Model]
    ):
        if (model, related_model_field, related_model) in IGNORE_RELATIONS:
            return

        graph.add(model, related_model)
        nodes[model].edges[related_model].append(related_model_field)

        if related_model not in nodes:
            process_model(related_model)

    def process_model(model: type[Model]):
        for (
            referenced_model,
            related_model_field,
            related_model,
        ) in UNDOCUMENTED_RELATIONS:
            if referenced_model == model:
                process_relation(model, related_model_field, related_model)

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
                process_relation(model, related_model_field, related_model)

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
                    process_relation(model, related_model_field, related_model)

    graph.add(query.model)
    process_model(query.model)

    # the topological sort yields models in the order we want to run deletions
    sorted_models = list(graph.static_order())

    # but for actually building the querysets, we prefer the order from root to leafs
    nodes[query.model].querysets = [query]
    nodes[query.model].depth = 0
    for model in reversed(sorted_models):
        node = nodes[model]
        depth = node.depth + 1
        in_filters = [simplified_lookup(qs) for qs in node.querysets]

        for related_model, related_fields in node.edges.items():
            related_node = nodes[related_model]

            if depth < related_node.depth:
                related_node.depth = depth
                queries_to_build = (
                    (field, in_filter)
                    for field in related_fields
                    for in_filter in in_filters
                )
                related_node.querysets = [
                    related_model.objects.filter(**{f"{field}__in": in_filter})
                    for field, in_filter in queries_to_build
                ]

    return [ModelQueries(model, nodes[model].querysets) for model in sorted_models]


def simplified_lookup(queryset: QuerySet) -> QuerySet | list[int]:
    """
    This potentially simplifies simple primary key lookups.

    The whole point of the `build_relation_graph` is to begin with a `QuerySet`,
    and most of the time, those are simple lookups by primary key.

    When chaining those to related objects, and we can detect that this is indeed
    a simple primary key lookup, we can eliminate one level of subqueries by
    returning the simplified lookup value.

    This is hopefully slightly faster, as the DB will still do an index scan for
    a subquery like `foreign_pk IN (SELECT pk FROM table WHERE pk=123)`.
    In that case, the expression will be simplified to `foreign_pk IN (123)`.
    """
    if queryset.query.is_sliced:
        return queryset

    where = queryset.query.where
    if len(where.children) != 1:
        return queryset

    condition = where.children[0]
    if not isinstance(condition, Expression) or not isinstance(condition.lhs, Col):
        return queryset

    column = condition.lhs.target
    if column.model == queryset.model and column.primary_key:
        if isinstance(condition, Exact) and condition.rhs_is_direct_value():
            return [condition.rhs]

        # In theory, this does not necessarily need to be a "direct value",
        # but it can also be a subquery. But lets be conservative here.
        if isinstance(condition, In) and condition.rhs_is_direct_value():
            return condition.rhs

    return queryset
