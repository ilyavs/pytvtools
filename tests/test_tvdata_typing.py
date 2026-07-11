from typing import get_type_hints, Any
from pytvtools_core.tvdata import TVData
from pytvtools_core.types import OHLCVBar

def test_get_ohlcv_return_type():
    hints = get_type_hints(TVData.get_ohlcv)
    # The actual signature is list[OHLCVBar] | dict[str, Any]
    assert hints["return"] == list[OHLCVBar] | dict[str, Any]
