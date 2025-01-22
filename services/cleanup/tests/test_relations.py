import pytest
import sqlparse
from django.db.models.query import QuerySet
from django.db.models.sql.subqueries import DeleteQuery
from shared.django_apps.codecov_auth.models import Owner
from shared.django_apps.core.models import Repository

from services.cleanup.relations import build_relation_graph


def dump_delete_queries(queryset: QuerySet) -> str:
    relations = build_relation_graph(queryset)

    queries = ""
    for model, query in relations:
        compiler = query.query.chain(DeleteQuery).get_compiler(query.db)
        sql, _params = compiler.as_sql()
        sql = sqlparse.format(sql, reindent=True, keyword_case="upper")

        if queries:
            queries += "\n\n"
        queries += f"-- {model.__name__}\n{sql}\n"

    return queries


@pytest.mark.django_db
def test_builds_delete_queries(snapshot):
    repo = Repository.objects.filter(repoid=123)
    org = Owner.objects.filter(ownerid=123)

    # if you change any of the model relations, this snapshot will most likely change.
    # in that case, feel free to update this using `pytest --insta update`.
    assert dump_delete_queries(repo) == snapshot("repository.txt")
    assert dump_delete_queries(org) == snapshot("owner.txt")
