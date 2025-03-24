from lxml import etree

from services.report.languages import csharp
from test_utils.base import BaseTestCase

from . import create_report_builder_session

xml = b"""<?xml version="1.0" encoding="utf-8"?>
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
"""


class TestCSharp(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore":
                return None
            assert path in ("source",)
            return path

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        csharp.from_xml(etree.fromstring(xml), report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report == {
            "archive": {
                "source": [
                    (1, "2/2", "b", [[0, "2/2", None, None, None]], None, None),
                    (2, 2, None, [[0, 2, None, None, None]], None, None),
                    (3, 0, None, [[0, 0, None, None, None]], None, None),
                    (4, 0, None, [[0, 0, None, None, None]], None, None),
                    (5, 0, None, [[0, 0, None, None, None]], None, None),
                    (6, 1, None, [[0, 1, None, None, None]], None, None),
                    (10, "1/2", "b", [[0, "1/2", ["1:2"], None, None]], None, None),
                ]
            },
            "report": {
                "files": {
                    "source": [
                        0,
                        [0, 7, 3, 3, 1, "42.85714", 2, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ]
                },
                "sessions": {},
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 2,
                "c": "42.85714",
                "d": 0,
                "diff": None,
                "f": 1,
                "h": 3,
                "m": 3,
                "n": 7,
                "p": 1,
                "s": 0,
            },
        }
