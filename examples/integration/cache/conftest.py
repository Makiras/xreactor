"""Native helpers shared by the independently selected Cache RTL tests."""
import pytest

from examples.integration.cache.cache_assertion_env import build_fatal_coverage


@pytest.fixture(scope="session")
def fatal_coverage_library(tmp_path_factory):
    return build_fatal_coverage(tmp_path_factory.mktemp("fatal-coverage-hook"))
