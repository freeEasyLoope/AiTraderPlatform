"""日期格式归一化 & 历史日线区间过滤的回归测试。

背景（真实线上缺陷）：筛选器按 akshare 的习惯传紧凑日期 "YYYYMMDD"，
而 kline_http 用**字符串比较**过滤区间——"20240101" <= "2024-01-02" 因
ASCII 顺序（'0' > '-'）恒为 False，导致整批数据被静默过滤掉；
继续落到 baostock 兜底时又被判 "日期格式不正确，请修改。"。
两者都不抛异常，表现为"历史成交量莫名其妙取不到"，极难定位。
"""

import datetime

import pytest

from src.runtime import normalize_date


class TestNormalizeDate:
    def test_iso_passthrough(self):
        assert normalize_date("2024-01-02") == "2024-01-02"

    def test_compact_to_iso(self):
        assert normalize_date("20240102") == "2024-01-02"

    def test_compact_with_time_suffix(self):
        assert normalize_date("20240102 15:00:00") == "2024-01-02"

    def test_datetime_object(self):
        assert normalize_date(datetime.date(2024, 1, 2)) == "2024-01-02"
        assert normalize_date(datetime.datetime(2024, 1, 2, 15, 30)) == "2024-01-02"

    def test_empty_and_none(self):
        assert normalize_date(None) == ""
        assert normalize_date("") == ""
        assert normalize_date("   ") == ""

    def test_unrecognized_passthrough(self):
        assert normalize_date("not-a-date") == "not-a-date"

    def test_compact_is_not_string_comparable_with_iso(self):
        """固化缺陷成因：不归一化时，紧凑格式与 ISO 的字符串比较恒为 False。"""
        assert not ("20240101" <= "2024-01-02")
        assert normalize_date("20240101") <= "2024-01-02"


_BARS = [
    {"date": "2024-01-02", "open": 1.00, "high": 1.10, "low": 0.95, "close": 1.05,
     "volume": 100.0},
    {"date": "2024-01-03", "open": 1.05, "high": 1.20, "low": 1.00, "close": 1.15,
     "volume": 200.0},
    {"date": "2024-03-01", "open": 2.00, "high": 2.10, "low": 1.90, "close": 2.05,
     "volume": 300.0},
]


class TestFetchHistoryDateNormalization:
    def _patch_sources(self, monkeypatch):
        import src.data.kline_http as kh

        def _stub(sina_sym, start, end):
            return list(_BARS)

        monkeypatch.setattr(kh, "_SOURCES", (("stub", _stub),))
        return kh

    def test_compact_range_still_returns_bars(self, monkeypatch):
        """紧凑日期必须能取到数据（修复前这里返回 []）。"""
        kh = self._patch_sources(monkeypatch)
        snaps = kh.fetch_history("600519", "20240101", "20240131")
        assert len(snaps) == 2, "紧凑日期区间应命中前两根，而非被静默过滤"

    def test_iso_range_returns_bars(self, monkeypatch):
        kh = self._patch_sources(monkeypatch)
        snaps = kh.fetch_history("600519", "2024-01-01", "2024-01-31")
        assert len(snaps) == 2

    def test_compact_and_iso_yield_identical_result(self, monkeypatch):
        kh = self._patch_sources(monkeypatch)
        compact = kh.fetch_history("600519", "20240101", "20240131")
        iso = kh.fetch_history("600519", "2024-01-01", "2024-01-31")
        assert [s.close for s in compact] == [s.close for s in iso]

    def test_change_pct_backfilled(self, monkeypatch):
        """matcher 的涨跌停判定依赖 change_pct，曾硬编码为 0。"""
        kh = self._patch_sources(monkeypatch)
        snaps = kh.fetch_history("600519", "20240101", "20240131")
        assert snaps[0].change_pct == 0.0  # 首根无前收盘
        assert snaps[1].change_pct == pytest.approx((1.15 - 1.05) / 1.05)

    def test_out_of_range_returns_empty(self, monkeypatch):
        kh = self._patch_sources(monkeypatch)
        assert kh.fetch_history("600519", "20200101", "20200131") == []


class TestBatchNormalization:
    def test_batch_compact_dates(self, monkeypatch):
        import src.data.kline_http as kh

        captured = {}

        def _stub(sina_sym, start, end):
            captured["start"] = start
            return list(_BARS)

        monkeypatch.setattr(kh, "_SOURCES", (("stub", _stub),))
        out = kh.fetch_history_batch(["600519", "000858"], "20240101", "20240131")
        assert set(out) == {"600519", "000858"}
        assert all(len(v) == 2 for v in out.values())


class TestProviderBoundaryNormalization:
    def test_get_historical_data_normalizes_compact_dates(self, monkeypatch):
        """provider 入口必须归一化，保证 baostock 兜底拿到合法日期。"""
        import src.data.kline_http as kh
        from src.data.sina_client import SinaClient

        seen = {}

        def _fake_batch(symbols, start, end):
            seen["start"], seen["end"] = start, end
            return {}

        monkeypatch.setattr(kh, "fetch_history_batch", _fake_batch)

        SinaClient().get_historical_data(["600519"], "20240101", "20240131")
        assert seen["start"] == "2024-01-01"
        assert seen["end"] == "2024-01-31"
