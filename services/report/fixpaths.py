import logging
import re
from os.path import relpath

log = logging.getLogger(__name__)

_remove_target_delombok = re.compile(r'[^,]*/target/delombok/[^,]*,').sub

_remove_known_bad_paths = re.compile(r'^(\.*\/)*(%s)?' % '|'.join((
    r'((home|Users)/travis/build/[^\/\n]+/[^\/\n]+/)',
    r'((home|Users)/jenkins/jobs/[^\/\n]+/workspace/)',
    r'(Users/distiller/[^\/\n]+/)',
    r'(home/[^\/\n]+/src/([^\/\n]+/){3})',  # home/rof/src/github.com|bitbucket.org/owner/repo/
    r'((home|Users)/[^\/\n]+/workspace/[^\/\n]+/[^\/\n]+/)',  # /Users/user/workspace/owner/repo
    r'(.*/jenkins/workspace/[^\/\n]+/)',
    r'((.+/src/)?github\.com/[^\/\n]+/[^\/\n]+/)',
    r'(\w:/Repos/[^\/\n]+/[^\/\n]+/)',
    r'([\w:/]+projects/[^\/\n]+/)',
    r'(\w:/_build/GitHub/[^\/\n]+/)',
    r'(build/lib\.[^\/\n]+/)',
    r'(home/circleci/code/)',
    r'(home/circleci/repo/)',
    r'(vendor/src/.*)',
    r'(pipeline/source/)',
    r'(var/snap-ci/repo/)',
    r'(home/ubuntu/[^\/\n]+/)',
    r'(.*/site-packages/[^\/\n]+\.egg/)',  # python3+
    r'(.*/site-packages/)',
    r'(usr/local/lib/[^\/\n]+/dist-packages/)',
    r'(.*/slather/spec/fixtures/[^\n]*)',
    r'(.*/target/generated-sources/[^\n]*)',
    r'(.*/\.phpenv/.*)',
    r'(.*/Debug-iphonesimulator/ReactiveCocoa\.build/DerivedSources/RA.*)',
    r'(usr/include/.*)',
    r'(.*/handlebars\.js/dist/.*)',
    r'(node_modules/.*)',
    r'(bower_components/.*)',
    r'(.*/lib/clang/.*)',
    r'(.*[\<\>].*)',
    r'(\w\:\/)',  # E:/ C:/
    r'(.*/mac-coverage/build/src/.*)',
    r'(opt/.*/dist-packages/.*)',  # opt/ros/indigo/lib/python2.7/dist-packages/...
    r'(.*/iPhoneSimulator.platform/Developer/SDKs/.*)',
    r'(Applications/Xcode\.app/Contents/Developer/Toolchains/.*)',
    r'((.*/)?\.?v?(irtual)?\.?envs?(-[^\/\n]+)?/.*/[^\/\n]+\.py$)',
    r'(Users/[^\/\n]+/Projects/.*/Pods/.*)',
    r'(Users/[^\/\n]+/Projects/[^\/\n]+/)',
    r'(home/[^\/\n]+/[^\/\n]+/[^\/\n]+/)',  # /home/:user/:owner/:repo/
 )), re.I | re.M).sub


def clean_toc(toc):
    toc = toc.strip()
    if toc:
        toc = (
            ',%s,' % toc.replace('\\ ', ' ')  # remove escaping spaces
                        .replace('\\', '/')  # [windows] remove backslashes
                        .replace('\n', ',')
        ).replace(',./', ',')

        if '/target/delombok/' in toc:
            toc = _remove_target_delombok(toc, '')

        return toc


def clean_path(custom_fixes, path_matcher, resolver, path,
               disable_default_path_fixes=False):

    if not path:
        return None

    path = relpath(
        path.replace('\\', '/')
            .lstrip('./')
            .lstrip('../')
    )
    if custom_fixes:
        # applies pre
        path = custom_fixes(path, False)

    if resolver and not disable_default_path_fixes:
        path = resolver(path, ancestors=1)
        if not path:
            return None

    elif resolver is None:
        path = _remove_known_bad_paths('', path)

    if custom_fixes:
        # applied pre and post
        path = custom_fixes(path, True)

    if not path_matcher(path):
        return None

    return path


def first_not_null_index(_list):
    """return key of the first not null value in list
    """
    for i, v in enumerate(_list):
        if v is not None:
            return i


_star_to_glob = re.compile(r'(?<!\.)\*').sub


def _fixpaths_regs(fix):
    key = tuple(fix.split('::'))[0]
    # [DEPRECIATING] because handled by validators, but some data is cached in db
    # a/**/b => a/.*/b
    key = key.replace('**', r'.*')
    # a/*/b => a/[^\/\n]+/b
    key = _star_to_glob(r'[^\/\n]+', key)
    return key.lstrip('/')


def fixpaths_to_func(custom_fixes):
    if not custom_fixes:
        return None

    _prefix = set(filter(lambda a: a[:2] == '::', custom_fixes))
    custom_fixes = list(set(custom_fixes) - _prefix)
    if _prefix:
        _prefix = '/'.join(list(map(lambda p: p[2:].rstrip('/'), _prefix))[::-1])
    if custom_fixes:
        # regestry = [result, result]
        regestry = list(map(lambda fix: tuple(fix.split('::'))[1], custom_fixes))
        sub = re.compile(r'^(%s)' % ')|('.join(map(_fixpaths_regs, custom_fixes))).sub
    else:
        sub = None

    def func(path, prefix=True):
        if path:
            if prefix and _prefix:
                # apply prefix
                path = '%s/%s' % (_prefix, path)

            if sub:
                path = sub(lambda m: regestry[first_not_null_index(m.groups())], path, count=1)

            return path.replace('//', '/').lstrip('/')

    return func
