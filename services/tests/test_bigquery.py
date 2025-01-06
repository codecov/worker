import datetime as dt
from datetime import datetime

import polars as pl
import pytest

import generated_proto.sample.sample_pb2 as sample_pb2
from services.bigquery import BigQueryService

fake_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQDCFqq2ygFh9UQU/6PoDJ6L9e4ovLPCHtlBt7vzDwyfwr3XGxln
0VbfycVLc6unJDVEGZ/PsFEuS9j1QmBTTEgvCLR6RGpfzmVuMO8wGVEO52pH73h9
rviojaheX/u3ZqaA0di9RKy8e3L+T0ka3QYgDx5wiOIUu1wGXCs6PhrtEwICBAEC
gYBu9jsi0eVROozSz5dmcZxUAzv7USiUcYrxX007SUpm0zzUY+kPpWLeWWEPaddF
VONCp//0XU8hNhoh0gedw7ZgUTG6jYVOdGlaV95LhgY6yXaQGoKSQNNTY+ZZVT61
zvHOlPynt3GZcaRJOlgf+3hBF5MCRoWKf+lDA5KiWkqOYQJBAMQp0HNVeTqz+E0O
6E0neqQDQb95thFmmCI7Kgg4PvkS5mz7iAbZa5pab3VuyfmvnVvYLWejOwuYSp0U
9N8QvUsCQQD9StWHaVNM4Lf5zJnB1+lJPTXQsmsuzWvF3HmBkMHYWdy84N/TdCZX
Cxve1LR37lM/Vijer0K77wAx2RAN/ppZAkB8+GwSh5+mxZKydyPaPN29p6nC6aLx
3DV2dpzmhD0ZDwmuk8GN+qc0YRNOzzJ/2UbHH9L/lvGqui8I6WLOi8nDAkEA9CYq
ewfdZ9LcytGz7QwPEeWVhvpm0HQV9moetFWVolYecqBP4QzNyokVnpeUOqhIQAwe
Z0FJEQ9VWsG+Df0noQJBALFjUUZEtv4x31gMlV24oiSWHxIRX4fEND/6LpjleDZ5
C/tY+lZIEO1Gg/FxSMB+hwwhwfSuE3WohZfEcSy+R48=
-----END RSA PRIVATE KEY-----"""

gcp_config = {
    "type": "service_account",
    "project_id": "codecov-dev",
    "private_key_id": "testu7gvpfyaasze2lboblawjb3032mbfisy9gpg",
    "private_key": fake_private_key,
    "client_email": "localstoragetester@genuine-polymer-165712.iam.gserviceaccount.com",
    "client_id": "110927033630051704865",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/localstoragetester%40genuine-polymer-165712.iam.gserviceaccount.com",
}


sql = """
WITH sample_data AS (
    SELECT * FROM UNNEST([
        STRUCT(TIMESTAMP '2025-01-01T00:00:00Z' AS timestamp, 1 AS id, 'name' AS name),
        STRUCT(TIMESTAMP '2024-12-30T00:00:00Z' AS timestamp, 2 AS id, 'name2' AS name)
    ])
)
SELECT * FROM sample_data
"""


@pytest.mark.skip(reason="This test requires being run using actual working creds")
def test_bigquery_service(codecov_vcr):
    bigquery_service = BigQueryService(gcp_config)

    results = bigquery_service.query(sql)

    assert len(results) == 2
    assert set([row["timestamp"] for row in results]) == {
        datetime.fromisoformat("2025-01-01T00:00:00Z"),
        datetime.fromisoformat("2024-12-30T00:00:00Z"),
    }
    assert set([row["name"] for row in results]) == {"name", "name2"}
    assert set([row["id"] for row in results]) == {1, 2}


@pytest.mark.skip(reason="This test requires being run using actual working creds")
def test_bigquery_service_polars(codecov_vcr):
    bigquery_service = BigQueryService(gcp_config)

    results = bigquery_service.query_polars(
        sql,
        None,
        [
            ("timestamp", pl.Datetime(time_zone=dt.UTC)),
            "id",
            "name",
        ],
    )

    assert len(results) == 2
    assert set(results["timestamp"].to_list()) == {
        datetime.fromisoformat("2025-01-01T00:00:00Z"),
        datetime.fromisoformat("2024-12-30T00:00:00Z"),
    }
    assert set(results["name"].to_list()) == {"name", "name2"}
    assert set(results["id"].to_list()) == {1, 2}


# this test should only be run manually when making changes to the way we write to bigquery
# the reason it's not automated is because vcrpy does not seem to work with the gRPC requests
@pytest.mark.skip(reason="This test requires being run using actual working creds")
def test_bigquery_service_write():
    table_name = "codecov-dev.test_dataset.sample_table"
    bigquery_service = BigQueryService(gcp_config)

    bigquery_service.query(f"TRUNCATE TABLE `{table_name}`")

    data = [
        sample_pb2.Sample(
            timestamp="2025-01-01T00:00:00Z",
            id="1",
            name="name",
        ),
        sample_pb2.Sample(
            timestamp="2024-12-30T00:00:00Z",
            id="2",
            name="name2",
        ),
    ]

    serialized_data = [row.SerializeToString() for row in data]

    bigquery_service.write(
        "test_dataset",
        "test_table",
        sample_pb2,
        serialized_data,
    )

    results = bigquery_service.query(f"SELECT * FROM `{table_name}`")

    assert len(results) == 2

    assert set([row["timestamp"] for row in results]) == set(
        [
            datetime.fromisoformat("2025-01-01T00:00:00Z"),
            datetime.fromisoformat("2024-12-30T00:00:00Z"),
        ]
    )
    assert set([row["name"] for row in results]) == set(["name", "name2"])
