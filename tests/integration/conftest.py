import pytest

from examples.transactions.pipeline import ToyPipeline


@pytest.fixture(params=["memory", "native"])
def make_toy(request):
    if request.param == "native":
        pytest.importorskip("xspcomm")
    toys = []

    def make(**options):
        toy = ToyPipeline(backend=request.param, **options)
        toys.append(toy)
        return toy

    yield make
    for toy in toys:
        try:
            assert toy.backend.watcher_count == 0
            assert toy.backend._owner is None
            assert toy.first.U() == toy.second.U() == 0
        finally:
            toy.close()
        if toy.native:
            assert toy.clock.StepRisQueueSize() == 0
