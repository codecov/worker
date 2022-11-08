import os
import sys
from unittest import mock

from click.testing import CliRunner

from celery_config import HEALTH_CHECK_QUEUE
from main import _get_queues_param_from_queue_input, cli, main, setup_worker, test, web


def test_get_queues_param_from_queue_input():
    assert (
        _get_queues_param_from_queue_input(["worker,profiling,notify"])
        == f"worker,profiling,notify,{HEALTH_CHECK_QUEUE}"
    )
    assert (
        _get_queues_param_from_queue_input(["worker", "profiling", "notify"])
        == f"worker,profiling,notify,{HEALTH_CHECK_QUEUE}"
    )


def test_run_empty_config(mock_storage, mock_configuration):
    assert not mock_storage.root_storage_created
    res = setup_worker()
    assert res is None
    assert mock_storage.root_storage_created
    assert mock_storage.config == {}


def test_sys_path_append_on_enterprise(mock_storage, mock_configuration):
    sys.frozen = True
    res = setup_worker()
    assert res is None
    assert "./external_deps" in sys.path


def test_run_already_existing_root_storage(mock_storage, mock_configuration):
    mock_storage.root_storage_created = True
    res = setup_worker()
    assert res is None
    assert mock_storage.config == {}
    assert mock_storage.root_storage_created


def test_get_cli_help(mocker):
    runner = CliRunner()
    res = runner.invoke(cli, ["--help"])
    expected_output = "\n".join(
        [
            "Usage: cli [OPTIONS] COMMAND [ARGS]...",
            "",
            "Options:",
            "  --help  Show this message and exit.",
            "",
            "Commands:",
            "  test",
            "  web",
            "  worker",
            "",
        ]
    )

    assert res.output == expected_output


def test_deal_unsupported_commands(mocker):
    runner = CliRunner()
    test_res = runner.invoke(test, [])
    assert test_res.output == "Error: System not suitable to run TEST mode\n"
    web_res = runner.invoke(web, [])
    assert web_res.output == "Error: System not suitable to run WEB mode\n"


def test_deal_worker_command_default(mocker, mock_storage):
    mocker.patch.dict(os.environ, {"HOSTNAME": "simpleworker"})
    mocked_get_current_version = mocker.patch(
        "main.get_current_version", return_value="some_version_12.3"
    )
    mock_app = mocker.patch("main.app")
    runner = CliRunner()
    res = runner.invoke(cli, ["worker"])
    expected_output = "\n".join(
        [
            "",
            "  _____          _",
            " / ____|        | |",
            "| |     ___   __| | ___  ___ _____   __",
            "| |    / _ \\ / _` |/ _ \\/ __/ _ \\ \\ / /",
            "| |___| (_) | (_| |  __/ (_| (_) \\ V /",
            " \\_____\\___/ \\__,_|\\___|\\___\\___/ \\_/",
            "                              some_version_12.3",
            "",
            "",
            "",
        ]
    )
    assert res.output == expected_output
    mocked_get_current_version.assert_called_with()
    mock_app.celery_app.worker_main.assert_called_with(
        argv=[
            "worker",
            "-n",
            "simpleworker",
            "-c",
            2,
            "-l",
            "info",
            "-Q",
            f"celery,{HEALTH_CHECK_QUEUE}",
            "-B",
            "-s",
            "/home/codecov/celerybeat-schedule",
        ]
    )


def test_deal_worker_command(mocker, mock_storage):
    mocker.patch.dict(os.environ, {"HOSTNAME": "simpleworker"})
    mocked_get_current_version = mocker.patch(
        "main.get_current_version", return_value="some_version_12.3"
    )
    mock_app = mocker.patch("main.app")
    runner = CliRunner()
    res = runner.invoke(cli, ["worker", "--queue", "simple,one,two", "--queue", "some"])
    expected_output = "\n".join(
        [
            "",
            "  _____          _",
            " / ____|        | |",
            "| |     ___   __| | ___  ___ _____   __",
            "| |    / _ \\ / _` |/ _ \\/ __/ _ \\ \\ / /",
            "| |___| (_) | (_| |  __/ (_| (_) \\ V /",
            " \\_____\\___/ \\__,_|\\___|\\___\\___/ \\_/",
            "                              some_version_12.3",
            "",
            "",
            "",
        ]
    )
    assert res.output == expected_output
    mocked_get_current_version.assert_called_with()
    mock_app.celery_app.worker_main.assert_called_with(
        argv=[
            "worker",
            "-n",
            "simpleworker",
            "-c",
            2,
            "-l",
            "info",
            "-Q",
            f"simple,one,two,some,{HEALTH_CHECK_QUEUE}",
            "-B",
            "-s",
            "/home/codecov/celerybeat-schedule",
        ]
    )


def test_main(mocker):
    mock_cli = mocker.patch("main.cli")
    assert main() is None
    mock_cli.assert_called_with(obj={})
