import os
import json
import requests
import pandas as pd
import yfinance as yf
from weasyprint import HTML
from datetime import datetime, timezone, timedelta

# ==========================================
# 1. 资产配置
# ==========================================
TICKERS = {
    'SP500':  '^GSPC',
    'NASDAQ': '^IXIC',
    'VIX':    '^VIX',
    'HYG':    'HYG',
    'JNK':    'JNK',
    'TNX':    '^TNX',
    'GOLD':   'GC=F',
    'DXY':    'DX-Y.NYB',
}

ET = timezone(timedelta(hours=-4))   # 美东夏令时 EDT，全年误差 ≤1小时可接受

# ==========================================
# 2. 获取 yfinance 数据实际时间戳
# ==========================================
def get_data_timestamp():
    """
    从 yfinance 读取标普500的 regular_market_time，
    这是数据源最后更新的时间，而非脚本运行时间。
    """
    try:
        info = yf.Ticker('^GSPC').fast_info
        ts   = getattr(info, 'regular_market_time', None)
        if ts is not None:
            # regular_market_time 可能是 datetime 或 Unix 时间戳
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            else:
                dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            dt_et = dt.astimezone(ET)
            print(f"Data timestamp from yfinance: {dt_et.strftime('%Y-%m-%d %H:%M ET')}")
            return dt_et
    except Exception as e:
        print(f"Warning: could not get market time: {e}")

    # 备用：用 yf.download 最后一根 K 线的日期
    try:
        df    = yf.download('^GSPC', period="5d", interval="1d", progress=False)
        last  = df.index[-1]
        # 日线数据没有具体时间，默认用收盘时间 16:00 ET
        dt    = datetime(last.year, last.month, last.day, 16, 0, 0, tzinfo=ET)
        print(f"Data timestamp fallback (last bar): {dt.strftime('%Y-%m-%d %H:%M ET')}")
        return dt
    except Exception as e:
        print(f"Warning: fallback timestamp also failed: {e}")
        return datetime.now(ET)

# ==========================================
# 3. 抓取收盘数据
# ==========================================
def get_market_data():
    market_data = {}
    for name, sym in TICKERS.items():
        try:
            t       = yf.Ticker(sym)
            info    = t.fast_info
            current = getattr(info, 'last_price', None) or getattr(info, 'regularMarketPrice', None)
            prev    = getattr(info, 'previous_close', None) or getattr(info, 'regularMarketPreviousClose', None)

            if current and prev and prev != 0:
                market_data[name] = {
                    'price':      float(current),
                    'change_pct': ((float(current) - float(prev)) / float(prev)) * 100
                }
            else:
                df = yf.download(sym, period="5d", progress=False)['Close']
                if len(df) >= 2:
                    cur = float(df.iloc[-1].iloc[0])
                    prv = float(df.iloc[-2].iloc[0])
                    market_data[name] = {'price': cur, 'change_pct': ((cur - prv) / prv) * 100}
                else:
                    market_data[name] = {'price': 0.0, 'change_pct': 0.0}

            print(f"{name}: {market_data[name]['price']:.4f} ({market_data[name]['change_pct']:+.2f}%)")

        except Exception as e:
            print(f"Warning: Error fetching {name}: {e}")
            market_data[name] = {'price': 0.0, 'change_pct': 0.0}

    return market_data

# ==========================================
# 4. 抓取走势图数据（全部资产）
# ==========================================
def fetch_series(sym, period, interval):
    try:
        df    = yf.download(sym, period=period, interval=interval, progress=False)
        close = df['Close'].squeeze()
        if close.empty:
            return []
        idx = close.index
        if hasattr(idx, 'tz') and idx.tz is not None:
            idx = idx.tz_convert('America/New_York')
        fmt = ("%H:%M" if period == "1d" else
               "%m/%d %H:%M" if interval in ('5m', '15m', '30m') else
               "%m/%d")
        return [
            {"t": ts.strftime(fmt), "v": round(float(v), 4)}
            for ts, v in zip(idx, close)
            if not pd.isna(v)
        ]
    except Exception as e:
        print(f"  Warning: fetch_series {sym} {period}/{interval} failed: {e}")
        return []

def get_chart_data():
    chart_data = {}
    for name, sym in TICKERS.items():
        print(f"Fetching chart data for {name} ({sym})...")
        ticker_data = {
            'intraday': fetch_series(sym, "1d",  "5m"),
            '5d':       fetch_series(sym, "5d",  "30m"),
            '1mo':      fetch_series(sym, "1mo", "1d"),
        }
        print(f"  intraday={len(ticker_data['intraday'])} pts, "
              f"5d={len(ticker_data['5d'])} pts, "
              f"1mo={len(ticker_data['1mo'])} pts")
        chart_data[name] = ticker_data
    return chart_data

# ==========================================
# 5. CNN 恐惧与贪婪指数
# ==========================================
def fetch_fear_greed():
    rating_map = {
        "Extreme Fear":  "极度恐惧",
        "Fear":          "恐惧",
        "Neutral":       "中性",
        "Greed":         "贪婪",
        "Extreme Greed": "极度贪婪",
    }
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={
                "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept":          "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer":         "https://edition.cnn.com/markets/fear-and-greed",
                "Origin":          "https://edition.cnn.com",
            },
            timeout=10
        )
        resp.raise_for_status()
        d      = resp.json()
        score  = round(d["fear_and_greed"]["score"])
        rating = d["fear_and_greed"]["rating"]
        print(f"CNN F&G: {score} ({rating})")
        return {"FG_Score": score, "FG_Status": rating_map.get(rating, rating)}
    except Exception as e:
        print(f"Warning: CNN F&G failed: {e}, switching to backup...")
    try:
        resp  = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d     = resp.json()
        score = int(d["data"][0]["value"])
        cls   = d["data"][0]["value_classification"]
        print(f"alternative.me F&G: {score} ({cls})")
        return {"FG_Score": score, "FG_Status": rating_map.get(cls, cls)}
    except Exception as e:
        print(f"Error: F&G backup failed: {e}")
        return {"FG_Score": "N/A", "FG_Status": "获取失败"}

# ==========================================
# 6. VIX 策略映射
# ==========================================
def get_vix_strategy(vix_val):
    if vix_val < 12:
        return {"status": "极度乐观", "tip": "谨慎追高，控制仓位"}
    elif vix_val < 20:
        return {"status": "正常区间", "tip": "常规定投，持股待涨"}
    elif vix_val < 30:
        return {"status": "恐惧上升", "tip": "加大定投，分批建仓"}
    elif vix_val < 50:
        return {"status": "市场恐慌", "tip": "加倍定投，逢低布局"}
    else:
        return {"status": "极度恐慌", "tip": "大胆抄底，重仓入场"}

# ==========================================
# 7. 综合策略解读
# ==========================================
def generate_strategy(data, fg_data, vix_strategy):
    sp500_chg      = data['SP500']['change_pct']
    nasdaq_chg     = data['NASDAQ']['change_pct']
    vix_val        = data['VIX']['price']
    tnx_val        = data['TNX']['price']
    gold_chg       = data['GOLD']['change_pct']
    dxy_chg        = data['DXY']['change_pct']
    hyg_chg        = data['HYG']['change_pct']
    jnk_chg        = data['JNK']['change_pct']
    fg_score       = fg_data['FG_Score']
    avg_credit_chg = (hyg_chg + jnk_chg) / 2
    strategies     = []

    if sp500_chg > 1.5 and nasdaq_chg > 1.5:
        market_view = f"今日大盘强势上涨，标普500收涨 {sp500_chg:.2f}%，纳指收涨 {nasdaq_chg:.2f}%，市场做多情绪明显占优。"
    elif sp500_chg > 0 and nasdaq_chg > 0:
        market_view = f"今日大盘小幅收涨，标普500 {sp500_chg:+.2f}%，纳指 {nasdaq_chg:+.2f}%，整体偏多但动能有限。"
    elif sp500_chg < -1.5 and nasdaq_chg < -1.5:
        market_view = f"今日大盘显著下跌，标普500收跌 {abs(sp500_chg):.2f}%，纳指收跌 {abs(nasdaq_chg):.2f}%，市场抛压较重。"
    else:
        market_view = f"今日大盘震荡整理，标普500 {sp500_chg:+.2f}%，纳指 {nasdaq_chg:+.2f}%，多空分歧明显。"
    strategies.append(f"📊 大盘表现：{market_view}")

    if isinstance(fg_score, int):
        if fg_score >= 75:
            fg_view = f"恐惧贪婪指数高达 {fg_score}（{fg_data['FG_Status']}），市场过热风险上升，追高需谨慎。"
        elif fg_score >= 55:
            fg_view = f"恐惧贪婪指数为 {fg_score}（{fg_data['FG_Status']}），情绪偏乐观但尚未过热，可维持正常定投节奏。"
        elif fg_score >= 45:
            fg_view = f"恐惧贪婪指数为 {fg_score}（{fg_data['FG_Status']}），市场情绪中性，观望为主，等待方向明确。"
        elif fg_score >= 25:
            fg_view = f"恐惧贪婪指数为 {fg_score}（{fg_data['FG_Status']}），市场情绪偏悲观，历史上往往是较好的分批入场时机。"
        else:
            fg_view = f"恐惧贪婪指数仅 {fg_score}（{fg_data['FG_Status']}），市场处于极度悲观状态，可考虑逆向布局。"
    else:
        fg_view = f"恐惧贪婪指数获取失败，建议参考 VIX（{vix_val:.1f}）进行情绪判断。"
    strategies.append(f"😰 情绪分析：{fg_view}")

    if vix_val < 15:
        vix_view = f"VIX 收于 {vix_val:.2f}，处于历史低位，适合持股，但需警惕黑天鹅风险。"
    elif vix_val < 20:
        vix_view = f"VIX 收于 {vix_val:.2f}，处于正常区间，市场风险可控，策略建议：{vix_strategy['tip']}。"
    elif vix_val < 30:
        vix_view = f"VIX 升至 {vix_val:.2f}，恐慌情绪升温，策略建议：{vix_strategy['tip']}。"
    else:
        vix_view = f"VIX 飙升至 {vix_val:.2f}，市场高度恐慌，VIX>30 往往预示阶段性底部临近，策略建议：{vix_strategy['tip']}。"
    strategies.append(f"⚡ VIX 信号：{vix_view}")

    rate_view = (f"十年期美债收益率收于 {tnx_val:.3f}%，处于高位，对成长股估值压制明显。" if tnx_val > 4.5
                 else f"十年期美债收益率收于 {tnx_val:.3f}%，利率中高位运行，成长股承压但尚在可接受范围。" if tnx_val > 4.0
                 else f"十年期美债收益率收于 {tnx_val:.3f}%，利率相对温和，有利于成长股估值修复。")
    dxy_view  = (f"美元指数今日上涨 {dxy_chg:.2f}%，强势美元对新兴市场和大宗商品形成压制。" if dxy_chg > 0.5
                 else f"美元指数今日下跌 {abs(dxy_chg):.2f}%，美元走弱有利于黄金和新兴市场资产。" if dxy_chg < -0.5
                 else f"美元指数今日变动 {dxy_chg:+.2f}%，基本稳定。")
    strategies.append(f"🏦 利率与美元：{rate_view} {dxy_view}")

    credit_view = (f"高收益债 HYG（{hyg_chg:+.2f}%）/ JNK（{jnk_chg:+.2f}%）今日上涨，信用市场流动性健康，风险偏好提升。" if avg_credit_chg > 0.3
                   else f"高收益债 HYG（{hyg_chg:+.2f}%）/ JNK（{jnk_chg:+.2f}%）今日下跌，信用溢价走阔，需警惕流动性收紧风险。" if avg_credit_chg < -0.3
                   else f"高收益债 HYG（{hyg_chg:+.2f}%）/ JNK（{jnk_chg:+.2f}%）今日基本持平，流动性状况稳定。")
    strategies.append(f"💧 流动性信号：{credit_view}")

    gold_view = (f"黄金今日上涨 {gold_chg:.2f}% 而股市下跌，避险资金明显流入黄金，建议适当增加防御性配置。" if gold_chg > 1.0 and sp500_chg < 0
                 else f"黄金今日上涨 {gold_chg:.2f}%，或反映通胀预期升温，关注 CPI 等经济数据。" if gold_chg > 1.0
                 else f"黄金今日下跌 {abs(gold_chg):.2f}%，避险需求减弱，市场风险偏好整体较好。" if gold_chg < -1.0
                 else f"黄金今日变动 {gold_chg:+.2f}%，避险情绪基本平稳。")
    strategies.append(f"🥇 避险信号：{gold_view}")

    bullish = sum([sp500_chg > 0, nasdaq_chg > 0, vix_val < 20,
                   isinstance(fg_score, int) and fg_score < 60,
                   avg_credit_chg > 0, tnx_val < 4.3])
    action  = ("多项指标偏多，市场整体健康，建议维持正常定投计划，持股待涨，不必追高。" if bullish >= 5
               else "多空信号混杂，建议保持现有仓位，谨慎追加，密切关注后续数据。" if bullish >= 3
               else "多项指标偏空，建议降低仓位，保留现金，等待市场企稳后再分批布局。")
    strategies.append(f"🎯 综合操作建议：{action}")

    return strategies

# ==========================================
# 8. 核心执行逻辑
# ==========================================
def main():
    print("正在抓取收盘数据...")
    data       = get_market_data()
    fg_data    = fetch_fear_greed()
    print("正在抓取走势图数据...")
    chart_data = get_chart_data()

    vix_val      = data['VIX']['price']
    vix_strategy = get_vix_strategy(vix_val)
    strategies   = generate_strategy(data, fg_data, vix_strategy)

    # ✅ 使用 yfinance 数据的实际时间戳，而非脚本运行时间
    data_dt     = get_data_timestamp()
    report_date = data_dt.strftime('%Y年%m月%d日 %H:%M ET')
    date_iso    = data_dt.strftime('%Y-%m-%d')

    print(f"Report date (from yfinance): {report_date}")

    summary_data = {
        "date":          report_date,
        "date_iso":      date_iso,
        "SP500_price":   f"{data['SP500']['price']:.2f}",
        "SP500_change":  f"{data['SP500']['change_pct']:.2f}",
        "NASDAQ_price":  f"{data['NASDAQ']['price']:.2f}",
        "NASDAQ_change": f"{data['NASDAQ']['change_pct']:.2f}",
        "VIX_price":     f"{vix_val:.2f}",
        "VIX_change":    f"{data['VIX']['change_pct']:.2f}",
        "VIX_Status":    vix_strategy['status'],
        "VIX_Tip":       vix_strategy['tip'],
        "FG_Score":      str(fg_data['FG_Score']),
        "FG_Status":     fg_data['FG_Status'],
        "HYG_price":     f"{data['HYG']['price']:.2f}",
        "HYG_change":    f"{data['HYG']['change_pct']:.2f}",
        "JNK_price":     f"{data['JNK']['price']:.2f}",
        "JNK_change":    f"{data['JNK']['change_pct']:.2f}",
        "TNX_price":     f"{data['TNX']['price']:.3f}%",
        "TNX_change":    f"{data['TNX']['change_pct']:.2f}",
        "GOLD_price":    f"{data['GOLD']['price']:.2f}",
        "GOLD_change":   f"{data['GOLD']['change_pct']:.2f}",
        "DXY_price":     f"{data['DXY']['price']:.2f}",
        "DXY_change":    f"{data['DXY']['change_pct']:.2f}",
        "strategies":    strategies,
        "charts":        chart_data,
    }

    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public')
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, 'data.json'), 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=4)

    def get_color(c): return "#16a34a" if c > 0 else "#dc2626"
    def get_arrow(c): return "▲" if c > 0 else "▼"
    strategy_rows = "".join([f"<li style='margin-bottom:8px;'>{s}</li>" for s in strategies])

    html_template = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <style>
        @page {{ size: A4; margin: 15mm 12mm; }}
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; line-height: 1.6; font-size: 10pt; }}
        .header {{ background-color: #1e3a8a; color: white; padding: 20px; margin: -15mm -12mm 20px -12mm; }}
        .header h1 {{ margin: 0 0 4px 0; font-size: 18pt; }}
        .disclaimer {{ font-size: 8pt; opacity: 0.6; margin-top: 4px; }}
        .section-title {{ font-size: 12pt; color: #1e3a8a; border-left: 4px solid #3b82f6; padding-left: 8px; margin: 18px 0 8px 0; font-weight: bold; }}
        .data-table {{ width: 100%; border-collapse: collapse; background-color: white; border: 1px solid #e2e8f0; }}
        .data-table th {{ background-color: #f1f5f9; padding: 8px 10px; text-align: left; font-size: 9pt; }}
        .data-table td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; font-size: 9pt; }}
        .strategy-box {{ background-color: #eff6ff; border-left: 4px solid #2563eb; padding: 14px 16px; margin-top: 8px; border-radius: 4px; }}
        .strategy-box ul {{ margin: 0; padding: 0 0 0 4px; list-style: none; }}
        .strategy-box li {{ font-size: 9pt; line-height: 1.7; color: #1e3a8a; }}
    </style></head><body>
    <div class="header">
        <h1>美股情绪观察每日报告</h1>
        <div style="font-size:10pt;opacity:0.85;">📅 数据时间：{report_date}</div>
        <div class="disclaimer">数据来自第三方（Yahoo Finance / CNN），由 AI 辅助生成，仅供参考，不构成任何投资建议</div>
    </div>
    <div class="section-title">1. 大盘核心指数</div>
    <table class="data-table">
        <tr><th>指数</th><th>收盘价</th><th>单日涨跌</th></tr>
        <tr><td>标普500 (S&P 500)</td><td>{summary_data['SP500_price']}</td>
            <td style="color:{get_color(data['SP500']['change_pct'])};">{get_arrow(data['SP500']['change_pct'])} {summary_data['SP500_change']}%</td></tr>
        <tr><td>纳斯达克综合 (NASDAQ)</td><td>{summary_data['NASDAQ_price']}</td>
            <td style="color:{get_color(data['NASDAQ']['change_pct'])};">{get_arrow(data['NASDAQ']['change_pct'])} {summary_data['NASDAQ_change']}%</td></tr>
    </table>
    <div class="section-title">2. 恐慌与情绪指标</div>
    <table class="data-table">
        <tr><th>指标</th><th>数值</th><th>涨跌</th><th>解读</th></tr>
        <tr><td>VIX 恐慌指数</td><td>{summary_data['VIX_price']}</td>
            <td style="color:{get_color(data['VIX']['change_pct'])};">{get_arrow(data['VIX']['change_pct'])} {summary_data['VIX_change']}%</td>
            <td>【{vix_strategy['status']}】{vix_strategy['tip']}</td></tr>
        <tr><td>恐惧与贪婪指数</td><td>{summary_data['FG_Score']}</td><td>—</td>
            <td>【{summary_data['FG_Status']}】</td></tr>
    </table>
    <div class="section-title">3. 高收益信用债（流动性）</div>
    <table class="data-table">
        <tr><th>ETF</th><th>收盘价</th><th>单日涨跌</th></tr>
        <tr><td>HYG</td><td>${summary_data['HYG_price']}</td>
            <td style="color:{get_color(data['HYG']['change_pct'])};">{get_arrow(data['HYG']['change_pct'])} {summary_data['HYG_change']}%</td></tr>
        <tr><td>JNK</td><td>${summary_data['JNK_price']}</td>
            <td style="color:{get_color(data['JNK']['change_pct'])};">{get_arrow(data['JNK']['change_pct'])} {summary_data['JNK_change']}%</td></tr>
    </table>
    <div class="section-title">4. 跨资产联动（宏观阻力）</div>
    <table class="data-table">
        <tr><th>资产</th><th>收盘价/收益率</th><th>单日涨跌</th></tr>
        <tr><td>十年期美债收益率</td><td>{summary_data['TNX_price']}</td>
            <td style="color:{get_color(data['TNX']['change_pct'])};">{get_arrow(data['TNX']['change_pct'])} {summary_data['TNX_change']}%</td></tr>
        <tr><td>黄金期货 (Gold)</td><td>${summary_data['GOLD_price']}</td>
            <td style="color:{get_color(data['GOLD']['change_pct'])};">{get_arrow(data['GOLD']['change_pct'])} {summary_data['GOLD_change']}%</td></tr>
        <tr><td>美元指数 (DXY)</td><td>{summary_data['DXY_price']}</td>
            <td style="color:{get_color(data['DXY']['change_pct'])};">{get_arrow(data['DXY']['change_pct'])} {summary_data['DXY_change']}%</td></tr>
    </table>
    <div class="section-title">5. 综合投资策略指引</div>
    <div class="strategy-box"><ul>{strategy_rows}</ul></div>
    </body></html>
    """
    HTML(string=html_template).write_pdf(os.path.join(output_dir, 'report.pdf'))
    print("✅ 完成！data.json 和 report.pdf 已生成。")

if __name__ == "__main__":
    main()
