import logging
import re
import string

log = logging.getLogger(__name__)

remove_known_bad_paths = re.compile(
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


def unquote_git_path(path: str) -> str:
    """
    Undo git-style Unicode armor for paths.
    """

    # This armoring is documented under git-config, `core.quotePath`, e.g. at
    # https://git-scm.com/docs/git-config#Documentation/git-config.txt-corequotePath
    # There is no builtin codec for this, so we'll do it ourselves.

    # We'll use a string-builder technique. We'll put each byte into a list and
    # then turn the list into a string.
    rv = []
    i = 0
    while i < len(path):
        if path[i] == "\\":
            if path[i + 1] == "r":
                # The examples all match "users/.../Icon\r"
                # https://apple.stackexchange.com/questions/31867/what-is-icon-r-file-and-how-do-i-delete-them
                i += 2
            elif path[i + 1] in string.octdigits:
                # Decode an escaped byte; the next three characters are octets.
                rv.append(int(path[i + 1 : i + 4], 8))
                i += 4
            else:
                rv.append(ord(path[i + 1]))
                i += 2
        else:
            # Just copy the codepoint.
            rv.append(ord(path[i]))
            i += 1
    # Finally, decode with UTF-8.
    return bytes(rv).decode("utf-8")


def clean_toc(toc: str) -> list[str]:
    """
    Split a newline-delimited table of contents into a list of paths.

    Each path will be cleaned up slightly.
    """

    rv = []
    for path in toc.strip().split("\n"):
        # Detect and undo git's Unicode armoring.
        if path.startswith('"') and path.endswith('"'):
            path = unquote_git_path(path[1:-1])

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
