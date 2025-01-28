from types import ModuleType
from typing import Dict, List, Sequence, cast

import polars as pl
from google.api_core import retry
from google.cloud import bigquery
from google.cloud.bigquery_storage_v1 import BigQueryWriteClient, types
from google.cloud.bigquery_storage_v1.writer import AppendRowsStream
from google.oauth2.service_account import Credentials
from google.protobuf import descriptor_pb2
from shared.config import get_config


class BigQueryService:
    """
    Requires a table to be created with a time partitioning schema.
    """

    def __init__(
        self,
        gcp_config: dict[str, str],
    ) -> None:
        """Initialize BigQuery client with GCP credentials.

        Args:
            gcp_config: Dictionary containing Google Cloud service account credentials
                including project_id, private_key and other required fields
        Raises:
            google.api_core.exceptions.GoogleAPIError: If client initialization fails
            ValueError: If required credentials are missing from gcp_config
            google.auth.exceptions.DefaultCredentialsError: If credentials are not found
        """
        self.credentials = Credentials.from_service_account_info(gcp_config)

        if not self.credentials.project_id:
            raise ValueError("Project ID is not set")

        self.project_id = cast(str, self.credentials.project_id)

        self.client = bigquery.Client(
            project=self.project_id, credentials=self.credentials
        )

    def write(
        self,
        dataset_id: str,
        table_id: str,
        proto_module: ModuleType,
        data: list[bytes],
    ) -> None:
        """Write records to the BigQuery table using the Storage Write API.
        Uses protobuf encoded models defined in the protobuf directory.

        Args:
            table_id: Full table ID in format 'project.dataset.table'
            data: List of already encoded proto2 bytes

        Raises:
            google.api_core.exceptions.GoogleAPIError: If the API request fails
        """

        self.write_client = BigQueryWriteClient(credentials=self.credentials)

        parent = self.write_client.table_path(self.project_id, dataset_id, table_id)

        write_stream = types.WriteStream()

        write_stream.type_ = types.WriteStream.Type.PENDING
        write_stream = self.write_client.create_write_stream(
            parent=parent, write_stream=write_stream
        )
        stream_name = write_stream.name

        request_template = types.AppendRowsRequest()
        request_template.write_stream = stream_name

        proto_descriptor = descriptor_pb2.DescriptorProto()
        proto_module.DESCRIPTOR.message_types_by_name.values()[0].CopyToProto(
            proto_descriptor
        )

        proto_schema = types.ProtoSchema()
        proto_schema.proto_descriptor = proto_descriptor

        proto_data = types.AppendRowsRequest.ProtoData()
        proto_data.writer_schema = proto_schema

        request_template.proto_rows = proto_data

        append_rows_stream = AppendRowsStream(self.write_client, request_template)

        proto_rows = types.ProtoRows()
        proto_rows.serialized_rows = data

        request = types.AppendRowsRequest()
        request.offset = 0
        proto_data = types.AppendRowsRequest.ProtoData()
        proto_data.rows = proto_rows
        request.proto_rows = proto_data

        _ = append_rows_stream.send(request)

        self.write_client.finalize_write_stream(name=write_stream.name)

        batch_commit_write_streams_request = types.BatchCommitWriteStreamsRequest()
        batch_commit_write_streams_request.parent = parent
        batch_commit_write_streams_request.write_streams = [write_stream.name]

        self.write_client.batch_commit_write_streams(batch_commit_write_streams_request)

    def query(
        self,
        query: str,
        params: Sequence[
            bigquery.ScalarQueryParameter
            | bigquery.RangeQueryParameter
            | bigquery.ArrayQueryParameter
            | bigquery.StructQueryParameter
        ]
        | None = None,
    ) -> List[Dict]:
        """Execute a BigQuery SQL query and return results.
        Try not to write INSERT statements and use the write method instead.

        Args:
            query: SQL query string
            params: Optional dict of query parameters

        Returns:
            List of dictionaries containing the query results

        Raises:
            google.api_core.exceptions.GoogleAPIError: If the query fails
        """
        job_config = bigquery.QueryJobConfig()

        if params:
            job_config.query_parameters = params

        row_iterator = self.client.query_and_wait(
            query, job_config=job_config, retry=retry.Retry(deadline=30)
        )

        return [dict(row.items()) for row in row_iterator]

    def query_polars(
        self,
        query: str,
        params: dict | None = None,
        schema: list[str | tuple[str, pl.DataType]] | None = None,
    ) -> pl.DataFrame:
        """Execute a BigQuery SQL query and return results.
        Try not to write INSERT statements and use the write method instead.

        Args:
            query: SQL query string
            params: Optional dict of query parameters

        Returns:
            List of dictionaries containing the query results

        Raises:
            google.api_core.exceptions.GoogleAPIError: If the query fails
        """
        job_config = bigquery.QueryJobConfig()

        if params:
            job_config.query_parameters = [
                bigquery.ScalarQueryParameter(k, "STRING", v) for k, v in params.items()
            ]

        row_iterator = self.client.query_and_wait(
            query, job_config=job_config, retry=retry.Retry(deadline=30)
        )

        return pl.DataFrame(
            (dict(row.items()) for row in row_iterator), schema=schema, orient="row"
        )


def get_bigquery_service():
    gcp_config: dict[str, str] = get_config("services", "gcp", default={})
    return BigQueryService(gcp_config)
