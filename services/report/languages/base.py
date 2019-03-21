class BaseLanguageProcessor(object):

    def __init__(self, *args, **kwargs):
        pass

    def matches_content(self, content, first_line, name):
        pass

    def process(self, content, path_fixer, ignored_lines, sessionid):
        pass
