from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from xreactor import (
    Bin,
    CoverageDatabase,
    CoverGroupDef,
    CoverPointDef,
    generate_unified_coverage_report,
    generate_unified_coverage_site,
    parse_lcov,
)


class CoverageReportTests(unittest.TestCase):
    def test_lcov_deduplicates_records_and_reports_uncovered_ranges(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "code.info"
            path.write_text(
                "SF:/rtl/a.sv\nDA:10,2\nDA:11,0\nDA:12,0\nend_of_record\n"
                "SF:/rtl/a.sv\nDA:10,3\nDA:13,1\nend_of_record\n"
                "SF:/rtl/b.sv\nLF:4\nLH:3\nend_of_record\n",
                encoding="utf-8",
            )
            report = parse_lcov(path, name="sim")
        self.assertEqual(report["lines_found"], 8)
        self.assertEqual(report["lines_hit"], 5)
        self.assertEqual(report["files"][0]["uncovered_lines"], ["11-12"])

    def test_generates_self_contained_combined_html_and_escapes_payload(self) -> None:
        definition = CoverGroupDef(
            "fetch<script>",
            (CoverPointDef("kind", {"ok": Bin.values("ok")}),),
            description="Validate <fetch> behavior.",
        )
        group = definition.instantiate("ifu0")
        group.sample({"kind": "ok"}, details=False)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            functional = CoverageDatabase([group]).write_json(root / "functional.json")
            lcov = root / "line.info"
            lcov.write_text(
                "TN:test\nSF:/rtl/top.sv\nDA:1,1\nDA:2,0\nend_of_record\n",
                encoding="utf-8",
            )
            output = generate_unified_coverage_report(
                functional_paths=[functional],
                line_coverage=[("Verilator", lcov)],
                output=root / "coverage.html",
                title="DUT <coverage>",
            )
            document = output.read_text(encoding="utf-8")
        self.assertIn("DUT &lt;coverage&gt;", document)
        self.assertIn('\"format\":\"xreactor-unified-coverage\"', document)
        self.assertIn('\"name\":\"Verilator\"', document)
        self.assertNotIn("fetch<script>", document)
        self.assertNotIn("Validate <fetch> behavior.", document)
        self.assertNotIn("@@REPORT_JSON@@", document)

    def test_generates_functional_directory_and_group_pages(self) -> None:
        definition = CoverGroupDef(
            "fetch",
            (
                CoverPointDef(
                    "kind",
                    {"ok": Bin.values("ok"), "err": Bin.values("err")},
                    description="Classifies the fetch result.",
                ),
            ),
            description="Covers end-to-end fetch behavior.",
        )
        group = definition.instantiate("core0.ifu")
        group.sample({"kind": "ok"}, details=False)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            functional = CoverageDatabase([group]).write_json(root / "functional.json")
            site = root / "site"
            index = generate_unified_coverage_site(
                functional_paths=[functional],
                output_dir=site,
                title="DUT coverage",
            )
            group_pages = list((site / "functional" / "groups").glob("*/index.html"))
            group_document = group_pages[0].read_text(encoding="utf-8")
            point_pages = list((site / "functional" / "groups").glob("*/points/*.html"))
            point_document = point_pages[0].read_text(encoding="utf-8")
            # Regeneration is permitted only because the site carries its marker.
            generate_unified_coverage_site(
                functional_paths=[functional], output_dir=site, title="DUT coverage"
            )
            self.assertTrue(index.is_file())
            self.assertTrue((site / "functional" / "index.html").is_file())
            self.assertTrue((site / "line" / "index.html").is_file())
        self.assertEqual(len(group_pages), 1)
        self.assertEqual(len(point_pages), 1)
        self.assertIn("points/", group_document)
        self.assertIn("Covers end-to-end fetch behavior.", group_document)
        self.assertIn("Classifies the fetch result.", group_document)
        self.assertIn("Classifies the fetch result.", point_document)
        self.assertIn("uncovered", point_document)
        self.assertIn("Matcher / definition", point_document)


if __name__ == "__main__":
    unittest.main()
