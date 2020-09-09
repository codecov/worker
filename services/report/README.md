This is the part of the system responsible for reading the uploaded-reports.

The classes follow the `adapter` design pattern. Each implementation class is responsible for reading one type of file (like one implentation for gcov, one implementation for cobertura etc)

- It is an `adapter` in that it tries to read the existing format provider by a third-party into a standard format we have (it's not a textbook adapter design pattern, but it matches the concept of an adapter)

# Flow

The flow is as follows:

- The `services/report/report_processor.py` function `process_report` is called. It first tries to do a simple parsing of the user-uploaded report, determining if it is a json/xml/plist/txt file (or other high-level format).

- After that is determined, it fetches all the `BaseLanguageProcessor` implementations that can parse that type of file (ie, all implementations that deal with json files).

- With that list, it tries to see which of the implementations can deal with that specific file. For such, it calls `matches_content` on every implementation until the first one that returns True

- On that implementation, it calls the `process`, which takes the uploaded report (a string), a few more parameters, and returns a `Report` with the actual coverage information that such report gives.

# Parsing a new type of file

To implement a new type of file, one must create a new implementation of `BaseLanguageProcessor` present in `services/report/languages/base.py`.

Then one needs to add this to the relevant high-level format in `get_possible_processors_list`. Where it is inside that function determines what exact type object is passed to the `matches_content` and `process` methods. For example, if added to the `xml` section, the implementation can expect a python `etree.ElementTree` object passed to it.