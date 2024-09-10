import xml.etree.cElementTree as etree

from services.report.languages import csharp
from test_utils.base import BaseTestCase

from . import create_report_builder_session

xml = """<?xml version="1.0" encoding="utf-8"?>
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
                <SequencePoint vc="2" uspid="3" ordinal="0" offset="0" sl="1" sc="2" el="1" ec="9" />
                <SequencePoint vc="2" uspid="4" ordinal="1" offset="1" sl="2" sc="0" el="2" ec="31" />
                <SequencePoint vc="0" uspid="5" ordinal="2" offset="15" sl="3" sc="4" el="5" ec="10" />
                <SequencePoint vc="0" uspid="5" ordinal="2" offset="15" sl="6" sc="4" el="6" ec="10" />
                <SequencePoint vc="2" uspid="5" ordinal="2" offset="15" sl="10" sc="4" el="6" ec="10" />
                <SequencePoint />
              </SequencePoints>
              <MethodPoint />
              <MethodPoint vc="0" uspid="2100" ordinal="0" offset="2" sl="3" el="1" />
              <MethodPoint vc="3" uspid="2100" ordinal="0" offset="2" sl="4" el="1" />
              <MethodPoint vc="3" uspid="2100" ordinal="0" offset="2" />
            </Method>
          </Methods>
        </Class>
        <Class>
          <Methods>
            <Method visited="true" cyclomaticComplexity="1" sequenceCoverage="100" branchCoverage="100" isConstructor="false" isStatic="false" isGetter="true" isSetter="false">
              <FileRef uid="1" />
              <SequencePoints>
                <SequencePoint vc="0" uspid="5" ordinal="2" offset="15" sl="3" sc="4" el="5" ec="10" />
              </SequencePoints>
            </Method>
            <Method visited="false" cyclomaticComplexity="1" nPathComplexity="0" sequenceCoverage="0" branchCoverage="0" isConstructor="true" isStatic="true" isGetter="false" isSetter="false">
              <Summary numSequencePoints="0" visitedSequencePoints="0" numBranchPoints="0" visitedBranchPoints="0" sequenceCoverage="0" branchCoverage="0" maxCyclomaticComplexity="1" minCyclomaticComplexity="1" visitedClasses="0" numClasses="0" visitedMethods="0" numMethods="0" />
              <MetadataToken>100665117</MetadataToken>
              <Name>System.Void Givolio.Tests.BundleConfigUnitTests/&lt;&gt;c::.cctor()</Name>
              <SequencePoints />
              <BranchPoints />
              <MethodPoint vc="0" uspid="93" ordinal="0" offset="0" />
            </Method>
          </Methods>
        </Class>
      </Classes>
    </Module>
  </Modules>
</CoverageSession>
"""


class TestCSharp2(BaseTestCase):
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

        assert processed_report["archive"] == {
            "source": [
                (1, 2, None, [[0, 2, None, None, None]], None, None),
                (2, 2, None, [[0, 2, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
                (4, 0, None, [[0, 0, None, None, None]], None, None),
                (5, 0, None, [[0, 0, None, None, None]], None, None),
                (6, 0, None, [[0, 0, None, None, None]], None, None),
                (10, 2, None, [[0, 2, None, None, None]], None, None),
            ]
        }
