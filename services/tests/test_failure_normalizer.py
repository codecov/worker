import pytest

from services.failure_normalizer import FailureNormalizer

test_string = "abcdefAB-1234-1234-1234-abcdefabcdef test_string 2024-03-10 test 0x44358378 20240312T155215Z 2024-03-12T15:52:15Z  15:52:15Z  2024-03-12T08:52:15-07:00 https://api.codecov.io/commits/list :1:2 :3: :: 0xabcdef1234"


def test_failure_normalizer():
    user_dict = {"TEST": [r"test_string"]}
    f = FailureNormalizer(user_dict)
    s = f.normalize_failure_message(test_string)

    assert (
        s
        == "UUID TEST DATE test HEXNUMBER DATETIME DATETIME  TIME  DATETIME URL LINENO LINENO :: HEXNUMBER"
    )


def test_failure_normalizer_ignore_predefined():
    user_dict = {"TEST": [r"test_string"]}
    f = FailureNormalizer(user_dict, True)
    s = f.normalize_failure_message(test_string)

    assert (
        s
        == "abcdefAB-1234-1234-1234-abcdefabcdef TEST 2024-03-10 test 0x44358378 20240312T155215Z 2024-03-12T15:52:15Z  15:52:15Z  2024-03-12T08:52:15-07:00 https://api.codecov.io/commits/list :1:2 :3: :: 0xabcdef1234"
    )


def test_failure_normalizer_append_predefined():
    user_dict = {"UUID": ["test"]}
    f = FailureNormalizer(user_dict)
    s = f.normalize_failure_message(test_string)

    assert (
        s
        == "UUID UUID_string DATE UUID HEXNUMBER DATETIME DATETIME  TIME  DATETIME URL LINENO LINENO :: HEXNUMBER"
    )


def test_failure_normalizer_overwrite_predefined():
    user_dict = {"UUID": ["test"]}
    f = FailureNormalizer(user_dict, override_predefined=True)
    s = f.normalize_failure_message(test_string)

    assert (
        s
        == "HASH UUID_string DATE UUID HEXNUMBER DATETIME DATETIME  TIME  DATETIME URL LINENO LINENO :: HEXNUMBER"
    )


def test_failure_normalizer_filepath():
    thing_string = "hello/my/name/is/hello/world.js"
    user_dict = {"UUID": ["test"]}
    f = FailureNormalizer(user_dict, override_predefined=True)
    s = f.normalize_failure_message(thing_string)

    assert s == "FILEPATH/is/hello/world.js"


@pytest.mark.parametrize(
    "input,expected",
    [
        (
            """def test_subtract():
&gt;       assert Calculator.subtract(1, 2) == 1.0
E       assert -1 == 1.0
E        +  where -1 = &lt;function Calculator.subtract at 0x7f43b21a3130&gt;(1, 2)
E        +    where &lt;function Calculator.subtract at 0x7f43b21a3130&gt; = Calculator.subtract

app/test_calculator.py:12: AssertionError"
""",
            """def test_subtract():
&gt;       assert Calculator.subtract(NO, NO) == NO
E       assert NO == NO
E        +  where NO = &lt;function Calculator.subtract at HEXNUMBER&gt;(NO, NO)
E        +    where &lt;function Calculator.subtract at HEXNUMBER&gt; = Calculator.subtract

app/test_calculator.pyLINENO AssertionError"
""",
        ),
        (
            """mocker = &lt;pytest_mock.plugin.MockFixture object at 0x6ddc0ae62550&gt;
mock_configuration = &lt;shared.config.ConfigHelper object at 0x54dc9bb7c210&gt;
chain = mocker.patch("tasks.upload.chain")
storage_path = (
    "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
)
message="",
commitid="abf6d4df662c47e32460020ab14abf9303581429",
s = b'\\x592f6b514678496f4333336a54314f71774c744f7934524d4479517778715270446678487459344769777458454a584d632b61633349432f35636c52635659473330782f7a496b7a5053542b426333454d614c5635673d3d'
altchars = None, validate = False
""",
            """mocker = &lt;pytest_mock.plugin.MockFixture object at HEXNUMBER&gt;
mock_configuration = &lt;shared.config.ConfigHelper object at HEXNUMBER&gt;
chain = mocker.patch("tasks.upload.chain")
storage_path = (
    "FILEPATH/testing/UUID/bundle_report.sqlite"
)
message="",
commitid="HASH",
s = b'\\xHASH'
altchars = None, validate = False
""",
        ),
    ],
)
def test_from_random_cases(input, expected):
    test_message = input
    order_to_process = [
        "UUID",
        "DATETIME",
        "DATE",
        "TIME",
        "URL",
        "FILEPATH",
        "LINENO",
        "HASH",
        "HEXNUMBER",
        "NO",
    ]

    normalizer_class = FailureNormalizer(
        dict(), override_predefined=True, key_analysis_order=order_to_process
    )
    s = normalizer_class.normalize_failure_message(test_message)
    assert s == expected
