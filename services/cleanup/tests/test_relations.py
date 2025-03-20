import pytest
import sqlparse
from django.db.models.query import QuerySet
from django.db.models.sql.subqueries import DeleteQuery
from shared.django_apps.codecov_auth.models import Owner
from shared.django_apps.codecov_auth.tests.factories import OwnerFactory
from shared.django_apps.core.models import Repository
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.django_apps.reports.models import ReportDetails, TestInstance

from services.cleanup.relations import (
    build_relation_graph,
    reverse_filter,
    simplified_lookup,
)


def dump_delete_queries(queryset: QuerySet) -> str:
    relations = build_relation_graph(queryset)

    queries = ""
    for relation in relations:
        if queries:
            queries += "\n\n"
        queries += f"-- {relation.model.__name__}\n"

        for query in relation.querysets:
            compiler = query.query.chain(DeleteQuery).get_compiler(query.db)
            sql, _params = compiler.as_sql()
            sql = sqlparse.format(sql, reindent=True, keyword_case="upper")
            queries += sql + ";\n"

    return queries


@pytest.mark.django_db
def test_builds_delete_queries(snapshot):
    repo = Repository.objects.filter(repoid=123)
    org = Owner.objects.filter(ownerid=123)

    # if you change any of the model relations, this snapshot will most likely change.
    # in that case, feel free to update this using `pytest --insta update`.
    assert dump_delete_queries(repo) == snapshot("repository.txt")
    assert dump_delete_queries(org) == snapshot("owner.txt")


@pytest.mark.django_db
def test_can_simplify_queries():
    repo = Repository.objects.filter(repoid=123)
    assert simplified_lookup(repo) == [123]

    repo = Repository.objects.filter(repoid__in=[123, 456])
    assert simplified_lookup(repo) == [123, 456]

    repo = Repository.objects.filter(fork=123)
    assert simplified_lookup(repo) == repo

    owner_repos = Repository.objects.filter(author=123)
    repo = Repository.objects.filter(repoid__in=owner_repos)
    # In theory, we could simplify this to forward directly to the  `owner_repo`
    # subquery, but that would open too many opportunities to properly test.
    assert simplified_lookup(repo) == repo


@pytest.mark.django_db
def test_leaf_table(snapshot):
    query = ReportDetails.objects.all()
    assert dump_delete_queries(query) == snapshot("leaf.txt")


@pytest.mark.django_db
def test_can_reverse_filter():
    query = TestInstance.objects.filter(repoid=123)
    assert reverse_filter(query) is None

    query = TestInstance.objects.filter(repoid__in=[123, 234])
    assert reverse_filter(query) is None

    query = TestInstance.objects.filter(
        repoid__in=Repository.objects.filter(author=123), branch="foo"
    )
    assert reverse_filter(query) is None

    owner = OwnerFactory()
    r1 = RepositoryFactory(author=owner)
    r2 = RepositoryFactory(author=owner)
    r3 = RepositoryFactory(author=owner)

    filtered_qs = Repository.objects.filter(author=owner.ownerid)
    query = TestInstance.objects.filter(repoid__in=filtered_qs)

    column, reversed_query = reverse_filter(query)

    assert column == "repoid"
    # ideally, we would assert that the `QuerySet` itself is the same,
    # but that is not really doable. but in essense we only care that it yields
    # the same results, which it does:
    assert set(reversed_query) == set(filtered_qs)
    assert set(reversed_query) == {r1, r2, r3}
