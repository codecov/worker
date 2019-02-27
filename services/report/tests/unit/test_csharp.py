from json import dumps, loads
import xml.etree.cElementTree as etree

from tests.base import TestCase
from app.tasks.reports.languages import csharp


xml = '''<?xml version="1.0" encoding="utf-8"?>
<CoverageSession xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Summary numSequencePoints="1803" visitedSequencePoints="1647" numBranchPoints="1155" visitedBranchPoints="1048" sequenceCoverage="91.35" branchCoverage="90.74" maxCyclomaticComplexity="32" minCyclomaticComplexity="1" />
  <Modules>
    <Module hash="BE-4C-F7-4D-3C-FA-F7-95-CF-D7-B6-5B-0F-D1-10-B2-85-3C-34-94">
      <Summary numSequencePoints="1803" visitedSequencePoints="1647" numBranchPoints="1155" visitedBranchPoints="1048" sequenceCoverage="91.35" branchCoverage="90.74" maxCyclomaticComplexity="32" minCyclomaticComplexity="1" />
      <FullName></FullName>
      <ModuleName></ModuleName>
      <Files>
        <File uid="1" fullPath="ignore" />
        <File uid="3" fullPath="source" />
      </Files>
      <Classes>
        <Class>
          <Summary numSequencePoints="1733" visitedSequencePoints="1577" numBranchPoints="1123" visitedBranchPoints="1016" sequenceCoverage="91.00" branchCoverage="90.47" maxCyclomaticComplexity="32" minCyclomaticComplexity="1" />
          <FullName></FullName>
          <Methods>
            <Method visited="true" cyclomaticComplexity="1" sequenceCoverage="100" branchCoverage="100" isConstructor="false" isStatic="false" isGetter="true" isSetter="false">
              <FileRef uid="3" />
              <SequencePoints>
                <SequencePoint vc="2" uspid="3" ordinal="0" offset="0" sl="1" sc="2" el="1" ec="9" bec="2" bev="1" fileid="3" />
                <SequencePoint vc="2" uspid="4" ordinal="1" offset="1" sl="2" sc="0" el="2" ec="31" bec="0" bev="0" fileid="3" />
                <SequencePoint vc="0" uspid="5" ordinal="2" offset="15" sl="3" sc="4" el="5" ec="10" bec="0" bev="0" fileid="3" />
                <SequencePoint vc="0" uspid="5" ordinal="2" offset="15" sl="6" sc="4" el="6" ec="10" bec="0" bev="0" fileid="3" />
                <SequencePoint vc="2" uspid="5" ordinal="2" offset="15" sl="10" sc="4" el="6" ec="10" bec="2" bev="1" fileid="3" />
                <SequencePoint />
              </SequencePoints>
              <MethodPoint />
              <MethodPoint vc="0" uspid="2100" ordinal="0" offset="2" sl="3" el="1" bec="0" bev="0" fileid="3" />
              <MethodPoint vc="3" uspid="2100" ordinal="0" offset="2" sl="4" el="1" bec="0" bev="0" fileid="3" />
              <BranchPoints>
                  <BranchPoint vc="3" uspid="2100" offset="0" offsetend="1" sl="10" fileid="3" />
                  <BranchPoint vc="0" uspid="2100" offset="1" offsetend="2" sl="10" fileid="3" />
              </BranchPoints>
            </Method>
          </Methods>
        </Class>
        <Class>
          <Methods>
            <Method visited="true" cyclomaticComplexity="1" sequenceCoverage="100" branchCoverage="100" isConstructor="false" isStatic="false" isGetter="true" isSetter="false">
              <FileRef uid="3" />
              <SequencePoints>
                <SequencePoint vc="1" uspid="5" ordinal="2" offset="15" sl="6" sc="4" el="6" ec="10" bec="0" bev="0" fileid="3" />
                <SequencePoint vc="2" uspid="3" ordinal="0" offset="0" sl="1" sc="2" el="1" ec="9" bec="2" bev="2" fileid="3" />
              </SequencePoints>
            </Method>
            <Method visited="true" cyclomaticComplexity="1" sequenceCoverage="100" branchCoverage="100" isConstructor="false" isStatic="false" isGetter="true" isSetter="false">
              <FileRef uid="1" />
              <SequencePoints>
                <SequencePoint vc="0" uspid="5" ordinal="2" offset="15" sl="3" sc="4" el="5" ec="10" bec="0" bev="0" fileid="1" />
              </SequencePoints>
            </Method>
          </Methods>
        </Class>
      </Classes>
    </Module>
  </Modules>
</CoverageSession>
'''

result = {
    "files": {
        "source": {
            "l": {
                "10": {
                    "c": "1/2",
                    "t": "b",
                    "s": [[0, '1/2', ['1:2'], None, None]]
                    # "p": [[4, 10, 1]]
                },
                "1": {
                    "c": "2/2",
                    "t": "b",
                    "s": [[0, "2/2", None, None, None]]
                },
                "3": {
                    "c": 0,
                    "s": [[0, 0, None, None, None]],
                    "t": "m"
                    # "p": [[4, None, 0]]
                },
                "4": {
                    "c": 3,
                    "s": [[0, 3, None, None, None]],
                    "t": "m"
                    # "p": [[4, None, 0]]
                },
                "2": {
                    "c": 2,
                    "s": [[0, 2, None, None, None]]
                    # "p": [[0, 31, 2]]
                },
                "5": {
                    "c": 0,
                    "s": [[0, 0, None, None, None]]
                    # "p": [[None, 10, 0]]
                },
                "6": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                    # "p": [[4, 10, 1]]
                }
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore':
                return None
            assert path in ('source', )
            return path

        report = csharp.from_xml(etree.fromstring(xml), fixes, {}, 0)
        report = self.v3_to_v2(report)
        print dumps(report, indent=4)
        self.validate.report(report)
        assert loads(dumps(result)) == report
