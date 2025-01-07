from django.db.models.query import QuerySet

from services.cleanup.models import MANUAL_CLEANUP
from services.cleanup.relations import build_relation_graph
from services.cleanup.utils import CleanupContext


def run_cleanup(query: QuerySet) -> tuple[int, int]:
    """
    Cleans up all the models and storage files reachable from the given `QuerySet`.

    This deletes all database models in topological sort order, and also removes
    all the files in storage for any of the models in the relationship graph.

    Returns the number of models and files being cleaned up.
    """
    context = CleanupContext()
    models_to_cleanup = build_relation_graph(query)

    cleaned_models = 0
    cleaned_files = 0

    for model, query in models_to_cleanup:
        manual_cleanup = MANUAL_CLEANUP.get(model)
        if manual_cleanup is not None:
            res = manual_cleanup(context, query)
            cleaned_models += res[0]
            cleaned_files += res[1]

        else:
            cleaned_models += query._raw_delete(query.db)

    return (cleaned_models, cleaned_files)
