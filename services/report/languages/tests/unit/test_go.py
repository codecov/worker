import pytest
from shared.reports.types import ReportTotals

from helpers.exceptions import CorruptRawReportError
from services.report.languages import go
from test_utils.base import BaseTestCase

from . import create_report_builder_session

txt = b"""mode: atomic
source:1.1,1.10 1 1
source:7.14,9.10 1 1
source:11.26,13.2 1 1
ignore:15.19,17.2 1 1
ignore:
source:15.19,17.2 1 0

source:15.19,17.2 1 1
"""

huge_txt = b"""mode: count
path/file.go:18.95,22.51 3 0
path/file.go:28.2,29.61 2 0
path/file.go:37.2,37.15 1 0
path/file.go:22.51,24.3 1 3
path/file.go:24.8,26.3 1 0
path/file.go:29.61,31.3 1 0
path/file.go:31.8,32.24 1 0
path/file.go:32.24,34.4 1 0
path/file.go:41.75,45.45 3 0
path/file.go:51.2,52.55 2 0
path/file.go:60.2,60.15 1 0
path/file.go:45.45,47.3 1 0
path/file.go:47.8,49.3 1 0
path/file.go:52.55,54.3 1 0
path/file.go:54.8,55.24 1 0
path/file.go:55.24,57.4 1 0
path/file.go:64.74,68.45 3 0
path/file.go:74.2,75.55 2 0
path/file.go:83.2,83.15 1 0
path/file.go:68.45,70.3 1 0
path/file.go:70.8,72.3 1 0
path/file.go:75.55,77.3 1 0
path/file.go:77.8,78.24 1 0
path/file.go:78.24,80.4 1 1
path/file.go:87.87,91.49 3 1
path/file.go:97.2,98.59 2 0
path/file.go:106.2,106.15 1 0
path/file.go:91.49,93.3 1 0
path/file.go:93.8,95.3 1 0
path/file.go:98.59,100.3 1 0
path/file.go:100.8,101.24 1 0
path/file.go:101.24,103.4 1 0
path/file.go:110.70,114.55 3 0
path/file.go:122.2,122.11 1 0
path/file.go:114.55,116.3 1 0
path/file.go:116.8,117.24 1 0
path/file.go:117.24,119.4 1 0
path/file.go:126.36,128.2 1 0
path/file.go:131.68,135.57 3 0
path/file.go:143.2,144.61 2 0
path/file.go:152.2,152.15 1 0
path/file.go:135.57,137.3 1 0
path/file.go:137.8,138.24 1 0
path/file.go:138.24,140.4 1 0
path/file.go:144.61,146.3 1 0
path/file.go:146.8,147.24 1 0
path/file.go:147.24,149.4 1 0
path/file.go:156.126,160.81 3 0
path/file.go:166.2,167.91 2 0
path/file.go:175.2,175.15 1 0
path/file.go:160.81,162.3 1 0
path/file.go:162.8,164.3 1 0
path/file.go:167.91,169.3 1 0
path/file.go:169.8,170.24 1 0
path/file.go:170.24,172.4 1 0
path/file.go:179.64,183.53 3 0
path/file.go:191.2,192.55 2 0
path/file.go:200.2,200.15 1 0
path/file.go:183.53,185.3 1 0
path/file.go:185.8,186.24 1 0
path/file.go:186.24,188.4 1 0
path/file.go:192.55,194.3 1 0
path/file.go:194.8,195.24 1 0
path/file.go:195.24,197.4 1 0
path/file.go:204.112,208.73 3 0
path/file.go:216.2,217.66 2 0
path/file.go:225.2,225.15 1 0
path/file.go:208.73,210.3 1 0
path/file.go:210.8,211.24 1 0
path/file.go:211.24,213.4 1 0
path/file.go:217.66,219.3 1 0
path/file.go:219.8,220.24 1 0
path/file.go:220.24,222.4 1 0
path/file.go:229.89,233.61 3 0
path/file.go:241.2,242.63 2 0
path/file.go:250.2,250.15 1 0
path/file.go:233.61,235.3 1 0
path/file.go:235.8,236.24 1 0
path/file.go:236.24,238.4 1 0
path/file.go:242.63,244.3 1 0
path/file.go:244.8,245.24 1 0
path/file.go:245.24,247.4 1 0
path/file.go:254.82,258.53 3 0
path/file.go:266.2,267.55 2 0
path/file.go:275.2,275.15 1 0
path/file.go:258.53,260.3 1 0
path/file.go:260.8,261.24 1 0
path/file.go:261.24,263.4 1 0
path/file.go:267.55,269.3 1 0
path/file.go:269.8,270.24 1 0
path/file.go:270.24,272.4 1 0
path/file.go:279.107,283.61 3 0
path/file.go:291.2,292.63 2 1
path/file.go:300.2,300.15 1 0"""


class TestGo(BaseTestCase):
    def test_report(self):
        def fixes(path):
            return None if "ignore" in path else path

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        go.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "source": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (7, 1, None, [[0, 1, None, None, None]], None, None),
                (8, 1, None, [[0, 1, None, None, None]], None, None),
                (9, 1, None, [[0, 1, None, None, None]], None, None),
                (11, 1, None, [[0, 1, None, None, None]], None, None),
                (12, 1, None, [[0, 1, None, None, None]], None, None),
                (15, 1, None, [[0, 1, None, None, None]], None, None),
                (16, 1, None, [[0, 1, None, None, None]], None, None),
            ]
        }

        assert expected_result_archive == processed_report["archive"]

    def test_huge_report(self):
        def fixes(path):
            return None if "ignore" in path else path

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        go.from_txt(huge_txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"] == {
            "path/file.go": [
                (18, 0, None, [[0, 0, None, None, None]], None, None),
                (19, 0, None, [[0, 0, None, None, None]], None, None),
                (20, 0, None, [[0, 0, None, None, None]], None, None),
                (21, 0, None, [[0, 0, None, None, None]], None, None),
                (22, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                (23, 3, None, [[0, 3, None, None, None]], None, None),
                (24, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                (25, 0, None, [[0, 0, None, None, None]], None, None),
                (26, 0, None, [[0, 0, None, None, None]], None, None),
                (28, 0, None, [[0, 0, None, None, None]], None, None),
                (29, 0, None, [[0, 0, None, None, None]], None, None),
                (30, 0, None, [[0, 0, None, None, None]], None, None),
                (31, 0, None, [[0, 0, None, None, None]], None, None),
                (32, 0, None, [[0, 0, None, None, None]], None, None),
                (33, 0, None, [[0, 0, None, None, None]], None, None),
                (34, 0, None, [[0, 0, None, None, None]], None, None),
                (37, 0, None, [[0, 0, None, None, None]], None, None),
                (41, 0, None, [[0, 0, None, None, None]], None, None),
                (42, 0, None, [[0, 0, None, None, None]], None, None),
                (43, 0, None, [[0, 0, None, None, None]], None, None),
                (44, 0, None, [[0, 0, None, None, None]], None, None),
                (45, 0, None, [[0, 0, None, None, None]], None, None),
                (46, 0, None, [[0, 0, None, None, None]], None, None),
                (47, 0, None, [[0, 0, None, None, None]], None, None),
                (48, 0, None, [[0, 0, None, None, None]], None, None),
                (49, 0, None, [[0, 0, None, None, None]], None, None),
                (51, 0, None, [[0, 0, None, None, None]], None, None),
                (52, 0, None, [[0, 0, None, None, None]], None, None),
                (53, 0, None, [[0, 0, None, None, None]], None, None),
                (54, 0, None, [[0, 0, None, None, None]], None, None),
                (55, 0, None, [[0, 0, None, None, None]], None, None),
                (56, 0, None, [[0, 0, None, None, None]], None, None),
                (57, 0, None, [[0, 0, None, None, None]], None, None),
                (60, 0, None, [[0, 0, None, None, None]], None, None),
                (64, 0, None, [[0, 0, None, None, None]], None, None),
                (65, 0, None, [[0, 0, None, None, None]], None, None),
                (66, 0, None, [[0, 0, None, None, None]], None, None),
                (67, 0, None, [[0, 0, None, None, None]], None, None),
                (68, 0, None, [[0, 0, None, None, None]], None, None),
                (69, 0, None, [[0, 0, None, None, None]], None, None),
                (70, 0, None, [[0, 0, None, None, None]], None, None),
                (71, 0, None, [[0, 0, None, None, None]], None, None),
                (72, 0, None, [[0, 0, None, None, None]], None, None),
                (74, 0, None, [[0, 0, None, None, None]], None, None),
                (75, 0, None, [[0, 0, None, None, None]], None, None),
                (76, 0, None, [[0, 0, None, None, None]], None, None),
                (77, 0, None, [[0, 0, None, None, None]], None, None),
                (78, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                (79, 1, None, [[0, 1, None, None, None]], None, None),
                (80, 1, None, [[0, 1, None, None, None]], None, None),
                (83, 0, None, [[0, 0, None, None, None]], None, None),
                (87, 1, None, [[0, 1, None, None, None]], None, None),
                (88, 1, None, [[0, 1, None, None, None]], None, None),
                (89, 1, None, [[0, 1, None, None, None]], None, None),
                (90, 1, None, [[0, 1, None, None, None]], None, None),
                (91, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                (92, 0, None, [[0, 0, None, None, None]], None, None),
                (93, 0, None, [[0, 0, None, None, None]], None, None),
                (94, 0, None, [[0, 0, None, None, None]], None, None),
                (95, 0, None, [[0, 0, None, None, None]], None, None),
                (97, 0, None, [[0, 0, None, None, None]], None, None),
                (98, 0, None, [[0, 0, None, None, None]], None, None),
                (99, 0, None, [[0, 0, None, None, None]], None, None),
                (100, 0, None, [[0, 0, None, None, None]], None, None),
                (101, 0, None, [[0, 0, None, None, None]], None, None),
                (102, 0, None, [[0, 0, None, None, None]], None, None),
                (103, 0, None, [[0, 0, None, None, None]], None, None),
                (106, 0, None, [[0, 0, None, None, None]], None, None),
                (110, 0, None, [[0, 0, None, None, None]], None, None),
                (111, 0, None, [[0, 0, None, None, None]], None, None),
                (112, 0, None, [[0, 0, None, None, None]], None, None),
                (113, 0, None, [[0, 0, None, None, None]], None, None),
                (114, 0, None, [[0, 0, None, None, None]], None, None),
                (115, 0, None, [[0, 0, None, None, None]], None, None),
                (116, 0, None, [[0, 0, None, None, None]], None, None),
                (117, 0, None, [[0, 0, None, None, None]], None, None),
                (118, 0, None, [[0, 0, None, None, None]], None, None),
                (119, 0, None, [[0, 0, None, None, None]], None, None),
                (122, 0, None, [[0, 0, None, None, None]], None, None),
                (126, 0, None, [[0, 0, None, None, None]], None, None),
                (127, 0, None, [[0, 0, None, None, None]], None, None),
                (131, 0, None, [[0, 0, None, None, None]], None, None),
                (132, 0, None, [[0, 0, None, None, None]], None, None),
                (133, 0, None, [[0, 0, None, None, None]], None, None),
                (134, 0, None, [[0, 0, None, None, None]], None, None),
                (135, 0, None, [[0, 0, None, None, None]], None, None),
                (136, 0, None, [[0, 0, None, None, None]], None, None),
                (137, 0, None, [[0, 0, None, None, None]], None, None),
                (138, 0, None, [[0, 0, None, None, None]], None, None),
                (139, 0, None, [[0, 0, None, None, None]], None, None),
                (140, 0, None, [[0, 0, None, None, None]], None, None),
                (143, 0, None, [[0, 0, None, None, None]], None, None),
                (144, 0, None, [[0, 0, None, None, None]], None, None),
                (145, 0, None, [[0, 0, None, None, None]], None, None),
                (146, 0, None, [[0, 0, None, None, None]], None, None),
                (147, 0, None, [[0, 0, None, None, None]], None, None),
                (148, 0, None, [[0, 0, None, None, None]], None, None),
                (149, 0, None, [[0, 0, None, None, None]], None, None),
                (152, 0, None, [[0, 0, None, None, None]], None, None),
                (156, 0, None, [[0, 0, None, None, None]], None, None),
                (157, 0, None, [[0, 0, None, None, None]], None, None),
                (158, 0, None, [[0, 0, None, None, None]], None, None),
                (159, 0, None, [[0, 0, None, None, None]], None, None),
                (160, 0, None, [[0, 0, None, None, None]], None, None),
                (161, 0, None, [[0, 0, None, None, None]], None, None),
                (162, 0, None, [[0, 0, None, None, None]], None, None),
                (163, 0, None, [[0, 0, None, None, None]], None, None),
                (164, 0, None, [[0, 0, None, None, None]], None, None),
                (166, 0, None, [[0, 0, None, None, None]], None, None),
                (167, 0, None, [[0, 0, None, None, None]], None, None),
                (168, 0, None, [[0, 0, None, None, None]], None, None),
                (169, 0, None, [[0, 0, None, None, None]], None, None),
                (170, 0, None, [[0, 0, None, None, None]], None, None),
                (171, 0, None, [[0, 0, None, None, None]], None, None),
                (172, 0, None, [[0, 0, None, None, None]], None, None),
                (175, 0, None, [[0, 0, None, None, None]], None, None),
                (179, 0, None, [[0, 0, None, None, None]], None, None),
                (180, 0, None, [[0, 0, None, None, None]], None, None),
                (181, 0, None, [[0, 0, None, None, None]], None, None),
                (182, 0, None, [[0, 0, None, None, None]], None, None),
                (183, 0, None, [[0, 0, None, None, None]], None, None),
                (184, 0, None, [[0, 0, None, None, None]], None, None),
                (185, 0, None, [[0, 0, None, None, None]], None, None),
                (186, 0, None, [[0, 0, None, None, None]], None, None),
                (187, 0, None, [[0, 0, None, None, None]], None, None),
                (188, 0, None, [[0, 0, None, None, None]], None, None),
                (191, 0, None, [[0, 0, None, None, None]], None, None),
                (192, 0, None, [[0, 0, None, None, None]], None, None),
                (193, 0, None, [[0, 0, None, None, None]], None, None),
                (194, 0, None, [[0, 0, None, None, None]], None, None),
                (195, 0, None, [[0, 0, None, None, None]], None, None),
                (196, 0, None, [[0, 0, None, None, None]], None, None),
                (197, 0, None, [[0, 0, None, None, None]], None, None),
                (200, 0, None, [[0, 0, None, None, None]], None, None),
                (204, 0, None, [[0, 0, None, None, None]], None, None),
                (205, 0, None, [[0, 0, None, None, None]], None, None),
                (206, 0, None, [[0, 0, None, None, None]], None, None),
                (207, 0, None, [[0, 0, None, None, None]], None, None),
                (208, 0, None, [[0, 0, None, None, None]], None, None),
                (209, 0, None, [[0, 0, None, None, None]], None, None),
                (210, 0, None, [[0, 0, None, None, None]], None, None),
                (211, 0, None, [[0, 0, None, None, None]], None, None),
                (212, 0, None, [[0, 0, None, None, None]], None, None),
                (213, 0, None, [[0, 0, None, None, None]], None, None),
                (216, 0, None, [[0, 0, None, None, None]], None, None),
                (217, 0, None, [[0, 0, None, None, None]], None, None),
                (218, 0, None, [[0, 0, None, None, None]], None, None),
                (219, 0, None, [[0, 0, None, None, None]], None, None),
                (220, 0, None, [[0, 0, None, None, None]], None, None),
                (221, 0, None, [[0, 0, None, None, None]], None, None),
                (222, 0, None, [[0, 0, None, None, None]], None, None),
                (225, 0, None, [[0, 0, None, None, None]], None, None),
                (229, 0, None, [[0, 0, None, None, None]], None, None),
                (230, 0, None, [[0, 0, None, None, None]], None, None),
                (231, 0, None, [[0, 0, None, None, None]], None, None),
                (232, 0, None, [[0, 0, None, None, None]], None, None),
                (233, 0, None, [[0, 0, None, None, None]], None, None),
                (234, 0, None, [[0, 0, None, None, None]], None, None),
                (235, 0, None, [[0, 0, None, None, None]], None, None),
                (236, 0, None, [[0, 0, None, None, None]], None, None),
                (237, 0, None, [[0, 0, None, None, None]], None, None),
                (238, 0, None, [[0, 0, None, None, None]], None, None),
                (241, 0, None, [[0, 0, None, None, None]], None, None),
                (242, 0, None, [[0, 0, None, None, None]], None, None),
                (243, 0, None, [[0, 0, None, None, None]], None, None),
                (244, 0, None, [[0, 0, None, None, None]], None, None),
                (245, 0, None, [[0, 0, None, None, None]], None, None),
                (246, 0, None, [[0, 0, None, None, None]], None, None),
                (247, 0, None, [[0, 0, None, None, None]], None, None),
                (250, 0, None, [[0, 0, None, None, None]], None, None),
                (254, 0, None, [[0, 0, None, None, None]], None, None),
                (255, 0, None, [[0, 0, None, None, None]], None, None),
                (256, 0, None, [[0, 0, None, None, None]], None, None),
                (257, 0, None, [[0, 0, None, None, None]], None, None),
                (258, 0, None, [[0, 0, None, None, None]], None, None),
                (259, 0, None, [[0, 0, None, None, None]], None, None),
                (260, 0, None, [[0, 0, None, None, None]], None, None),
                (261, 0, None, [[0, 0, None, None, None]], None, None),
                (262, 0, None, [[0, 0, None, None, None]], None, None),
                (263, 0, None, [[0, 0, None, None, None]], None, None),
                (266, 0, None, [[0, 0, None, None, None]], None, None),
                (267, 0, None, [[0, 0, None, None, None]], None, None),
                (268, 0, None, [[0, 0, None, None, None]], None, None),
                (269, 0, None, [[0, 0, None, None, None]], None, None),
                (270, 0, None, [[0, 0, None, None, None]], None, None),
                (271, 0, None, [[0, 0, None, None, None]], None, None),
                (272, 0, None, [[0, 0, None, None, None]], None, None),
                (275, 0, None, [[0, 0, None, None, None]], None, None),
                (279, 0, None, [[0, 0, None, None, None]], None, None),
                (280, 0, None, [[0, 0, None, None, None]], None, None),
                (281, 0, None, [[0, 0, None, None, None]], None, None),
                (282, 0, None, [[0, 0, None, None, None]], None, None),
                (283, 0, None, [[0, 0, None, None, None]], None, None),
                (291, 1, None, [[0, 1, None, None, None]], None, None),
                (292, 1, None, [[0, 1, None, None, None]], None, None),
                (300, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }

        assert report.totals == ReportTotals(
            files=1,
            lines=196,
            hits=9,
            misses=183,
            partials=4,
            coverage="4.59184",
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )

    def test_huge_report_partials_as_hits(self):
        def fixes(path):
            return None if "ignore" in path else path

        report_builder_session = create_report_builder_session(
            path_fixer=fixes,
            current_yaml={"parsers": {"go": {"partials_as_hits": True}}},
        )
        go.from_txt(huge_txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"] == {
            "path/file.go": [
                (18, 0, None, [[0, 0, None, None, None]], None, None),
                (19, 0, None, [[0, 0, None, None, None]], None, None),
                (20, 0, None, [[0, 0, None, None, None]], None, None),
                (21, 0, None, [[0, 0, None, None, None]], None, None),
                (22, 1, None, [[0, 1, None, None, None]], None, None),
                (23, 3, None, [[0, 3, None, None, None]], None, None),
                (24, 1, None, [[0, 1, None, None, None]], None, None),
                (25, 0, None, [[0, 0, None, None, None]], None, None),
                (26, 0, None, [[0, 0, None, None, None]], None, None),
                (28, 0, None, [[0, 0, None, None, None]], None, None),
                (29, 0, None, [[0, 0, None, None, None]], None, None),
                (30, 0, None, [[0, 0, None, None, None]], None, None),
                (31, 0, None, [[0, 0, None, None, None]], None, None),
                (32, 0, None, [[0, 0, None, None, None]], None, None),
                (33, 0, None, [[0, 0, None, None, None]], None, None),
                (34, 0, None, [[0, 0, None, None, None]], None, None),
                (37, 0, None, [[0, 0, None, None, None]], None, None),
                (41, 0, None, [[0, 0, None, None, None]], None, None),
                (42, 0, None, [[0, 0, None, None, None]], None, None),
                (43, 0, None, [[0, 0, None, None, None]], None, None),
                (44, 0, None, [[0, 0, None, None, None]], None, None),
                (45, 0, None, [[0, 0, None, None, None]], None, None),
                (46, 0, None, [[0, 0, None, None, None]], None, None),
                (47, 0, None, [[0, 0, None, None, None]], None, None),
                (48, 0, None, [[0, 0, None, None, None]], None, None),
                (49, 0, None, [[0, 0, None, None, None]], None, None),
                (51, 0, None, [[0, 0, None, None, None]], None, None),
                (52, 0, None, [[0, 0, None, None, None]], None, None),
                (53, 0, None, [[0, 0, None, None, None]], None, None),
                (54, 0, None, [[0, 0, None, None, None]], None, None),
                (55, 0, None, [[0, 0, None, None, None]], None, None),
                (56, 0, None, [[0, 0, None, None, None]], None, None),
                (57, 0, None, [[0, 0, None, None, None]], None, None),
                (60, 0, None, [[0, 0, None, None, None]], None, None),
                (64, 0, None, [[0, 0, None, None, None]], None, None),
                (65, 0, None, [[0, 0, None, None, None]], None, None),
                (66, 0, None, [[0, 0, None, None, None]], None, None),
                (67, 0, None, [[0, 0, None, None, None]], None, None),
                (68, 0, None, [[0, 0, None, None, None]], None, None),
                (69, 0, None, [[0, 0, None, None, None]], None, None),
                (70, 0, None, [[0, 0, None, None, None]], None, None),
                (71, 0, None, [[0, 0, None, None, None]], None, None),
                (72, 0, None, [[0, 0, None, None, None]], None, None),
                (74, 0, None, [[0, 0, None, None, None]], None, None),
                (75, 0, None, [[0, 0, None, None, None]], None, None),
                (76, 0, None, [[0, 0, None, None, None]], None, None),
                (77, 0, None, [[0, 0, None, None, None]], None, None),
                (78, 1, None, [[0, 1, None, None, None]], None, None),
                (79, 1, None, [[0, 1, None, None, None]], None, None),
                (80, 1, None, [[0, 1, None, None, None]], None, None),
                (83, 0, None, [[0, 0, None, None, None]], None, None),
                (87, 1, None, [[0, 1, None, None, None]], None, None),
                (88, 1, None, [[0, 1, None, None, None]], None, None),
                (89, 1, None, [[0, 1, None, None, None]], None, None),
                (90, 1, None, [[0, 1, None, None, None]], None, None),
                (91, 1, None, [[0, 1, None, None, None]], None, None),
                (92, 0, None, [[0, 0, None, None, None]], None, None),
                (93, 0, None, [[0, 0, None, None, None]], None, None),
                (94, 0, None, [[0, 0, None, None, None]], None, None),
                (95, 0, None, [[0, 0, None, None, None]], None, None),
                (97, 0, None, [[0, 0, None, None, None]], None, None),
                (98, 0, None, [[0, 0, None, None, None]], None, None),
                (99, 0, None, [[0, 0, None, None, None]], None, None),
                (100, 0, None, [[0, 0, None, None, None]], None, None),
                (101, 0, None, [[0, 0, None, None, None]], None, None),
                (102, 0, None, [[0, 0, None, None, None]], None, None),
                (103, 0, None, [[0, 0, None, None, None]], None, None),
                (106, 0, None, [[0, 0, None, None, None]], None, None),
                (110, 0, None, [[0, 0, None, None, None]], None, None),
                (111, 0, None, [[0, 0, None, None, None]], None, None),
                (112, 0, None, [[0, 0, None, None, None]], None, None),
                (113, 0, None, [[0, 0, None, None, None]], None, None),
                (114, 0, None, [[0, 0, None, None, None]], None, None),
                (115, 0, None, [[0, 0, None, None, None]], None, None),
                (116, 0, None, [[0, 0, None, None, None]], None, None),
                (117, 0, None, [[0, 0, None, None, None]], None, None),
                (118, 0, None, [[0, 0, None, None, None]], None, None),
                (119, 0, None, [[0, 0, None, None, None]], None, None),
                (122, 0, None, [[0, 0, None, None, None]], None, None),
                (126, 0, None, [[0, 0, None, None, None]], None, None),
                (127, 0, None, [[0, 0, None, None, None]], None, None),
                (131, 0, None, [[0, 0, None, None, None]], None, None),
                (132, 0, None, [[0, 0, None, None, None]], None, None),
                (133, 0, None, [[0, 0, None, None, None]], None, None),
                (134, 0, None, [[0, 0, None, None, None]], None, None),
                (135, 0, None, [[0, 0, None, None, None]], None, None),
                (136, 0, None, [[0, 0, None, None, None]], None, None),
                (137, 0, None, [[0, 0, None, None, None]], None, None),
                (138, 0, None, [[0, 0, None, None, None]], None, None),
                (139, 0, None, [[0, 0, None, None, None]], None, None),
                (140, 0, None, [[0, 0, None, None, None]], None, None),
                (143, 0, None, [[0, 0, None, None, None]], None, None),
                (144, 0, None, [[0, 0, None, None, None]], None, None),
                (145, 0, None, [[0, 0, None, None, None]], None, None),
                (146, 0, None, [[0, 0, None, None, None]], None, None),
                (147, 0, None, [[0, 0, None, None, None]], None, None),
                (148, 0, None, [[0, 0, None, None, None]], None, None),
                (149, 0, None, [[0, 0, None, None, None]], None, None),
                (152, 0, None, [[0, 0, None, None, None]], None, None),
                (156, 0, None, [[0, 0, None, None, None]], None, None),
                (157, 0, None, [[0, 0, None, None, None]], None, None),
                (158, 0, None, [[0, 0, None, None, None]], None, None),
                (159, 0, None, [[0, 0, None, None, None]], None, None),
                (160, 0, None, [[0, 0, None, None, None]], None, None),
                (161, 0, None, [[0, 0, None, None, None]], None, None),
                (162, 0, None, [[0, 0, None, None, None]], None, None),
                (163, 0, None, [[0, 0, None, None, None]], None, None),
                (164, 0, None, [[0, 0, None, None, None]], None, None),
                (166, 0, None, [[0, 0, None, None, None]], None, None),
                (167, 0, None, [[0, 0, None, None, None]], None, None),
                (168, 0, None, [[0, 0, None, None, None]], None, None),
                (169, 0, None, [[0, 0, None, None, None]], None, None),
                (170, 0, None, [[0, 0, None, None, None]], None, None),
                (171, 0, None, [[0, 0, None, None, None]], None, None),
                (172, 0, None, [[0, 0, None, None, None]], None, None),
                (175, 0, None, [[0, 0, None, None, None]], None, None),
                (179, 0, None, [[0, 0, None, None, None]], None, None),
                (180, 0, None, [[0, 0, None, None, None]], None, None),
                (181, 0, None, [[0, 0, None, None, None]], None, None),
                (182, 0, None, [[0, 0, None, None, None]], None, None),
                (183, 0, None, [[0, 0, None, None, None]], None, None),
                (184, 0, None, [[0, 0, None, None, None]], None, None),
                (185, 0, None, [[0, 0, None, None, None]], None, None),
                (186, 0, None, [[0, 0, None, None, None]], None, None),
                (187, 0, None, [[0, 0, None, None, None]], None, None),
                (188, 0, None, [[0, 0, None, None, None]], None, None),
                (191, 0, None, [[0, 0, None, None, None]], None, None),
                (192, 0, None, [[0, 0, None, None, None]], None, None),
                (193, 0, None, [[0, 0, None, None, None]], None, None),
                (194, 0, None, [[0, 0, None, None, None]], None, None),
                (195, 0, None, [[0, 0, None, None, None]], None, None),
                (196, 0, None, [[0, 0, None, None, None]], None, None),
                (197, 0, None, [[0, 0, None, None, None]], None, None),
                (200, 0, None, [[0, 0, None, None, None]], None, None),
                (204, 0, None, [[0, 0, None, None, None]], None, None),
                (205, 0, None, [[0, 0, None, None, None]], None, None),
                (206, 0, None, [[0, 0, None, None, None]], None, None),
                (207, 0, None, [[0, 0, None, None, None]], None, None),
                (208, 0, None, [[0, 0, None, None, None]], None, None),
                (209, 0, None, [[0, 0, None, None, None]], None, None),
                (210, 0, None, [[0, 0, None, None, None]], None, None),
                (211, 0, None, [[0, 0, None, None, None]], None, None),
                (212, 0, None, [[0, 0, None, None, None]], None, None),
                (213, 0, None, [[0, 0, None, None, None]], None, None),
                (216, 0, None, [[0, 0, None, None, None]], None, None),
                (217, 0, None, [[0, 0, None, None, None]], None, None),
                (218, 0, None, [[0, 0, None, None, None]], None, None),
                (219, 0, None, [[0, 0, None, None, None]], None, None),
                (220, 0, None, [[0, 0, None, None, None]], None, None),
                (221, 0, None, [[0, 0, None, None, None]], None, None),
                (222, 0, None, [[0, 0, None, None, None]], None, None),
                (225, 0, None, [[0, 0, None, None, None]], None, None),
                (229, 0, None, [[0, 0, None, None, None]], None, None),
                (230, 0, None, [[0, 0, None, None, None]], None, None),
                (231, 0, None, [[0, 0, None, None, None]], None, None),
                (232, 0, None, [[0, 0, None, None, None]], None, None),
                (233, 0, None, [[0, 0, None, None, None]], None, None),
                (234, 0, None, [[0, 0, None, None, None]], None, None),
                (235, 0, None, [[0, 0, None, None, None]], None, None),
                (236, 0, None, [[0, 0, None, None, None]], None, None),
                (237, 0, None, [[0, 0, None, None, None]], None, None),
                (238, 0, None, [[0, 0, None, None, None]], None, None),
                (241, 0, None, [[0, 0, None, None, None]], None, None),
                (242, 0, None, [[0, 0, None, None, None]], None, None),
                (243, 0, None, [[0, 0, None, None, None]], None, None),
                (244, 0, None, [[0, 0, None, None, None]], None, None),
                (245, 0, None, [[0, 0, None, None, None]], None, None),
                (246, 0, None, [[0, 0, None, None, None]], None, None),
                (247, 0, None, [[0, 0, None, None, None]], None, None),
                (250, 0, None, [[0, 0, None, None, None]], None, None),
                (254, 0, None, [[0, 0, None, None, None]], None, None),
                (255, 0, None, [[0, 0, None, None, None]], None, None),
                (256, 0, None, [[0, 0, None, None, None]], None, None),
                (257, 0, None, [[0, 0, None, None, None]], None, None),
                (258, 0, None, [[0, 0, None, None, None]], None, None),
                (259, 0, None, [[0, 0, None, None, None]], None, None),
                (260, 0, None, [[0, 0, None, None, None]], None, None),
                (261, 0, None, [[0, 0, None, None, None]], None, None),
                (262, 0, None, [[0, 0, None, None, None]], None, None),
                (263, 0, None, [[0, 0, None, None, None]], None, None),
                (266, 0, None, [[0, 0, None, None, None]], None, None),
                (267, 0, None, [[0, 0, None, None, None]], None, None),
                (268, 0, None, [[0, 0, None, None, None]], None, None),
                (269, 0, None, [[0, 0, None, None, None]], None, None),
                (270, 0, None, [[0, 0, None, None, None]], None, None),
                (271, 0, None, [[0, 0, None, None, None]], None, None),
                (272, 0, None, [[0, 0, None, None, None]], None, None),
                (275, 0, None, [[0, 0, None, None, None]], None, None),
                (279, 0, None, [[0, 0, None, None, None]], None, None),
                (280, 0, None, [[0, 0, None, None, None]], None, None),
                (281, 0, None, [[0, 0, None, None, None]], None, None),
                (282, 0, None, [[0, 0, None, None, None]], None, None),
                (283, 0, None, [[0, 0, None, None, None]], None, None),
                (291, 1, None, [[0, 1, None, None, None]], None, None),
                (292, 1, None, [[0, 1, None, None, None]], None, None),
                (300, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }

        assert report.totals == ReportTotals(
            files=1,
            lines=196,
            hits=13,
            misses=183,
            partials=0,
            coverage="6.63265",
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )

    def test_combine_partials(self):
        assert go.combine_partials([(1, 5, 1), (9, 12, 0), (5, 7, 1), (8, 9, 0)]) == [
            [1, 7, 1],
            [8, 12, 0],
        ]  # same combine
        assert go.combine_partials([(1, 2, 0), (4, 10, 1)]) == [
            [1, 2, 0],
            [4, 10, 1],
        ]  # outer == same
        assert go.combine_partials([[1, None, 1]]) == [[1, None, 1]]  # single == same
        assert go.combine_partials([(2, 24, 1), (24, None, 0)]) == [
            [2, 24, 1],
            [24, None, 0],
        ]
        assert go.combine_partials([(2, 2, 1), (2, 2, 0)]) is None
        assert go.combine_partials([(0, None, 28), (0, None, 0)]) == [[0, None, 28]]
        assert go.combine_partials([(2, 35, 1), (35, None, 1)]) == [[2, None, 1]]
        assert go.combine_partials([(2, 35, "1/2"), (35, None, "1/2")]) == [
            [2, None, "1/2"]
        ]
        assert go.combine_partials([(2, 35, "1/2"), (35, None, "2/2")]) == [
            [2, 35, "1/2"],
            [35, None, "2/2"],
        ]
        assert go.combine_partials([(None, 2, 1), (1, 5, 1)]) == [[0, 5, 1]]
        assert go.combine_partials([(None, 1, 1), (1, 2, 0), (2, 3, 1)]) == [
            [1, 2, 0],
            [2, 3, 1],
        ]
        assert go.combine_partials([(1, None, 1), (2, None, 0)]) == [
            [1, None, 1]
        ]  # hit&miss overlay == hit
        assert go.combine_partials([(1, 5, 0), (4, 10, 1)]) == [
            [1, 4, 0],
            [4, 10, 1],
        ]  # intersect
        assert go.combine_partials(10 * [(1, 5, 0)] + 10 * [(4, 10, 1)]) == [
            [1, 4, 0],
            [4, 10, 1],
        ]  # intersect
        assert go.combine_partials([(1, 10, 0), (4, 6, 1)]) == [
            [1, 4, 0],
            [4, 6, 1],
            [6, 10, 0],
        ]  # inner overlay

    def test_report_line_missing_number_of_statements_count_new_line(self):
        def fixes(path):
            return None if "ignore" in path else path

        line = b"path/file.go:242.63,244.3path/file.go:242.63,244.3 1 0"
        report_builder_session = create_report_builder_session(path_fixer=fixes)

        with pytest.raises(CorruptRawReportError) as ex:
            go.from_txt(line, report_builder_session)

        assert (
            ex.value.corruption_error
            == "Missing numberOfStatements count\n at the end of the line, or they are not given in the right format"
        )
        assert (
            ex.value.expected_format
            == "name.go:line.column,line.column numberOfStatements count"
        )
