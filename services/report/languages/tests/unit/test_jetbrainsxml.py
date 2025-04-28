from lxml import etree

from services.report.languages import jetbrainsxml

from . import create_report_builder_session


def test_simple_jetbrainsxml():
    xml = """
<Root ReportType="DetailedXml">
    <File Index="1" Name="/_/src/testhost.x86/UnitTestClient.cs"/>
    <Statement FileIndex="1" Line="1" Column="1" EndLine="1" EndColumn="10" Covered="True" />
</Root>
"""
    report_builder_session = create_report_builder_session()
    jetbrainsxml.from_xml(
        etree.fromstring(xml),
        report_builder_session,
    )
    report = report_builder_session.output_report()

    assert not report.is_empty()
