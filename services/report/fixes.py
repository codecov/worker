def get_fixes_from_raw(content, fix):
    files = {}
    files_long_comments = {}
    _cur_file = None
    lines = None
    ignore_this = None

    for line in content.splitlines():
        if line:
            try:
                if line[:5] == 'EOF: ':
                    _, line, filename = line.split(' ', 2)
                    files.setdefault(fix(filename), {})['eof'] = int(line)

                else:
                    # filename:5:<source>
                    # filename:5
                    # filename:5,10,20
                    filename, line = line.split(':', 1)

                    if _cur_file != filename:
                        _cur_file = filename
                        _fixed = fix(filename)
                        if not _fixed:
                            continue
                        lines = files.setdefault(_fixed, {'lines': set()})['lines']

                    if ':' not in line:
                        # multi line
                        for sp in line.split(','):
                            lines.add(int(sp))

                    else:
                        ln, source = line.split(':', 1)
                        ln = int(ln)
                        source = source.strip()

                        if source[:2] == '/*' or 'LCOV_EXCL_START' in source:
                            files_long_comments.setdefault(_fixed, ([], []))[0].append(ln)

                        elif source[-2:] == '*/' or 'LCOV_EXCL_STOP' in source or 'LCOV_EXCL_END' in source:
                            files_long_comments.setdefault(_fixed, ([], []))[1].append(ln)

                        lines.add(ln)

            except Exception:
                pass

    for filename, (starts, stops) in files_long_comments.items():
        if filename and starts and stops:
            starts = sorted(starts)
            stops = sorted(stops)
            lines = files[filename]['lines']
            for x in range(len(starts)):
                if len(stops) > x:
                    lines.update(range(int(starts[x])+1, int(stops[x])))

    return files
