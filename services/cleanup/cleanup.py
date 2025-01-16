import logging

from django.db.models.query import QuerySet

from services.cleanup.models import MANUAL_CLEANUP
from services.cleanup.relations import build_relation_graph
from services.cleanup.utils import CleanupContext, CleanupResult, CleanupSummary

log = logging.getLogger(__name__)


def run_cleanup(
    query: QuerySet,
) -> CleanupSummary:
    """
    Cleans up all the models and storage files reachable from the given `QuerySet`.

    This deletes all database models in topological sort order, and also removes
    all the files in storage for any of the models in the relationship graph.

    Returns the number of models and files being cleaned up in total, and per-Model.
    """
    context = CleanupContext()
    models_to_cleanup = build_relation_graph(query)

    summary = {}
    cleaned_models = 0
    cleaned_files = 0

    for model, query in models_to_cleanup:
        manual_cleanup = MANUAL_CLEANUP.get(model)
        if manual_cleanup is not None:
            result = manual_cleanup(context, query)
        else:
            result = CleanupResult(query._raw_delete(query.db))

        if result.cleaned_models > 0 or result.cleaned_files > 0:
            summary[model] = result

            log.info(
                f"Finished cleaning up {model.__name__}",
                extra={
                    "cleaned_models": result.cleaned_models,
                    "cleaned_files": result.cleaned_files,
                },
            )

        cleaned_models += result.cleaned_models
        cleaned_files += result.cleaned_files

    totals = CleanupResult(cleaned_models, cleaned_files)
    return CleanupSummary(totals, summary)
