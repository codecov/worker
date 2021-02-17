import logging
import re
from typing import Optional, Sequence

log = logging.getLogger(__name__)

_remove_known_bad_paths = re.compile(
    r"^(\.*\/)*(%s)?"
    % "|".join(
        (
            r"((home|Users)/travis/build/[^\/\n]+/[^\/\n]+/)",
            r"((home|Users)/jenkins/jobs/[^\/\n]+/workspace/)",
            r"(Users/distiller/[^\/\n]+/)",
            r"(home/[^\/\n]+/src/([^\/\n]+/){3})",  # home/rof/src/github.com|bitbucket.org/owner/repo/
            r"((home|Users)/[^\/\n]+/workspace/[^\/\n]+/[^\/\n]+/)",  # /Users/user/workspace/owner/repo
            r"(.*/jenkins/workspace/[^\/\n]+/)",
            r"((.+/src/)?github\.com/[^\/\n]+/[^\/\n]+/)",
            r"(\w:/Repos/[^\/\n]+/[^\/\n]+/)",
            r"([\w:/]+projects/[^\/\n]+/)",
            r"(\w:/_build/GitHub/[^\/\n]+/)",
            r"(build/lib\.[^\/\n]+/)",
            r"(home/circleci/code/)",
            r"(home/circleci/repo/)",
            r"(vendor/src/.*)",
            r"(pipeline/source/)",
            r"(var/snap-ci/repo/)",
            r"(home/ubuntu/[^\/\n]+/)",
            r"(.*/site-packages/[^\/\n]+\.egg/)",  # python3+
            r"(.*/site-packages/)",
            r"(usr/local/lib/[^\/\n]+/dist-packages/)",
            r"(.*/slather/spec/fixtures/[^\n]*)",
            r"(.*/target/generated-sources/[^\n]*)",
            r"(.*/\.phpenv/.*)",
            r"(.*/Debug-iphonesimulator/ReactiveCocoa\.build/DerivedSources/RA.*)",
            r"(usr/include/.*)",
            r"(.*/handlebars\.js/dist/.*)",
            r"(node_modules/.*)",
            r"(bower_components/.*)",
            r"(.*/lib/clang/.*)",
            r"(.*[\<\>].*)",
            r"(\w\:\/)",  # E:/ C:/
            r"(.*/mac-coverage/build/src/.*)",
            r"(opt/.*/dist-packages/.*)",  # opt/ros/indigo/lib/python2.7/dist-packages/...
            r"(.*/iPhoneSimulator.platform/Developer/SDKs/.*)",
            r"(Applications/Xcode\.app/Contents/Developer/Toolchains/.*)",
            r"((.*/)?\.?v?(irtual)?\.?envs?(-[^\/\n]+)?/.*/[^\/\n]+\.py$)",
            r"(Users/[^\/\n]+/Projects/.*/Pods/.*)",
            r"(Users/[^\/\n]+/Projects/[^\/\n]+/)",
            r"(home/[^\/\n]+/[^\/\n]+/[^\/\n]+/)",  # /home/:user/:owner/:repo/
        )
    ),
    re.I | re.M,
).sub


def clean_toc(toc: str) -> Sequence[str]:
    """
    Split a newline-delimited table of contents into a list of paths.

    Each path will be cleaned up slightly.
    """

    rv = []
    for path in toc.strip().split("\n"):
        # Unescape escaped spaces.
        path = path.replace("\\ ", " ")
        # Windows: Fix backslashes.
        path = path.replace("\\", "/")
        # Fix relative paths which start in the current directory.
        if path.startswith("./"):
            path = path[2:]

        # Unconditionally remove delombok'd Java source code.
        # This can happen when folks upload code which uses the Lombok Java library.
        # This code would confuse coverage, duplicating real code, so we discard it. ~ C.
        if "/target/delombok/" in path:
            continue

        # This path is good; save it.
        rv.append(path)

    return rv


def first_not_null_index(_list) -> Optional[int]:
    """return key of the first not null value in list
    """
    for i, v in enumerate(_list):
        if v is not None:
            return i


_star_to_glob = re.compile(r"(?<!\.)\*").sub


def _fixpaths_regs(fix: str) -> str:
    key = tuple(fix.split("::"))[0]
    # [DEPRECIATING] because handled by validators, but some data is cached in db
    # a/**/b => a/.*/b
    key = key.replace("**", r".*")
    # a/*/b => a/[^\/\n]+/b
    key = _star_to_glob(r"[^\/\n]+", key)
    return key.lstrip("/")
