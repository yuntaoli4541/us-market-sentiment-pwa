import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_report import (  # noqa: E402
    build_decision_summary,
    build_watchlist_triggers,
    compare_metric_snapshots,
    build_score_history,
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
