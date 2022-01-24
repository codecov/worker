import os

import pytest

from main import (
    deal_test_command,
    deal_web_command,
    deal_worker_command,
    get_arg_parser,
    main,
    setup_worker,
)


def test_run_empty_config(mock_storage, mock_configuration):
    assert not mock_storage.root_storage_created
    res = setup_worker()
    assert res is None
    assert mock_storage.root_storage_created
    assert mock_storage.config == {}


def test_run_already_existing_root_storage(mock_storage, mock_configuration):
    mock_storage.root_storage_created = True
    res = setup_worker()
    assert res is None
    assert mock_storage.config == {}
    assert mock_storage.root_storage_created


def test_get_arg_parser():
    res = get_arg_parser()
    print(dir(res))
    assert res.prog == "codecov"


def test_deal_unsupported_commands(mocker):
    with pytest.raises(SystemExit):
        deal_test_command(get_arg_parser(), mocker.MagicMock())
    with pytest.raises(SystemExit):
        deal_web_command(get_arg_parser(), mocker.MagicMock())


def test_deal_worker_command(mocker, mock_storage):
    mock_app = mocker.patch("main.app")
    parser, codecov = mocker.MagicMock(), mocker.MagicMock(debug=False)
    res = deal_worker_command(parser, codecov)
    assert res == mock_app.celery_app.worker_main.return_value
    mock_app.celery_app.worker_main.assert_called_with(
        argv=[
            "worker",
            "-n",
            codecov.name,
            "-c",
            codecov.concurrency,
            "-l",
            "info",
            "-Q",
            codecov.queue,
            "-B",
            "-s",
            "/tmp/celerybeat-schedule",
        ]
    )


def test_main(mocker, mock_storage):
    mock_get_arg_parser = mocker.patch("main.get_arg_parser")
    codecov, unknown = (
        mocker.MagicMock(func=mocker.MagicMock(return_value="return_value")),
        mocker.MagicMock(debug=False),
    )
    mock_get_arg_parser.return_value.parse_known_args.return_value = codecov, unknown
    res = main()
    assert res == "return_value"
