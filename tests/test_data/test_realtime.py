"""实时行情多源链的回归测试（全部离线，用合成字段，不依赖网络）。

背景：新浪实时行情 `hq.sinajs.cn` 在部分托管节点被拒（实测 PocketBay 节点 403 /
连接超时），全项目曾有 8 处直连它。改为「腾讯优先 + 新浪兜底」后，必须保证：
  1. 腾讯 `~` 分隔字段能被正确映射成 MarketSnapshot；
  2. 兼容层产出的新浪线格式能被历史遗留的正则 + parts[1..5]/parts[8] 正确读取。
"""

import pytest

from src.data import realtime_http as rt


QT_FIELDS = [
    "1", "贵州茅台", "600519", "1258.00", "1272.75", "1273.93", "26235", "12117", "14119",
    "1258.00", "17", "1257.99", "4", "1257.88", "6", "1257.80", "3", "1257.79", "1",
    "1258.02", "2", "1258.04", "4", "1258.08", "1", "1258.18", "1", "1258.23", "1", "",
    "20260916161500", "-14.75", "-1.16", "1274.98", "1254.10",
    "1258.00/26235/3307926407", "26235", "330793", "0.21", "19.31", "",
    "1274.98", "1254.10", "1.64", "15726.03", "15726.03", "6.26", "1400.03", "1145.48",
]


class TestParseQtPayload:
    def test_parses_single(self):
        raw = 'v_sh600519="' + "~".join(QT_FIELDS) + '";'
        out = rt._parse_qt_payload(raw)
        assert "600519" in out
        assert out["600519"][1] == "贵州茅台"

    def test_parses_multiple_and_skips_garbage(self):
        raw = ('v_sh600519="' + "~".join(QT_FIELDS) + '";\n'
               'v_sz000858="51~五 粮 液~000858~69.26~69.70~69.60~154126~1~2~3~4~5~6~7~8~9~10~11~12~13~14~15~16~17~18~19~20~21~22~23~24~25~26~27~28";\n'
               'pv_none_match="whatever";\n'
               'garbage-no-equals\n')
        out = rt._parse_qt_payload(raw)
        assert set(out) >= {"600519", "000858"}

    def test_empty(self):
        assert rt._parse_qt_payload("") == {}


class TestToSnapshot:
    def test_field_mapping(self):
        snap = rt._to_snapshot("600519", QT_FIELDS)
        assert snap is not None
        assert snap.name == "贵州茅台"
        assert snap.close == pytest.approx(1258.00)
        assert snap.open == pytest.approx(1273.93)
        assert snap.high == pytest.approx(1274.98)
        assert snap.low == pytest.approx(1254.10)
        # 成交量：手 → 股
        assert snap.volume == pytest.approx(26235 * 100)
        # 涨跌幅由前收算得，而不是直接抄字段
        assert snap.change_pct == pytest.approx((1258.00 - 1272.75) / 1272.75)
        assert snap.pe == pytest.approx(19.31)
        assert snap.pb == pytest.approx(6.26)
        # 总市值：亿 → 元
        assert snap.total_market_cap == pytest.approx(15726.03 * 1e8)

    def test_zero_price_rejected(self):
        fields = list(QT_FIELDS)
        fields[3] = "0.00"
        assert rt._to_snapshot("600519", fields) is None

    def test_short_field_list_does_not_raise(self):
        snap = rt._to_snapshot("600519", QT_FIELDS[:8])
        assert snap is not None
        assert snap.close == pytest.approx(1258.00)
        assert snap.pe is None and snap.pb is None


class TestSinaFormatCompat:
    def test_line_shape_and_legacy_indices(self):
        line = rt._sina_line("600519", QT_FIELDS)
        assert line.startswith('var hq_str_sh600519="')
        body = line.split('"')[1]
        parts = body.split(",")
        assert len(parts) >= 32, "旧解析要求 len(parts) >= 32"
        assert parts[0] == "贵州茅台"      # 名称
        assert float(parts[1]) == pytest.approx(1273.93)  # 今开
        assert float(parts[2]) == pytest.approx(1272.75)  # 昨收
        assert float(parts[3]) == pytest.approx(1258.00)  # 当前价
        assert float(parts[4]) == pytest.approx(1274.98)  # 最高
        assert float(parts[5]) == pytest.approx(1254.10)  # 最低
        assert float(parts[8]) == pytest.approx(26235)    # 成交量(手)，仍需 ×100
        assert parts[30] == "2026-09-16"
        assert parts[31] == "16:15:00"

    def test_amount_in_wan(self):
        parts = rt._sina_line("600519", QT_FIELDS).split('"')[1].split(",")
        # 成交额 3307926407 元 → 330792.6407 万元
        assert float(parts[9]) == pytest.approx(330792.6407, rel=1e-6)

    def test_shenzhen_prefix(self):
        line = rt._sina_line("000858", QT_FIELDS)
        assert line.startswith('var hq_str_sz000858="')

    def test_missing_stamp_still_32_fields(self):
        fields = list(QT_FIELDS)
        fields[30] = ""
        parts = rt._sina_line("600519", fields).split('"')[1].split(",")
        assert len(parts) >= 32


class TestSourceFallback:
    def test_fetch_realtime_empty_input(self):
        assert rt.fetch_realtime([]) == {}

    def test_fetch_sina_format_falls_back_to_sina(self, monkeypatch):
        """多源全失败时必须回落新浪原站，而不是返回空串。"""
        monkeypatch.setattr(rt, "_SOURCES", ())
        import src.data.sina_client as sc
        monkeypatch.setattr(sc, "fetch_sina_raw", lambda syms, timeout=10.0: "SINA_FALLBACK")
        assert rt.fetch_sina_format(["600519"]) == "SINA_FALLBACK"

    def test_fetch_realtime_uses_first_nonempty_source(self, monkeypatch):
        calls = []

        def _dead(symbols):
            calls.append("dead")
            return {}

        def _live(symbols):
            calls.append("live")
            return {"600519": QT_FIELDS}

        monkeypatch.setattr(rt, "_SOURCES", (("dead", _dead), ("live", _live)))
        snaps = rt.fetch_realtime(["600519"])
        assert calls == ["dead", "live"], "应跳过空源继续下一个"
        assert snaps["600519"].close == pytest.approx(1258.00)

    def test_fetch_realtime_all_dead_returns_empty(self, monkeypatch):
        monkeypatch.setattr(rt, "_SOURCES", (("dead", lambda s: {}),))
        assert rt.fetch_realtime(["600519"]) == {}

    def test_source_exception_does_not_propagate(self, monkeypatch):
        def _boom(symbols):
            raise RuntimeError("network down")

        monkeypatch.setattr(rt, "_SOURCES", (("boom", _boom),))
        assert rt.fetch_realtime(["600519"]) == {}
