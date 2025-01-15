import pytest
import sqlparse
from django.db.models.sql.subqueries import DeleteQuery
from shared.django_apps.core.models import Repository

from services.cleanup.relations import build_relation_graph


@pytest.mark.django_db
def test_builds_relation_graph(snapshot):
    relations = build_relation_graph(Repository.objects.filter(repoid=123))

    queries = ""
    for model, query in relations:
        compiler = query.query.chain(DeleteQuery).get_compiler(query.db)
        sql, _params = compiler.as_sql()
        sql = sqlparse.format(sql, reindent=True, keyword_case="upper")

        if queries:
            queries += "\n\n"
        queries += f"-- {model.__name__}\n{sql}\n"

    # if you change any of the model relations, this snapshot will most likely change.
    # in that case, feel free to update this using `pytest --insta update`.
    assert snapshot() == queries
