from typing import Sequence
from decimal import Decimal
import re
import logging

from covreports.resources import ReportTotals

from services.notification.changes import Change
from services.yaml.reader import round_number, get_minimum_precision


log = logging.getLogger(__name__)

zero_change_regex = re.compile('0.0+%?')


def format_number_to_str(yml, value, if_zero=None, if_null=None, plus=False, style='{0}'):
    if value is None:
        return if_null
    precision = get_minimum_precision(yml)
    value = Decimal(value)
    res = round_number(yml, value)

    if if_zero and value == 0:
        return if_zero

    if res == 0 and value != 0:
        # <.01
        return style.format(
            '%s<%s' % ('+' if plus and value > 0 else '' if value > 0 else '-', precision)
        )

    if plus and res > Decimal('0'):
        res = '+' + str(res)
    return style.format(res)


def add_plus_sign(value):
    if value in ('', '0', '0%') or zero_change_regex.fullmatch(value):
        return ''
    elif value[0] != '-':
        return ('+%s' % value)
    else:
        return value


def list_to_text_table(rows, padding=0):
    """
    Assumes align left.

    list_to_text_table(
      [
          ('|##', 'master|', 'stable|', '+/-|', '##|'),
          ('+', '1|', '2|', '+1', ''),
      ], 2) == ['##   master   stable   +/-   ##',
                '+         1        2    +1     ']

    """
    # (2, 6, 6, 3, 2)
    column_w = list(
        map(
            max,
            zip(*map(lambda row: map(lambda cell: len(cell.strip('|')), row), rows))
        )
    )

    def _fill(a):
        w, cell = a
        return '{text:{fill}{align}{width}}'.format(
            text=cell.strip('|'),
            fill=' ',
            align=(('^' if cell[:1] == '|' else '>') if cell[-1:] == '|' else '<'),
            width=w
        )

    # now they are filled with spaces
    spacing = (' ' * padding).join
    return list(
        map(
            lambda row: spacing(map(_fill, zip(column_w, row))),
            rows
        )
    )


def diff_to_string(current_yaml,
                   base_title, base,
                   head_title, head):
    """
    ('master', {},
     'stable', {},
     ('ui', before, after), ...})
    """

    def F(value):
        if value is None:
            return '?'
        elif isinstance(value, str):
            return '%s%%' % round_number(current_yaml, Decimal(value))
        else:
            return value

    def _row(title, c1, c2, plus='+', minus='-', neutral=' '):
        if c1 == c2 == 0:
            return ('', '', '', '', '')
        else:
            # TODO if coverage format to smallest string or precision
            if c1 is None or c2 is None:
                change = ''
            elif isinstance(c2, str):
                change = F(str(float(c2) - float(c1)))
            else:
                change = str(c2 - c1)
            change_is_zero = change in ('0', '0%', '') or zero_change_regex.fullmatch(change)
            sign = neutral if change_is_zero else plus if change[0] != '-' else minus
            return (
                '%s %s' % (sign, title),
                '%s|' % F(c1),
                '%s|' % F(c2),
                '%s|' % add_plus_sign(change),
                ''
            )

    c = int(isinstance(base.complexity, str)) if base else 0
    # create a spaced table with data
    table = list_to_text_table([
        ('|##', '%s|' % base_title, '%s|' % head_title, '+/-|', '##|'),
        _row('Coverage',
             base.coverage if base else None,
             head.coverage,
             '+', '-'),
        _row('Complexity',
             base.complexity if base else None,
             head.complexity,
             '-+'[c], '+-'[c]),
        _row('Files',
             base.files if base else None,
             head.files,
             ' ', ' '),
        _row('Lines',
             base.lines if base else None,
             head.lines,
             ' ', ' '),
        _row('Branches',
             base.branches if base else None,
             head.branches,
             ' ', ' '),
        _row('Hits',
             base.hits if base else None,
             head.hits,
             '+', '-'),
        _row('Misses',
             base.misses if base else None,
             head.misses,
             '-', '+'),
        _row('Partials',
             base.partials if base else None,
             head.partials,
             '-', '+'),
    ], 3)
    row_w = len(table[0])

    spacer = ['=' * row_w]

    title = '@@%s@@' % '{text:{fill}{align}{width}}'\
            .format(text='Coverage Diff',
                    fill=' ',
                    align='^',
                    width=row_w - 4,
                    strip=True)

    table = (
        [title, table[0]] +
        spacer +
        table[1:3] +  # coverage, complexity
        spacer +
        table[3:6] +  # files, lines, branches
        spacer +
        table[6:9]  # hits, misses, partials
    )

    # no complexity included
    if head.complexity in (None, 0):
        table.pop(4)

    return '\n'.join(filter(lambda row: row.strip(' '), table)).strip('=').split('\n')


def sort_by_importance(changes: Sequence[Change]):
    return sorted(
        changes or [],
        key=lambda c: (float((c.totals or ReportTotals())[5]), c.new, c.deleted)
    )


def ellipsis(text, length, cut_from='left'):
    if cut_from == 'right':
        return (text[:length] + '...') if len(text) > length else text
    elif cut_from is None:
        return (text[:(length/2)] + '...' + text[(length/-2):]) if len(text) > length else text
    else:
        return ('...' + text[len(text)-length:]) if len(text) > length else text


def escape_markdown(value):
    return value.replace('`', '\\`')\
                .replace('*', '\\*')\
                .replace('_', '\\_')
