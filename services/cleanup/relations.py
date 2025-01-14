# from pprint import pprint

from graphlib import TopologicalSorter

from django.db.models import Model
from django.db.models.query import QuerySet


def build_relation_graph(query: QuerySet) -> list[tuple[type[Model], QuerySet]]:
    """
    This takes as input a django `QuerySet`, like `Repository.objects.filter(repoid=123)`.

    It then walks the django relation graph, resolving all the models that have a relationship **to** the input model,
    returning those models along with a `QuerySet` that allows either querying or deleting those models.

    The returned list is in topological sorting order, so related models are always sorted before models they depend on.
    """
    graph: TopologicalSorter[type[Model]] = TopologicalSorter()
    querysets: dict[type[Model], QuerySet] = {}

    def process_model(model: type[Model], query: QuerySet):
        if model in querysets:
            querysets[model] = querysets[model] | query
            return
        querysets[model] = query

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
                related_query = related_model.objects.filter(
                    **{f"{related_model_field}__in": query}
                )
                graph.add(model, related_model)
                process_model(related_model, related_query)

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
                    related_query = related_model.objects.filter(
                        **{f"{related_model_field}__in": query}
                    )
                    graph.add(model, related_model)
                    process_model(related_model, related_query)

                # pprint(vars(field.through._meta))

    process_model(query.model, query)

    return [(model, querysets[model]) for model in graph.static_order()]
