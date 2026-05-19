import os
import json
import requests
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
    'DXY':    'DX-Y.NYB'
}

# ==========================================
# 2. 判断当前是否在美股交易时间内
# ==========================================
def is_market_open():
    """
    判断当前 UTC 时间是否处于美股交易时段：
      - 夏令时 EDT (UTC-4)：13:30-20:00 UTC
      - 冬令时 EST (UTC-5)：14:30-21:00 UTC
    用宽松窗口 13:20-21:10 UTC 覆盖两个时区，周一到周五。
    """
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:          # 周六/周日
        return False
    market_start = now_utc.replace(hour=13, minute=20, second=0, microsecond=0)
    market_end   = now_utc.replace(hour=21, minute=10, second=0, microsecond=0)
    return market_start <= now_utc <= market_end

# ==========================================
# 3. 抓取市场数据（实时 or 收盘自适应）
# ==========================================
def get_market_data():
    """
    使用 yf.Ticker.fast_info 获取实时价格与前收盘价。
    比 yf.download 更快更准，盘中也能拿到当前价。
    """
    market_data = {}
    for name, sym in TICKERS.items():
        try:
            t    = yf.Ticker(sym)
            info = t.fast_info

            # fast_info 字段在不同 yfinance 版本略有差异，做容错处理
            current = (
                getattr(info, 'last_price', None) or
                getattr(info, 'regularMarketPrice', None)
            )
            prev = (
                getattr(info, 'previous_close', None) or
                getattr(info, 'regularMarketPreviousClose', None)
            )

            if current and prev and prev != 0:
                change_pct = ((current - prev) / prev) * 100
                market_data[name] = {'price': float(current), 'change_pct': float(change_pct)}
            else:
                # fast_info 拿不到时回退到 yf.download（日线数据）
                df = yf.download(sym, period="5d", progress=False)['Close']
                if len(df) >= 2:
                    cur  = float(df.iloc[-1].iloc[0])
                    prv  = float(df.iloc[-2].iloc[0])
                    market_data[name] = {'price': cur, 'change_pct': ((cur - prv) / prv) * 100}
                else:
                    market_data[name] = {'price': 0.0, 'change_pct': 0.0}

        except Exception as e:
            print(f"Warning: Error fetching {name} ({sym}): {e}")
            market_data[name] = {'price': 0.0, 'change_pct': 0.0}

    return market_data

# ==========================================
# 4. CNN 恐惧与贪婪指数（含备用方案）
# ==========================================
def fetch_fear_greed():
    rating_map = {
        "Extreme Fear":  "极度恐惧",
        "Fear":          "恐惧",
        "Neutral":       "中性",
        "Greed":         "贪婪",
        "Extreme Greed": "极度贪婪",
    }

    # 主方案：CNN 官方内部 API
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36",
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
        print(f"CNN F&G fetched: {score} ({rating})")
        return {"FG_Score": score, "FG_Status": rating_map.get(rating, rating)}
    except Exception as e:
        print(f"Warning: CNN primary failed: {e}, switching to backup...")

    # 备用方案：alternative.me（无 CORS / 无需特殊 headers）
    try:
        resp  = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d     = resp.json()
        score = int(d["data"][0]["value"])
        cls   = d["data"][0]["value_classification"]
        print(f"alternative.me F&G fetched: {score} ({cls})")
        return {"FG_Score": score, "FG_Status": rating_map.get(cls, cls)}
    except Exception as e:
        print(f"Error: Backup also failed: {e}")
        return {"FG_Score": "N/A", "FG_Status": "获取失败"}

# ==========================================
# 5. VIX 策略映射
# ==========================================
def get_vix_strategy(vix_val):
    if vix_val < 12:
        return {"status": "极度乐观", "tip": "谨慎追高", "color": "#dc2626"}
    elif vix_val < 20:
        return {"status": "正常区间", "tip": "常规定投", "color": "#15803d"}
    elif vix_val < 30:
        return {"status": "恐惧上升", "tip": "加大定投", "color": "#a16207"}
    elif vix_val < 50:
        return {"status": "市场恐慌", "tip": "加倍定投", "color": "#dc2626"}
    else:
        return {"status": "极度恐慌", "tip": "大胆抄底", "color": "#7f1d1d"}

# ==========================================
# 6. 核心执行逻辑
# ==========================================
def main():
    market_open  = is_market_open()
    status_label = "盘中实时" if market_open else "收盘数据"
    print(f"Market status: {'OPEN - fetching live data' if market_open else 'CLOSED - recording closing snapshot'}")

    data    = get_market_data()
    fg_data = fetch_fear_greed()

    # 时间戳：开盘中显示具体时间，休市显示"收盘"
    now_et = datetime.now(timezone(timedelta(hours=-4)))  # EDT，夏令时
    if market_open:
        report_date = now_et.strftime('%Y年%m月%d日 %H:%M ET（盘中）')
    else:
        report_date = now_et.strftime('%Y年%m月%d日 收盘快照')

    vix_val      = data['VIX']['price']
    vix_strategy = get_vix_strategy(vix_val)

    summary_data = {
        "date":          report_date,
        "market_status": status_label,      # 网页端可用此字段显示"盘中/收盘"标签
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
    }

    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public')
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, 'data.json'), 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=4)

    # PDF 报告
    def get_color(change): return "#16a34a" if change > 0 else "#dc2626"
    def get_arrow(change): return "▲" if change > 0 else "▼"

    html_template = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <style>
        @page {{ size: A4; margin: 15mm 12mm; }}
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; line-height: 1.5; }}
        .header {{ background-color: #1e3a8a; color: white; padding: 20px; margin: -15mm -12mm 20px -12mm; }}
        .badge {{ display: inline-block; background: {'#dcfce7' if market_open else '#f1f5f9'}; color: {'#15803d' if market_open else '#64748b'}; padding: 2px 10px; border-radius: 99px; font-size: 11pt; margin-top: 6px; }}
        .section-title {{ font-size: 13pt; color: #1e3a8a; border-left: 4px solid #3b82f6; padding-left: 8px; margin: 20px 0 10px 0; font-weight: bold; }}
        .data-table {{ width: 100%; border-collapse: collapse; background-color: white; border: 1px solid #e2e8f0; }}
        .data-table th {{ background-color: #f1f5f9; padding: 10px; text-align: left; }}
        .data-table td {{ padding: 10px; border-bottom: 1px solid #f1f5f9; }}
    </style></head><body>
    <div class="header">
        <h1>美股情绪观察每日报告</h1>
        <div>日期：{report_date}</div>
        <div class="badge">{'🟢 盘中实时' if market_open else '⚫ 收盘快照'}</div>
    </div>
    <div class="section-title">1. 大盘与情绪指标</div>
    <table class="data-table">
        <tr><th>核心资产</th><th>最新数据</th><th>涨跌幅</th><th>状态解读</th></tr>
        <tr><td>标普500</td><td>{summary_data['SP500_price']}</td>
            <td style="color:{get_color(data['SP500']['change_pct'])};">{get_arrow(data['SP500']['change_pct'])} {summary_data['SP500_change']}%</td><td>-</td></tr>
        <tr><td>纳斯达克</td><td>{summary_data['NASDAQ_price']}</td>
            <td style="color:{get_color(data['NASDAQ']['change_pct'])};">{get_arrow(data['NASDAQ']['change_pct'])} {summary_data['NASDAQ_change']}%</td><td>-</td></tr>
        <tr><td>VIX 恐慌指数</td><td>{summary_data['VIX_price']}</td>
            <td style="color:{get_color(data['VIX']['change_pct'])};">{get_arrow(data['VIX']['change_pct'])} {summary_data['VIX_change']}%</td>
            <td>【{vix_strategy['status']}】👉 {vix_strategy['tip']}</td></tr>
        <tr><td>恐惧与贪婪指数</td><td>{summary_data['FG_Score']}</td><td>-</td>
            <td>【{summary_data['FG_Status']}】</td></tr>
    </table>
    <div class="section-title">2. 信用债与跨资产联动</div>
    <table class="data-table">
        <tr><th>资产名称</th><th>价格/收益率</th><th>单日涨跌</th></tr>
        <tr><td>HYG</td><td>${summary_data['HYG_price']}</td>
            <td style="color:{get_color(data['HYG']['change_pct'])};">{summary_data['HYG_change']}%</td></tr>
        <tr><td>JNK</td><td>${summary_data['JNK_price']}</td>
            <td style="color:{get_color(data['JNK']['change_pct'])};">{summary_data['JNK_change']}%</td></tr>
        <tr><td>十年期美债收益率</td><td>{summary_data['TNX_price']}</td>
            <td style="color:{get_color(data['TNX']['change_pct'])};">{summary_data['TNX_change']}%</td></tr>
        <tr><td>黄金期货</td><td>${summary_data['GOLD_price']}</td>
            <td style="color:{get_color(data['GOLD']['change_pct'])};">{summary_data['GOLD_change']}%</td></tr>
        <tr><td>美元指数 DXY</td><td>{summary_data['DXY_price']}</td>
            <td style="color:{get_color(data['DXY']['change_pct'])};">{summary_data['DXY_change']}%</td></tr>
    </table>
    </body></html>
    """
    HTML(string=html_template).write_pdf(os.path.join(output_dir, 'report.pdf'))
    print("Done! data.json and report.pdf generated.")

if __name__ == "__main__":
    main()
