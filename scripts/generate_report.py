import os
import json
import yfinance as yf
from weasyprint import HTML
from datetime import datetime, timedelta

# ==========================================
# 1. 资产配置与数据抓取函数
# ==========================================
# 您需要追踪的资产 Ticker
TICKERS = {
    'SP500': '^GSPC',    # 标普500
    'NASDAQ': '^IXIC',   # 纳斯达克综合
    'VIX': '^VIX',       # 恐慌指数
    'HYG': 'HYG',        # 高收益债ETF
    'JNK': 'JNK',        # 高收益债ETF
    'TNX': '^TNX',       # 十年期美债收益率
    'GOLD': 'GC=F',      # 黄金期货
    'DXY': 'DX-Y.NYB'    # 美元指数
}

def get_market_data():
    """使用 yfinance 获取过去两个交易日的数据，以计算单日涨跌幅"""
    market_data = {}
    for name, ticker in TICKERS.items():
        try:
            # 下载最近5天的数据以确保能拿到最近两个有效交易日
            df = yf.download(ticker, period="5d", progress=False)['Close']
            if len(df) >= 2:
                current_price = float(df.iloc[-1])
                prev_price = float(df.iloc[-2])
                change_pct = ((current_price - prev_price) / prev_price) * 100
                market_data[name] = {
                    'price': current_price,
                    'change_pct': change_pct
                }
            else:
                market_data[name] = {'price': 0.0, 'change_pct': 0.0}
        except Exception as e:
            print(f"Error fetching data for {name}: {e}")
            market_data[name] = {'price': 0.0, 'change_pct': 0.0}
    return market_data

# ==========================================
# 2. 策略逻辑判断函数
# ==========================================
def get_vix_strategy(vix_val):
    """根据您定义的 VIX 区间返回操作提示"""
    if vix_val < 12:
        return {"status": "极度乐观", "tip": "谨慎追高", "color": "#dc2626"} # Red
    elif 12 <= vix_val < 20:
        return {"status": "正常区间", "tip": "常规定投", "color": "#15803d"} # Green
    elif 20 <= vix_val < 30:
        return {"status": "恐惧上升", "tip": "加大定投", "color": "#a16207"} # Yellow/Orange
    elif 30 <= vix_val < 50:
        return {"status": "市场恐慌", "tip": "加倍定投", "color": "#dc2626"} # Red
    else:
        return {"status": "极度恐慌", "tip": "大胆抄底", "color": "#7f1d1d"} # Dark Red

# ==========================================
# 3. 核心执行逻辑
# ==========================================
def main():
    print("开始获取市场数据...")
    data = get_market_data()
    
    # 获取日期 (格式化为 美东时间 YYYY年MM月DD日)
    report_date = datetime.now().strftime('%Y年%m月%d日')
    
    # 获取 VIX 策略
    vix_val = data['VIX']['price']
    vix_change = data['VIX']['change_pct']
    vix_strategy = get_vix_strategy(vix_val)

    # 准备要在前端渲染和在 HTML 模板中使用的 JSON 数据
    summary_data = {
        "date": report_date,
        "SP500": f"{data['SP500']['price']:.2f} ({data['SP500']['change_pct']:.2f}%)",
        "NASDAQ": f"{data['NASDAQ']['price']:.2f} ({data['NASDAQ']['change_pct']:.2f}%)",
        "VIX": f"{vix_val:.2f} ({vix_change:.2f}%)",
        "VIX_Status": vix_strategy['status'],
        "VIX_Tip": vix_strategy['tip'],
        "HYG": f"${data['HYG']['price']:.2f} ({data['HYG']['change_pct']:.2f}%)",
        "JNK": f"${data['JNK']['price']:.2f} ({data['JNK']['change_pct']:.2f}%)",
        "TNX": f"{data['TNX']['price']:.3f}%",
        "GOLD": f"${data['GOLD']['price']:.2f}",
        "DXY": f"{data['DXY']['price']:.2f}"
    }

    # 确保输出目录存在
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public')
    os.makedirs(output_dir, exist_ok=True)

    # 写入 data.json 供前端 PWA Dashboard 使用
    json_path = os.path.join(output_dir, 'data.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=4)
    print(f"✅ data.json 已生成在 {json_path}")

    # ==========================================
    # 4. 生成 HTML 并转换为 PDF
    # ==========================================
    # 定义基础颜色的辅助函数
    def get_color(change):
        return "#16a34a" if change > 0 else "#dc2626"
    
    def get_arrow(change):
        return "▲" if change > 0 else "▼"

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        @page {{ size: A4; margin: 15mm 12mm; background-color: #f8fafc; }}
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; line-height: 1.5; font-size: 10.5pt; }}
        .header {{ background-color: #1e3a8a; color: white; padding: 22px 20px; margin: -15mm -12mm 20px -12mm; }}
        .header h1 {{ margin: 0; font-size: 18pt; }}
        .section-title {{ font-size: 13pt; color: #1e3a8a; border-left: 4px solid #3b82f6; padding-left: 8px; margin: 22px 0 12px 0; font-weight: bold; }}
        .data-table {{ width: 100%; border-collapse: collapse; background-color: white; border: 1px solid #e2e8f0; border-radius: 6px; }}
        .data-table th {{ background-color: #f1f5f9; padding: 10px 14px; text-align: left; font-weight: bold; }}
        .data-table td {{ padding: 11px 14px; border-bottom: 1px solid #f1f5f9; }}
        .strategy-box {{ background-color: #eff6ff; border-left: 4px solid #2563eb; padding: 16px; border-radius: 0 6px 6px 0; margin-top: 15px; }}
    </style>
    </head>
    <body>
    <div class="header">
        <h1>美股情绪观察每日报告</h1>
        <div>报告日期：{report_date} (美东收盘切片)</div>
    </div>

    <div class="section-title">1. 大盘与情绪核心指标</div>
    <table class="data-table">
        <tr><th>指标</th><th>最新数值</th><th>日内变动</th><th>状态解读</th></tr>
        <tr>
            <td><strong>标普500 (S&P 500)</strong></td>
            <td>{data['SP500']['price']:.2f}</td>
            <td style="color: {get_color(data['SP500']['change_pct'])};">{get_arrow(data['SP500']['change_pct'])} {data['SP500']['change_pct']:.2f}%</td>
            <td>-</td>
        </tr>
        <tr>
            <td><strong>纳斯达克 (NASDAQ)</strong></td>
            <td>{data['NASDAQ']['price']:.2f}</td>
            <td style="color: {get_color(data['NASDAQ']['change_pct'])};">{get_arrow(data['NASDAQ']['change_pct'])} {data['NASDAQ']['change_pct']:.2f}%</td>
            <td>-</td>
        </tr>
        <tr>
            <td><strong>VIX 恐慌指数</strong></td>
            <td>{vix_val:.2f}</td>
            <td style="color: {get_color(vix_change)};">{get_arrow(vix_change)} {vix_change:.2f}%</td>
            <td><span style="color: {vix_strategy['color']}; font-weight: bold;">【{vix_strategy['status']}】</span> 操作提示：<strong>{vix_strategy['tip']}</strong></td>
        </tr>
    </table>

    <div class="section-title">2. 信用债与跨资产联动</div>
    <table class="data-table">
        <tr><th>资产</th><th>最新价/收益率</th><th>日内变动</th></tr>
        <tr>
            <td><strong>HYG (高收益债)</strong></td>
            <td>${data['HYG']['price']:.2f}</td>
            <td style="color: {get_color(data['HYG']['change_pct'])};">{get_arrow(data['HYG']['change_pct'])} {data['HYG']['change_pct']:.2f}%</td>
        </tr>
        <tr>
            <td><strong>十年期美债 (TNX)</strong></td>
            <td>{data['TNX']['price']:.3f}%</td>
            <td style="color: {get_color(data['TNX']['change_pct'])};">{get_arrow(data['TNX']['change_pct'])} {data['TNX']['change_pct']:.2f}%</td>
        </tr>
        <tr>
            <td><strong>黄金 (Gold)</strong></td>
            <td>${data['GOLD']['price']:.2f}</td>
            <td style="color: {get_color(data['GOLD']['change_pct'])};">{get_arrow(data['GOLD']['change_pct'])} {data['GOLD']['change_pct']:.2f}%</td>
        </tr>
        <tr>
            <td><strong>美元指数 (DXY)</strong></td>
            <td>{data['DXY']['price']:.2f}</td>
            <td style="color: {get_color(data['DXY']['change_pct'])};">{get_arrow(data['DXY']['change_pct'])} {data['DXY']['change_pct']:.2f}%</td>
        </tr>
    </table>

    <div class="section-title">3. 投资策略总结</div>
    <div class="strategy-box">
        <h4 style="margin-top:0;">💡 今日策略研判</h4>
        <p>基于当前 <strong>VIX ({vix_val:.2f})</strong> 处于<strong>【{vix_strategy['status']}】</strong>状态，核心操作策略指向：<strong>{vix_strategy['tip']}</strong>。</p>
        <p><em>(注：恐惧与贪婪指数数据因需抓取 CNN 页面结构较复杂，建议在前端手动输入或后续加入专用爬虫模块集成。)</em></p>
    </div>
    </body>
    </html>
    """

    pdf_path = os.path.join(output_dir, 'report.pdf')
    HTML(string=html_template).write_pdf(pdf_path)
    print(f"✅ 情绪观察报告 PDF 已生成在 {pdf_path}")

if __name__ == "__main__":
    main()
