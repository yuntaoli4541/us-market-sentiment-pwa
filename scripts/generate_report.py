import os
import json
import requests
import cloudscraper
import yfinance as yf
from weasyprint import HTML
from datetime import datetime

# ==========================================
# 1. 资产配置与数据抓取
# ==========================================
TICKERS = {
    'SP500': '^GSPC',    # 标普500
    'NASDAQ': '^IXIC',   # 纳斯达克
    'VIX': '^VIX',       # 恐慌指数
    'HYG': 'HYG',        # 高收益债ETF
    'JNK': 'JNK',        # 高收益债ETF
    'TNX': '^TNX',       # 十年期美债收益率
    'GOLD': 'GC=F',      # 黄金期货
    'DXY': 'DX-Y.NYB'    # 美元指数
}

def get_market_data():
    market_data = {}
    for name, ticker in TICKERS.items():
        try:
            df = yf.download(ticker, period="5d", progress=False)['Close']
            if len(df) >= 2:
                current_price = float(df.iloc[-1])
                prev_price = float(df.iloc[-2])
                change_pct = ((current_price - prev_price) / prev_price) * 100
                market_data[name] = {'price': current_price, 'change_pct': change_pct}
            else:
                market_data[name] = {'price': 0.0, 'change_pct': 0.0}
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            market_data[name] = {'price': 0.0, 'change_pct': 0.0}
    return market_data

def get_fear_and_greed():
    """使用 cloudscraper 访问 graphdata 接口获取最新恐惧贪婪指数"""
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    
    try:
        # 使用 cloudscraper 绕过防火墙拦截
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        
        # 抓取数据
        res = scraper.get(url, timeout=15)
        res.raise_for_status()
        j_data = res.json()
        
        # CNN 的 graphdata 接口返回的是一个字典，包含历史数据列表
        # 最新的一条数据在列表的最后一行 ([-1])
        latest_data = j_data['fear_and_greed_historical']['data'][-1]
        
        # 提取分数并四舍五入
        score = int(round(latest_data['score']))
        rating = latest_data['rating']
        
        # 将英文评级翻译成中文
        rating_map = {
            'extreme fear': '极度恐惧', 
            'fear': '恐惧',
            'neutral': '中立', 
            'greed': '贪婪', 
            'extreme greed': '极度贪婪'
        }
        
        return {"score": score, "status": rating_map.get(rating.lower(), rating)}
        
    except Exception as e:
        print(f"Error fetching Fear & Greed from graphdata: {e}")
        return {"score": "--", "status": "获取失败 (WAF拦截或接口变动)"}

def get_vix_strategy(vix_val):
    if vix_val < 12:
        return {"status": "极度乐观", "tip": "谨慎追高", "color": "#dc2626"}
    elif 12 <= vix_val < 20:
        return {"status": "正常区间", "tip": "常规定投", "color": "#15803d"}
    elif 20 <= vix_val < 30:
        return {"status": "恐惧上升", "tip": "加大定投", "color": "#a16207"}
    elif 30 <= vix_val < 50:
        return {"status": "市场恐慌", "tip": "加倍定投", "color": "#dc2626"}
    else:
        return {"status": "极度恐慌", "tip": "大胆抄底", "color": "#7f1d1d"}

# ==========================================
# 3. 核心执行逻辑
# ==========================================
def main():
    print("正在抓取全球资产及情绪数据...")
    data = get_market_data()
    fg_data = get_fear_and_greed()
    
    report_date = datetime.now().strftime('%Y年%m月%d日')
    vix_val = data['VIX']['price']
    vix_strategy = get_vix_strategy(vix_val)

    # 重构更细颗粒度的 JSON 数据字段，完美供应网页端
    summary_data = {
        "date": report_date,
        "SP500_price": f"{data['SP500']['price']:.2f}",
        "SP500_change": f"{data['SP500']['change_pct']:.2f}",
        "NASDAQ_price": f"{data['NASDAQ']['price']:.2f}",
        "NASDAQ_change": f"{data['NASDAQ']['change_pct']:.2f}",
        "VIX_price": f"{vix_val:.2f}",
        "VIX_change": f"{vix_change:.2f}" if 'vix_change' in locals() else f"{data['VIX']['change_pct']:.2f}",
        "VIX_Status": vix_strategy['status'],
        "VIX_Tip": vix_strategy['tip'],
        "FG_Score": str(fg_data['score']),
        "FG_Status": fg_data['status'],
        "HYG_price": f"{data['HYG']['price']:.2f}",
        "HYG_change": f"{data['HYG']['change_pct']:.2f}",
        "JNK_price": f"{data['JNK']['price']:.2f}",
        "JNK_change": f"{data['JNK']['change_pct']:.2f}",
        "TNX_price": f"{data['TNX']['price']:.3f}%",
        "TNX_change": f"{data['TNX']['change_pct']:.2f}",
        "GOLD_price": f"{data['GOLD']['price']:.2f}",
        "GOLD_change": f"{data['GOLD']['change_pct']:.2f}",
        "DXY_price": f"{data['DXY']['price']:.2f}",
        "DXY_change": f"{data['DXY']['change_pct']:.2f}"
    }

    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public')
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, 'data.json'), 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=4)

    # 同步生成格式完整的本地 PDF 备份
    def get_color(change): return "#16a34a" if change > 0 else "#dc2626"
    def get_arrow(change): return "▲" if change > 0 else "▼"

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8">
    <style>
        @page {{ size: A4; margin: 15mm 12mm; background-color: #f8fafc; }}
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; line-height: 1.5; }}
        .header {{ background-color: #1e3a8a; color: white; padding: 20px; margin: -15mm -12mm 20px -12mm; }}
        .section-title {{ font-size: 13pt; color: #1e3a8a; border-left: 4px solid #3b82f6; padding-left: 8px; margin: 20px 0 10px 0; font-weight: bold; }}
        .data-table {{ width: 100%; border-collapse: collapse; background-color: white; border: 1px solid #e2e8f0; }}
        .data-table th {{ background-color: #f1f5f9; padding: 10px; text-align: left; }}
        .data-table td {{ padding: 10px; border-bottom: 1px solid #f1f5f9; }}
        .strategy-box {{ background-color: #eff6ff; border-left: 4px solid #2563eb; padding: 15px; margin-top: 15px; }}
    </style>
    </head>
    <body>
    <div class="header"><h1>美股情绪观察每日报告</h1><div>日期：{report_date}</div></div>
    <div class="section-title">1. 大盘与情绪指标</div>
    <table class="data-table">
        <tr><th>核心资产</th><th>最新数据</th><th>涨跌幅</th><th>状态解读</th></tr>
        <tr><td>标普500指数</td><td>{summary_data['SP500_price']}</td><td style="color:{get_color(data['SP500']['change_pct'])};">{get_arrow(data['SP500']['change_pct'])} {summary_data['SP500_change']}%</td><td>-</td></tr>
        <tr><td>纳斯达克综合指数</td><td>{summary_data['NASDAQ_price']}</td><td style="color:{get_color(data['NASDAQ']['change_pct'])};">{get_arrow(data['NASDAQ']['change_pct'])} {summary_data['NASDAQ_change']}%</td><td>-</td></tr>
        <tr><td>VIX 恐慌指数</td><td>{summary_data['VIX_price']}</td><td style="color:{get_color(data['VIX']['change_pct'])};">{get_arrow(data['VIX']['change_pct'])} {summary_data['VIX_change']}%</td><td>【{vix_strategy['status']}】👉 {vix_strategy['tip']}</td></tr>
        <tr><td>恐惧与贪婪指数</td><td>{summary_data['FG_Score']}</td><td>-</td><td>市场当前状态：【{summary_data['FG_Status']}】</td></tr>
    </table>
    <div class="section-title">2. 信用债与跨资产联动</div>
    <table class="data-table">
        <tr><th>资产名称</th><th>收盘价/收益率</th><th>单日涨跌</th></tr>
        <tr><td>HYG 高收益债ETF</td><td>${summary_data['HYG_price']}</td><td style="color:{get_color(data['HYG']['change_pct'])};">{summary_data['HYG_change']}%</td></tr>
        <tr><td>JNK 高收益债ETF</td><td>${summary_data['JNK_price']}</td><td style="color:{get_color(data['JNK']['change_pct'])};">{summary_data['JNK_change']}%</td></tr>
        <tr><td>十年期美债收益率</td><td>{summary_data['TNX_price']}</td><td style="color:{get_color(data['TNX']['change_pct'])};">{summary_data['TNX_change']}%</td></tr>
        <tr><td>黄金期货 (Gold)</td><td>${summary_data['GOLD_price']}</td><td style="color:{get_color(data['GOLD']['change_pct'])};">{summary_data['GOLD_change']}%</td></tr>
        <tr><td>美元指数 (DXY)</td><td>{summary_data['DXY_price']}</td><td style="color:{get_color(data['DXY']['change_pct'])};">{summary_data['DXY_change']}%</td></tr>
    </table>
    </body>
    </html>
    """
    HTML(string=html_template).write_pdf(os.path.join(output_dir, 'report.pdf'))
    print("✅ 脚本执行成功，数据与PDF已生成！")

if __name__ == "__main__":
    main()
