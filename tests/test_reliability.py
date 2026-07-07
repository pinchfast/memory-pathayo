import pytest

from kgmemory.people.service import compute_reliability


class FakeStore:
    def __init__(self, rows):
        self._rows = rows

    async def query(self, cypher, params=None):
        return self._rows


@pytest.mark.asyncio
async def test_reliability_zero_history():
    store = FakeStore([])
    result = await compute_reliability(store, "nobody")
    assert result["reliability_score"] == 0.5
    assert result["commitments"] == 0


@pytest.mark.asyncio
async def test_reliability_with_completed_and_missed():
    # commit, status_update, performance counts
    store = FakeStore([["commitment", 4], ["status_update", 3], ["performance", 1]])
    result = await compute_reliability(store, "dave")
    assert result["commitments"] == 4
    assert result["completed"] == 3
    assert result["missed_or_flagged"] == 1
    assert 0.0 < result["reliability_score"] < 1.0
