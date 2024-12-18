from shared.django_apps.core.models import Repository

from services.cleanup.relations import build_relation_graph


def test_builds_relation_graph(db):
    print()
    relations = build_relation_graph(Repository.objects.filter(repoid=123))
    for model, query in relations:
        print(model, str(query.query))
