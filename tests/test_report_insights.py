import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_report import (  # noqa: E402
    build_decision_summary,
    build_watchlist_triggers,
    compare_metric_snapshots,
    build_score_history,
    build_sector_heatmap,
    build_market_breadth,
    build_style_factors,
    build_trend_state,
    build_risk_score_breakdown,
    build_comprehensive_strategy_guide,
)


def test_build_decision_summary_returns_actionable_topline():
    summary = build_decision_summary(
        score=7.5,
        bias="偏多",
        data={
            "SP500": {"change_pct": 0.22},
            "VIX": {"price": 15.3, "change_pct": -2.8},
            "TNX": {"price": 4.45, "change_pct": -0.04},
            "HYG": {"change_pct": 0.14},
            "JNK": {"change_pct": 0.05},
        },
        fg_score=60,
    )

    assert summary["bias"] == "偏多"
    assert summary["score"] == "7.5"
    assert summary["allocation"] == "5-6成"
    assert "偏多" in summary["headline"]
    assert summary["primary_driver"]
    assert summary["primary_risk"]


def test_build_watchlist_triggers_includes_rules_with_active_state():
    triggers = build_watchlist_triggers(
        data={
            "VIX": {"price": 21.2},
            "TNX": {"price": 4.82},
            "HYG": {"change_pct": -0.2},
            "JNK": {"change_pct": -0.25},
            "DXY": {"change_pct": 0.8},
        }
    )

    labels = [item["label"] for item in triggers]
    assert "VIX 上破 20" in labels
    assert "TNX 上破 4.7%" in labels
    assert any(item["active"] for item in triggers)
    assert all("detail" in item for item in triggers)


def test_compare_metric_snapshots_marks_improving_and_worsening():
    changes = compare_metric_snapshots(
        current={
            "SP500_price": "101.00",
            "SP500_change": "1.00",
            "VIX_price": "15.00",
            "FG_Score": "60",
            "TNX_price": "4.20%",
        },
        previous={
            "SP500_price": "100.00",
            "SP500_change": "0.50",
            "VIX_price": "18.00",
            "FG_Score": "50",
            "TNX_price": "4.00%",
        },
    )

    by_key = {item["key"]: item for item in changes}
    assert by_key["SP500_price"]["direction"] == "up"
    assert by_key["VIX_price"]["tone"] == "positive"
    assert by_key["TNX_price"]["tone"] == "negative"


def test_build_score_history_appends_today_and_keeps_recent_points():
    history = build_score_history(
        date_iso="2026-06-02",
        score=7.5,
        previous={
            "score_history": [
                {"date": "2026-05-30", "score": 6.5, "bias": "中性震荡"},
                {"date": "2026-06-01", "score": 7.0, "bias": "偏多"},
            ]
        },
        bias="偏多",
        limit=2,
    )

    assert history == [
        {"date": "2026-06-01", "score": 7.0, "bias": "偏多"},
        {"date": "2026-06-02", "score": 7.5, "bias": "偏多"},
    ]


def test_build_sector_heatmap_sorts_and_classifies_major_sectors():
    raw = {
        "XLK": {"price": 250.12, "change_pct": 1.45},
        "XLE": {"price": 92.50, "change_pct": -1.25},
        "XLV": {"price": 148.33, "change_pct": 0.05},
        "XLF": {"price": 52.10, "change_pct": 0.72},
    }

    heatmap = build_sector_heatmap(raw)

    assert [item["symbol"] for item in heatmap[:2]] == ["XLK", "XLF"]
    assert heatmap[0]["name"] == "科技"
    assert heatmap[0]["tone"] == "strong_up"
    assert heatmap[-1]["symbol"] == "XLE"
    assert heatmap[-1]["tone"] == "strong_down"
    assert all("change" in item and item["change"].endswith("%") for item in heatmap)



def test_sector_heatmap_includes_software_industry_etf():
    raw = {
        "IGV": {"price": 101.0, "change_pct": 1.2},
        "XLK": {"price": 250.0, "change_pct": 0.5},
    }

    heatmap = build_sector_heatmap(raw)
    by_symbol = {item["symbol"]: item for item in heatmap}

    assert by_symbol["IGV"]["name"] == "软件"
    assert by_symbol["IGV"]["category"] == "行业"


def test_index_no_longer_links_to_pdf_report():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "下载完整 PDF 报告" not in html
    assert "public/report.pdf" not in html



def test_industry_heatmap_includes_peer_etfs_and_holdings():
    raw = {
        "IGV": {"price": 101.0, "change_pct": 1.2},
        "SMH": {"price": 220.0, "change_pct": 2.4},
        "HACK": {"price": 70.0, "change_pct": -0.2},
        "SKYY": {"price": 90.0, "change_pct": 0.4},
        "XBI": {"price": 88.0, "change_pct": -1.1},
        "KRE": {"price": 55.0, "change_pct": 0.8},
    }

    heatmap = build_sector_heatmap(raw)
    by_symbol = {item["symbol"]: item for item in heatmap}

    for symbol in ["IGV", "SMH", "HACK", "SKYY", "XBI", "KRE"]:
        assert by_symbol[symbol]["category"] == "行业"
        assert by_symbol[symbol]["holdings"]
        assert {"symbol", "name"}.issubset(by_symbol[symbol]["holdings"][0])

    assert by_symbol["SMH"]["name"] == "半导体"
    assert by_symbol["HACK"]["name"] == "网络安全"


def test_index_has_clickable_holdings_modal_for_industry_cards():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "holdings-modal" in html
    assert "openHoldingsModal" in html
    assert "前十大持仓" in html



def test_sector_heatmap_marks_group_and_holding_scope():
    raw = {
        "XLK": {"price": 100.0, "change_pct": 0.3},
        "IGV": {"price": 101.0, "change_pct": 1.2},
    }

    heatmap = build_sector_heatmap(raw)
    by_symbol = {item["symbol"]: item for item in heatmap}

    assert by_symbol["XLK"]["group"] == "sector"
    assert by_symbol["IGV"]["group"] == "industry"
    assert by_symbol["IGV"]["holding_scope"] == "top10_yfinance"
    assert by_symbol["IGV"]["holding_note"]


def test_index_separates_sector_and_industry_heatmaps():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "sector-heatmap" in html
    assert "industry-heatmap" in html
    assert "renderGroupedHeatmaps" in html
    assert "前十大持仓" in html


def test_heatmap_colors_are_normalized_independently_by_group():
    raw = {
        "XLK": {"price": 100.0, "change_pct": 0.5},
        "XLE": {"price": 100.0, "change_pct": -0.5},
        "IGV": {"price": 100.0, "change_pct": 0.5},
        "SMH": {"price": 100.0, "change_pct": 2.0},
    }

    heatmap = build_sector_heatmap(raw)
    by_symbol = {item["symbol"]: item for item in heatmap}

    assert by_symbol["XLK"]["heatmap_scale"] == "sector"
    assert by_symbol["IGV"]["heatmap_scale"] == "industry"
    assert by_symbol["XLK"]["heatmap_color"] != by_symbol["IGV"]["heatmap_color"]
    assert by_symbol["XLK"]["heatmap_intensity"] > by_symbol["IGV"]["heatmap_intensity"]
    assert all("heatmap_color" in item and "heatmap_intensity" in item for item in heatmap)


def test_watchlist_summary_explains_all_observed_indicator_groups():
    data = {
        "VIX": {"price": 21},
        "TNX": {"price": 4.8},
        "HYG": {"change_pct": -0.4},
        "JNK": {"change_pct": -0.3},
        "DXY": {"change_pct": 0.8},
        "GOLD": {"change_pct": 1.2},
        "SP500": {"change_pct": -0.5},
        "NASDAQ": {"change_pct": -0.8},
    }

    triggers = build_watchlist_triggers(data)
    labels = {item["label"] for item in triggers}

    assert "大盘指数同步走弱" in labels
    assert "黄金避险走强" in labels
    assert "VIX 上破 20" in labels
    assert "TNX 上破 4.7%" in labels



def test_build_enhanced_summary_sections_returns_decision_memo():
    from generate_report import build_enhanced_summary_sections

    data = {
        "SP500": {"change_pct": 0.4},
        "NASDAQ": {"change_pct": 0.8},
        "VIX": {"price": 16.0, "change_pct": -1.0},
        "TNX": {"price": 4.55},
        "HYG": {"change_pct": 0.05},
        "JNK": {"change_pct": 0.02},
        "DXY": {"change_pct": -0.1},
        "GOLD": {"change_pct": 0.2},
    }
    sector_heatmap = [
        {"symbol": "XLK", "name": "科技", "group": "sector", "change_pct": 1.1, "tone": "strong_up"},
        {"symbol": "XLP", "name": "必需消费", "group": "sector", "change_pct": -0.2, "tone": "flat"},
        {"symbol": "IGV", "name": "软件", "group": "industry", "change_pct": 1.8, "tone": "strong_up"},
        {"symbol": "SMH", "name": "半导体", "group": "industry", "change_pct": 1.2, "tone": "strong_up"},
    ]
    triggers = build_watchlist_triggers(data)

    sections = build_enhanced_summary_sections(
        data=data,
        score=7.5,
        bias="偏多",
        allocation="5-6成",
        sector_heatmap=sector_heatmap,
        triggers=triggers,
    )

    assert sections["logic_breakdown"]
    assert len(sections["logic_breakdown"]) >= 4
    assert sections["risk_summary"]["level"] in {"低", "低到中等", "中等", "偏高", "高"}
    assert sections["risk_summary"]["summary"]
    assert sections["tomorrow_watchlist"]
    assert len(sections["tomorrow_watchlist"]) >= 4
    assert sections["rotation_summary"]["sector_leaders"]
    assert sections["rotation_summary"]["industry_leaders"]
    assert sections["rotation_summary"]["interpretation"]


def test_decision_summary_contains_enhanced_sections():
    summary = build_decision_summary(
        score=7.5,
        bias="偏多",
        data={
            "SP500": {"change_pct": 0.22},
            "NASDAQ": {"change_pct": 0.5},
            "VIX": {"price": 15.3, "change_pct": -2.8},
            "TNX": {"price": 4.45, "change_pct": -0.04},
            "HYG": {"change_pct": 0.14},
            "JNK": {"change_pct": 0.05},
            "DXY": {"change_pct": -0.1},
            "GOLD": {"change_pct": 0.2},
        },
        fg_score=60,
        sector_heatmap=[
            {"symbol": "XLK", "name": "科技", "group": "sector", "change_pct": 0.8, "tone": "up"},
            {"symbol": "IGV", "name": "软件", "group": "industry", "change_pct": 1.3, "tone": "strong_up"},
        ],
        triggers=[],
    )

    for key in ["logic_breakdown", "risk_summary", "tomorrow_watchlist", "rotation_summary"]:
        assert key in summary


def test_top_decision_summary_stays_compact_and_non_redundant():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    top_block = html.split('<!-- 1. 大盘核心指数 -->')[0]

    assert "今日核心结论" in top_block
    for text in ["今日逻辑拆解", "风险总评", "明日观察重点", "轮动解读"]:
        assert text not in top_block
    for element_id in ["logic-breakdown", "risk-level", "rotation-interpretation", "tomorrow-watchlist"]:
        assert element_id not in top_block
    assert "decision-headline" in top_block
    assert "decision-score" in top_block
    assert "decision-allocation" in top_block


def test_build_market_breadth_uses_equal_weight_and_small_cap_proxies():
    breadth = build_market_breadth({
        "SPY": {"change_pct": 0.8},
        "RSP": {"change_pct": 0.2},
        "QQQ": {"change_pct": 1.0},
        "QQQE": {"change_pct": 0.1},
        "IWM": {"change_pct": -0.4},
    })

    assert breadth["overall"] == "窄幅上涨"
    labels = {item["label"] for item in breadth["items"]}
    assert {"等权标普 vs 标普", "等权纳指 vs 纳指", "小盘股 vs 标普"}.issubset(labels)
    assert breadth["items"][0]["spread"].endswith("%")
    assert breadth["summary"]


def test_build_style_factors_sorts_factor_etfs_and_interprets_leadership():
    factors = build_style_factors({
        "SPY": {"change_pct": 0.3},
        "IWF": {"change_pct": 1.0},
        "IWD": {"change_pct": -0.1},
        "IWM": {"change_pct": 0.5},
        "MTUM": {"change_pct": 0.9},
        "QUAL": {"change_pct": 0.4},
        "USMV": {"change_pct": -0.2},
        "VYM": {"change_pct": 0.1},
    })

    assert factors["leaders"][0]["symbol"] == "IWF"
    assert factors["leadership"] in {"成长/动量占优", "价值/防御占优", "风格分化不明显"}
    assert all({"symbol", "name", "change", "tone"}.issubset(item) for item in factors["items"])


def test_build_trend_state_classifies_index_trend_from_chart_data():
    chart_data = {
        "SP500": {
            "5d": [{"v": 100}, {"v": 101}, {"v": 103}, {"v": 104}],
            "1mo": [{"v": 95}, {"v": 98}, {"v": 104}],
        },
        "NASDAQ": {
            "5d": [{"v": 100}, {"v": 99}, {"v": 101}, {"v": 103}],
            "1mo": [{"v": 96}, {"v": 100}, {"v": 103}],
        },
    }

    trend = build_trend_state(chart_data, {"SP500": {"change_pct": 0.5}, "NASDAQ": {"change_pct": 0.8}})

    assert trend["overall"] == "多头趋势"
    assert trend["items"][0]["label"] == "标普500"
    assert trend["items"][0]["state"] in {"多头趋势", "震荡偏多", "震荡", "震荡偏空", "空头趋势"}
    assert trend["summary"]


def test_build_risk_score_breakdown_explains_score_components():
    breakdown = build_risk_score_breakdown(
        data={
            "SP500": {"change_pct": 0.6},
            "NASDAQ": {"change_pct": 1.0},
            "VIX": {"price": 18, "change_pct": -2.0},
            "HYG": {"change_pct": 0.1},
            "JNK": {"change_pct": 0.1},
            "TNX": {"price": 4.3, "change_pct": 0.1},
            "DXY": {"change_pct": -0.2},
            "GOLD": {"change_pct": 0.1},
        },
        fg_score=58,
        breadth={"overall": "窄幅上涨"},
        trend_state={"overall": "多头趋势"},
    )

    names = {item["name"] for item in breakdown["components"]}
    assert {"大盘趋势", "情绪/VIX", "信用环境", "利率美元", "市场宽度"}.issubset(names)
    assert 0 <= breakdown["total"] <= 10
    assert breakdown["summary"]


def test_index_renders_decision_dashboard_expansion_sections():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    for text in ["市场宽度", "风格因子", "趋势状态", "评分拆解"]:
        assert text in html
    for fn in ["renderMarketBreadth", "renderStyleFactors", "renderTrendState", "renderRiskScoreBreakdown"]:
        assert fn in html


def test_index_removes_redundant_emotion_action_guidance():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "情绪操作导向" not in html
    assert "vix-tip" not in html


def test_heatmap_cards_show_separate_trend_strength_label():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "趋势强弱" in html
    assert "heatmapTrendLabel" in html


def test_index_uses_group_normalized_heatmap_colors():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "heatmap_color" in html
    assert "heatmap_text_color" in html
    assert "独立色阶" in html


def test_comprehensive_strategy_guide_integrates_all_indicator_groups():
    guide = build_comprehensive_strategy_guide(
        score=7.5,
        bias="偏多",
        action_plan="操作建议：维持五至六成仓位，以标普500宽基指数为核心压舱石，避免重仓单一个股。利用短期回调分批加仓。",
        market_breadth={
            "overall": "窄幅上涨",
            "summary": "等权指数弱于市值加权，需警惕少数大盘股拉动。",
            "items": [{"label": "等权标普 vs 标普", "spread": "-0.60%", "tone": "negative"}],
        },
        style_factors={
            "leadership": "成长/动量占优",
            "leaders": [
                {"symbol": "IWF", "name": "成长", "change": "+1.00%"},
                {"symbol": "MTUM", "name": "动量", "change": "+0.90%"},
            ],
        },
        trend_state={"overall": "多头趋势", "summary": "标普和纳指维持震荡偏多到多头趋势。"},
        risk_score_breakdown={
            "total": 7.2,
            "components": [
                {"name": "大盘趋势", "score": 2.0, "max": 2, "detail": "多头趋势"},
                {"name": "市场宽度", "score": 0.8, "max": 2, "detail": "窄幅上涨"},
                {"name": "利率美元", "score": 1.0, "max": 2, "detail": "利率中高位"},
            ],
        },
        decision_summary={
            "allocation": "5-6成",
            "rotation_summary": {
                "sector_leaders": [{"symbol": "XLK", "name": "科技", "change": "+0.80%"}],
                "industry_leaders": [{"symbol": "IGV", "name": "软件", "change": "+1.30%"}],
                "interpretation": "成长主题占优。",
            },
            "risk_summary": {"level": "低到中等", "action": "若 VIX 上破 20 且信用债走弱，降低追高。"},
            "tomorrow_watchlist": ["VIX 是否低于 20", "HYG/JNK 是否稳定"],
        },
        watchlist_triggers=[
            {"label": "VIX 上破 20", "active": False, "detail": "观察波动风险"},
            {"label": "信用债同步走弱", "active": False, "detail": "观察信用环境"},
        ],
    )

    assert guide["verdict"]["bias"] == "偏多"
    assert guide["verdict"]["allocation"] == "5-6成"
    assert {item["group"] for item in guide["evidence"]}.issuperset({"大盘趋势", "市场宽度", "风格因子", "板块/行业轮动", "评分拆解"})
    assert any("IWF" in item["detail"] or "成长" in item["detail"] for item in guide["allocation_plan"])
    assert guide["risk_controls"]
    assert guide["tomorrow_watchlist"]


def test_index_renders_structured_comprehensive_strategy_guide():
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    for text in ["总判断", "核心配置", "加仓条件", "减仓条件", "综合依据"]:
        assert text in html
    assert "renderComprehensiveStrategyGuide" in html
    assert "strategy-guide" in html
