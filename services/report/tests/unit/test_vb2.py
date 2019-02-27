from json import dumps
import xml.etree.cElementTree as etree

from tests.base import TestCase
from app.tasks.reports.languages import vb2


txt = '''<?xml version="1.0" standalone="yes"?>
<CoverageDSPriv>
  <Lines>
    <LnStart>258</LnStart>
    <ColStart>0</ColStart>
    <LnEnd>258</LnEnd>
    <ColEnd>0</ColEnd>
    <Coverage>1</Coverage>
    <SourceFileID>1</SourceFileID>
    <LineID>0</LineID>
  </Lines>
  <Lines>
    <LnStart>260</LnStart>
    <ColStart>0</ColStart>
    <LnEnd>260</LnEnd>
    <ColEnd>0</ColEnd>
    <Coverage>0</Coverage>
    <SourceFileID>5</SourceFileID>
    <LineID>1</LineID>
  </Lines>
  <Lines>
    <LnStart>261</LnStart>
    <ColStart>0</ColStart>
    <LnEnd>262</LnEnd>
    <ColEnd>0</ColEnd>
    <Coverage>2</Coverage>
    <SourceFileID>5</SourceFileID>
    <LineID>1</LineID>
  </Lines>
  <SourceFileNames>
    <SourceFileID>1</SourceFileID>
    <SourceFileName>source\\mobius\\cpp\\riosock\\riosock.cpp</SourceFileName>
  </SourceFileNames>
  <SourceFileNames>
    <SourceFileID>5</SourceFileID>
    <SourceFileName>Source\\Mobius\\csharp\\Tests.Common\\RowHelper.cs</SourceFileName>
  </SourceFileNames>
</CoverageDSPriv>
'''

result = {
    "files": {
        "source/mobius/cpp/riosock/riosock.cpp": {
            "l": {
                "258": {
                    "c": True,
                    "s": [[0, True, None, None, None]]
                }
            }
        },
        "Source/Mobius/csharp/Tests.Common/RowHelper.cs": {
            "l": {
                "262": {
                    "c": 0,
                    "s": [[0, 0, None, None, None]]
                },
                "261": {
                    "c": 0,
                    "s": [[0, 0, None, None, None]]
                },
                "260": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                }
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        report = vb2.from_xml(etree.fromstring(txt), str, {}, 0)
        report = self.v3_to_v2(report)
        self.validate.report(report)
        print dumps(report, indent=4)
        assert report == result
