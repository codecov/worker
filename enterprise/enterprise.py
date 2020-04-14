# -*- coding: utf-8 -*-
import app
import argparse
import os


def deal_web_command(parser, codecov):
    parser.error("System not suitable to run WEB mode")


def deal_worker_command(parser, codecov):
    return app.celery_app.worker_main(
        argv=[
            "worker",
            "-n",
            codecov.name,
            "-c",
            codecov.concurrency,
            "-l",
            ("debug" if codecov.debug else "info"),
            "-Q",
            codecov.queue,
        ]
    )


def deal_test_command(parser, codecov_args):
    parser.error("System not suitable to run TEST mode")


def get_arg_parser():
    parser = argparse.ArgumentParser(
        prog="codecov",
        add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Read more at https://github.com/codecov/enterprise""",
    )
    subparsers = parser.add_subparsers(title="Commands")

    cmd_web = subparsers.add_parser("web")
    cmd_web.set_defaults(proc="web", func=deal_web_command)

    cmd_worker = subparsers.add_parser("worker")
    cmd_worker.set_defaults(
        proc="worker",
        func=deal_worker_command,
        help="Run the celery worker. Take same arguments as 'celery worker'.",
    )
    cmd_worker.add_argument(
        "-c",
        "--concurrency",
        nargs="?",
        default="2",
        help="number or celery concurrency",
    )
    cmd_worker.add_argument(
        "-n",
        "--name",
        dest="name",
        nargs="?",
        default=os.getenv("HOSTNAME", "worker"),
        help="node name",
    )
    cmd_worker.add_argument(
        "-q",
        "--queue",
        nargs="?",
        default="celery",
        help="queues to listen to for this worker",
    )
    cmd_worker.add_argument(
        "--debug", action="store_true", default=False, help="enable celery debug mode"
    )

    cmd_test = subparsers.add_parser("test", help="Run tests on service integrations")
    cmd_test.set_defaults(proc="test", func=deal_test_command)
    return parser


def main():
    parser = get_arg_parser()
    codecov, unknown = parser.parse_known_args()
    return codecov.func(parser, codecov)


if __name__ == "__main__":
    main()
