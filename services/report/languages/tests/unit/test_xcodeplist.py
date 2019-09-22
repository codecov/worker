from pathlib import Path
from tests.base import BaseTestCase
from services.report.languages import xcodeplist

here = Path(__file__)
folder = here.parent

sample_small_plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>quiz</key>
    <dict>
        <key>question</key>
        <array>
            <dict>
                <key>text</key>
                <string>What does 'API' stand for?</string>
                <key>answer</key>
                <string>API stands for Application Programming Interface.</string>
            </dict>
            <dict>
                <key>text</key>
                <string>What's so good about pragmatic REST?</string>
                <key>answer</key>
                <string>It's focused on the api consumer, so it makes it easier for developers to contribute to your app library!</string>
            </dict>
        </array>
    </dict>
</dict>
</plist>"""


class TestXCodePlist(BaseTestCase):

    def readfile(self, filename, if_empty_write=None):
        with open(folder / filename, 'r') as r:
            contents = r.read()

        # codecov: assert not covered start [FUTURE new concept]
        if contents.strip() == '' and if_empty_write:
            with open(folder / filename, 'w+') as r:
                r.write(if_empty_write)
            return if_empty_write
        return contents

    def test_report(self):
        report = xcodeplist.from_xml(self.readfile('xccoverage.xml'), str, {}, 0)
        archive = report.to_archive()
        expect = self.readfile('xcodeplist.txt')
        assert archive == expect

    def test_detect(self):
        processor = xcodeplist.XCodePlistProcessor()
        assert processor.matches_content('content', 'first_line', '/path/to/xccoverage.plist')
        assert processor.matches_content(sample_small_plist, 'first_line', None)
