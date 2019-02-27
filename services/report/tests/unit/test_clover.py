from time import time
from json import dumps
from ddt import data, ddt
import xml.etree.cElementTree as etree

from tests.base import TestCase
from app.tasks.reports.languages import clover


xml = '''<?xml version="1.0" encoding="UTF-8"?>
<coverage generated="%s">
  <project timestamp="1410539625">
    <package name="Codecov">
      <file name="source.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="6" coveredstatements="2" elements="7" coveredelements="2"/>
        </class>
        <line num="5" type="method" name="send" crap="125.96" count="1"/>
        <line complexity="9" visibility="private" signature="findRepeatableAnnotations(AnnotatedElement,Class&lt;A&gt;,Set&lt;Annotation&gt;) : List&lt;A&gt;" num="6" count="2969" type="method"/>

        <line falsecount="0" truecount="1" num="1" type="cond"/>
        <line falsecount="1" truecount="0" num="2" type="cond"/>
        <line falsecount="1" truecount="1" num="3" type="cond"/>
        <line falsecount="0" truecount="0" num="4" type="cond"/>

        <line num="8" type="stmt" count="0"/>
        <line num="11" type="stmt" count="1"/>
        <line num="21" type="stmt" count="0"/>
        <line num="22" type="stmt" count="0"/>
        <line num="23" type="stmt" count="0"/>
        <line num="87" type="stmt" count="0"/>
        <metrics loc="86" ncloc="62" classes="1" methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="6" coveredstatements="2" elements="7" coveredelements="2"/>
      </file>
      <file path="file.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
        <line num="11" type="stmt" count="1"/>
      </file>
      <file name="nolines">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
      </file>
      <file name="ignore">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
        <line num="11" type="stmt" count="1"/>
      </file>
      <file name="vendor/ignoreme.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
      </file>
      <file name="/${1}.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
      </file>
    </package>
    <metrics files="1" loc="86" ncloc="62" classes="1" methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="6" coveredstatements="2" elements="7" coveredelements="2"/>
  </project>
</coverage>
'''

result = {
    'files': {
        'file.php': {
            'l': {
                '11': {
                    'c': 1,
                    's': [[0, 1, None, None, None]]
                }
            }
        },
        'source.php': {
            'l': {
                '11': {
                    'c': 1,
                    's': [[0, 1, None, None, None]]
                },
                '21': {
                    'c': 0,
                    's': [[0, 0, None, None, None]]
                },
                '22': {
                    'c': 0,
                    's': [[0, 0, None, None, None]]
                },
                '23': {
                    'c': 0,
                    's': [[0, 0, None, None, None]]
                },
                '5': {
                    'c': 1,
                    's': [[0, 1, None, None, 0]],
                    't': 'm'
                },
                '6': {
                    'c': 2969,
                    'C': 9,
                    's': [[0, 2969, None, None, 9]],
                    't': 'm'
                },
                '1': {
                    'c': "1/2",
                    's': [[0, "1/2", None, None, None]],
                    't': 'b'
                },
                '2': {
                    'c': "1/2",
                    's': [[0, "1/2", None, None, None]],
                    't': 'b'
                },
                '3': {
                    'c': "2/2",
                    's': [[0, "2/2", None, None, None]],
                    't': 'b'
                },
                '4': {
                    'c': "0/2",
                    's': [[0, "0/2", None, None, None]],
                    't': 'b'
                },
                '8': {
                    'c': 0,
                    's': [[0, 0, None, None, None]]
                }
            }
        }
    }
}


@ddt
class Test(TestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore':
                return None
            assert path in ('source.php', 'file.php', 'nolines')
            return path

        report = clover.from_xml(etree.fromstring(xml % int(time())), fixes, {}, 0, None)
        report = self.v3_to_v2(report)
        print dumps(report, indent=4)
        self.validate.report(report)
        assert result == report

    @data((int(time()) - 172800), '01-01-2014')
    def test_expired(self, date):
        with self.assertRaisesRegexp(AssertionError, 'Clover report expired'):
            clover.from_xml(etree.fromstring(xml % date), None, {}, 0, None)
