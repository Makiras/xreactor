"""Small functional-coverage definition organized around one protocol."""

from xreactor import Bin, CoverGroupDef, CoverPointDef, CrossDef


fetch_coverage = CoverGroupDef(
    "fetch",
    (
        CoverPointDef(
            "target",
            {
                "local": Bin.values("local"),
                "external": Bin.values("external"),
            },
            description="Exercises both instruction-fetch destinations.",
        ),
        CoverPointDef(
            "response",
            {
                "ok": Bin.values("ok"),
                "error": Bin.values("error"),
            },
            description="Exercises successful and failed responses.",
        ),
    ),
    (
        CrossDef(
            "target_x_response",
            ("target", "response"),
            description="Checks every response type on both routes.",
        ),
    ),
    description="End-to-end fetch routing coverage.",
)


if __name__ == "__main__":
    coverage = fetch_coverage.instantiate("core0.ifu")
    coverage.sample({"target": "local", "response": "ok"})
    coverage.sample({"target": "local", "response": "error"})
    coverage.sample({"target": "external", "response": "ok"})
    coverage.sample({"target": "external", "response": "error"})
    print(coverage.report())
