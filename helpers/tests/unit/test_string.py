from helpers.string import EscapeEnum, Replacement, StringEscaper, shorten_file_paths


def test_string_escaper():
    escape_def = [
        Replacement(["1"], "2", EscapeEnum.APPEND),
        Replacement(["3"], "4", EscapeEnum.PREPEND),
        Replacement(["5"], "6", EscapeEnum.REPLACE),
    ]

    escaper = StringEscaper(escape_def)

    assert escaper.replace("123456") == "12243466"


def test_shorten_file_paths():
    string = """Error: expect(received).toBe(expected) // Object.is equality

Expected: 1
Received: -1
    at Object.&lt;anonymous&gt; (/Users/users/dir/repo/demo/calculator/calculator.test.ts:10:31)
    at Promise.then.completed (/Users/users/dir/repo/node_modules/jest-circus/build/utils.js:298:28)
    at Promise.then.completed (build/utils.js:298:28)

"""
    expected = """Error: expect(received).toBe(expected) // Object.is equality

Expected: 1
Received: -1
    at Object.&lt;anonymous&gt; (.../demo/calculator/calculator.test.ts:10:31)
    at Promise.then.completed (.../jest-circus/build/utils.js:298:28)
    at Promise.then.completed (build/utils.js:298:28)

"""
    assert expected == shorten_file_paths(string)
