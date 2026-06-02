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

ET = timezone(timedelta(hours=-4))

# ==========================================
# 2. 获取 yfinance 数据实际时间戳
# ==========================================
def get_data_timestamp():
    try:
        info = yf.Ticker('^GSPC').fast_info
        ts   = getattr(info, 'regular_market_time', None)
        if ts is not None:
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            else:
                dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            dt_et = dt.astimezone(ET)
            print(f"Data timestamp: {dt_et.strftime('%Y-%m-%d %H:%M ET')}")
            return dt_et
    except Exception as e:
        print(f"Warning: could not get market time: {e}")
    try:
        df   = yf.download('^GSPC', period="5d", interval="1d", progress=False)
        last = df.index[-1]
        dt   = datetime(last.year, last.month, last.day, 16, 0, 0, tzinfo=ET)
        return dt
    except:
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
# 4. 抓取走势图数据
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
               "%m/%d %H:%M" if interval in ('5m', '15m', '30m') else "%m/%d")
        return [
            {"t": ts.strftime(fmt), "v": round(float(v), 4)}
            for ts, v in zip(idx, close) if not pd.isna(v)
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
# 5. 从走势数据提取趋势指标
# ==========================================
def calc_trend(chart_data, key):
    """
    返回：
      5d_chg  : 近五日涨跌幅 (%)
      1mo_chg : 近一个月涨跌幅 (%)
      momentum: 近半段 5d 相对前半段的变化（判断动能加速/减速）
    """
    result = {'5d_chg': None, '1mo_chg': None, 'momentum': 'flat'}

    try:
        pts = chart_data.get(key, {}).get('5d', [])
        if len(pts) >= 4:
            first, last = pts[0]['v'], pts[-1]['v']
            if first != 0:
                result['5d_chg'] = (last - first) / first * 100
            mid       = len(pts) // 2
            first_half_chg = (pts[mid]['v'] - pts[0]['v'])   / pts[0]['v']   * 100 if pts[0]['v']   != 0 else 0
            second_half_chg= (pts[-1]['v']  - pts[mid]['v']) / pts[mid]['v'] * 100 if pts[mid]['v'] != 0 else 0
            if second_half_chg > first_half_chg + 0.3:
                result['momentum'] = 'accelerating'
            elif second_half_chg < first_half_chg - 0.3:
                result['momentum'] = 'decelerating'
            else:
                result['momentum'] = 'stable'
    except:
        pass

    try:
        pts = chart_data.get(key, {}).get('1mo', [])
        if len(pts) >= 2:
            first, last = pts[0]['v'], pts[-1]['v']
            if first != 0:
                result['1mo_chg'] = (last - first) / first * 100
    except:
        pass

    return result

def fmt_trend(chg):
    """格式化趋势文字"""
    if chg is None:
        return "趋势数据不足"
    sign = "上涨" if chg > 0 else "下跌"
    return f"近期{sign} {abs(chg):.1f}%"

# ==========================================
# 6. CNN 恐惧与贪婪指数
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
        print(f"Warning: CNN F&G failed: {e}")
    try:
        resp  = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d     = resp.json()
        score = int(d["data"][0]["value"])
        cls   = d["data"][0]["value_classification"]
        return {"FG_Score": score, "FG_Status": rating_map.get(cls, cls)}
    except:
        return {"FG_Score": "N/A", "FG_Status": "获取失败"}

# ==========================================
# 7. VIX 策略映射
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
# 8. 每日复盘结构化洞察
# ==========================================
def _num(value):
    """Parse numbers from strings such as '4.20%' or '1,234.5'."""
    try:
        return float(str(value).replace('%', '').replace(',', '').strip())
    except Exception:
        return None


def allocation_for_score(score):
    if score >= 8:
        return "7-8成"
    if score >= 6.5:
        return "5-6成"
    if score >= 4:
        return "3-4成"
    if score >= 2.5:
        return "2成以内"
    return "现金为主"


def build_decision_summary(score, bias, data, fg_score):
    """Build the top-of-page one-glance decision card."""
    score_f = float(score)
    vix = data.get('VIX', {}).get('price', 0)
    vix_chg = data.get('VIX', {}).get('change_pct', 0)
    sp_chg = data.get('SP500', {}).get('change_pct', 0)
    tnx = data.get('TNX', {}).get('price', 0)
    hyg_chg = data.get('HYG', {}).get('change_pct', 0)
    jnk_chg = data.get('JNK', {}).get('change_pct', 0)

    if score_f >= 8:
        headline = "强势偏多，适合主动参与，但仍需分批执行"
    elif score_f >= 6.5:
        headline = "偏多但不宜追高，回调分批加仓更合适"
    elif score_f >= 4:
        headline = "震荡观察，等待趋势和信用信号共振"
    elif score_f >= 2.5:
        headline = "偏空防守，优先控制回撤和流动性风险"
    else:
        headline = "风险释放中，现金和防守优先"

    drivers = []
    risks = []
    if sp_chg > 0:
        drivers.append(f"标普当日收涨 {sp_chg:+.2f}%")
    else:
        risks.append(f"标普当日回落 {sp_chg:+.2f}%")
    if vix < 20 and vix_chg <= 0:
        drivers.append(f"VIX {vix:.1f} 且回落，波动压力温和")
    elif vix >= 20:
        risks.append(f"VIX {vix:.1f} 上破 20，恐慌升温")
    if (hyg_chg + jnk_chg) / 2 > 0:
        drivers.append("高收益债同步企稳，信用环境尚可")
    else:
        risks.append("高收益债偏弱，需观察信用风险")
    if tnx > 4.7:
        risks.append(f"十年期美债 {tnx:.2f}% 高于 4.7%，估值压力较大")
    elif tnx > 4.2:
        risks.append(f"十年期美债 {tnx:.2f}% 仍在中高位")
    if isinstance(fg_score, int) and fg_score >= 75:
        risks.append(f"恐惧贪婪 {fg_score} 接近过热")

    return {
        "headline": headline,
        "score": f"{score_f:.1f}",
        "bias": bias,
        "allocation": allocation_for_score(score_f),
        "primary_driver": "；".join(drivers[:2]) if drivers else "暂无明显单一驱动，等待更多确认",
        "primary_risk": "；".join(risks[:2]) if risks else "主要风险暂未显著暴露，但仍需避免追高",
    }


def build_watchlist_triggers(data):
    """Rules to watch after today's report."""
    vix = data.get('VIX', {}).get('price', 0)
    tnx = data.get('TNX', {}).get('price', 0)
    hyg = data.get('HYG', {}).get('change_pct', 0)
    jnk = data.get('JNK', {}).get('change_pct', 0)
    dxy = data.get('DXY', {}).get('change_pct', 0)
    credit_weak = hyg < -0.2 and jnk < -0.2
    return [
        {"label": "VIX 上破 20", "active": vix >= 20, "detail": "短线波动和避险需求升温，追高需暂停。"},
        {"label": "VIX 上破 30", "active": vix >= 30, "detail": "进入明显恐慌区，可转为分批逆向观察。"},
        {"label": "TNX 上破 4.7%", "active": tnx >= 4.7, "detail": "利率对成长股估值形成更强压制。"},
        {"label": "HYG/JNK 同步走弱", "active": credit_weak, "detail": "信用市场若连续走弱，权益风险质量下降。"},
        {"label": "美元单日快速走强", "active": dxy >= 0.7, "detail": "强美元可能压制商品、新兴市场和跨国公司盈利预期。"},
    ]


def compare_metric_snapshots(current, previous):
    if not previous:
        return []
    specs = [
        ("SP500_price", "标普500", "指数点位", "higher_good"),
        ("NASDAQ_price", "纳斯达克", "指数点位", "higher_good"),
        ("VIX_price", "VIX", "恐慌指数", "lower_good"),
        ("FG_Score", "恐惧贪婪", "情绪分数", "neutral_middle"),
        ("TNX_price", "十年期美债", "收益率", "lower_good"),
    ]
    changes = []
    for key, label, unit, mode in specs:
        cur = _num(current.get(key))
        prev = _num(previous.get(key))
        if cur is None or prev is None:
            continue
        delta = cur - prev
        if abs(delta) < 1e-9:
            direction = "flat"
        else:
            direction = "up" if delta > 0 else "down"
        if mode == "higher_good":
            tone = "positive" if delta > 0 else "negative" if delta < 0 else "neutral"
        elif mode == "lower_good":
            tone = "positive" if delta < 0 else "negative" if delta > 0 else "neutral"
        else:
            tone = "positive" if 45 <= cur <= 70 else "negative" if cur >= 80 or cur <= 25 else "neutral"
        changes.append({
            "key": key,
            "label": label,
            "unit": unit,
            "previous": f"{prev:.2f}",
            "current": f"{cur:.2f}",
            "delta": f"{delta:+.2f}",
            "direction": direction,
            "tone": tone,
        })
    return changes


def build_score_history(date_iso, score, previous, bias, limit=30):
    history = []
    if previous:
        for item in previous.get('score_history', []):
            if item.get('date') != date_iso:
                history.append(item)
    history.append({"date": date_iso, "score": round(float(score), 1), "bias": bias})
    return history[-limit:]


def build_sector_rotation(data):
    """Lightweight relative-performance view using available index proxies."""
    sp = data.get('SP500', {}).get('change_pct', 0)
    nd = data.get('NASDAQ', {}).get('change_pct', 0)
    credit = (data.get('HYG', {}).get('change_pct', 0) + data.get('JNK', {}).get('change_pct', 0)) / 2
    growth_gap = nd - sp
    if growth_gap > 0.4:
        leadership = "成长/科技相对占优"
    elif growth_gap < -0.4:
        leadership = "大盘宽基强于科技成长"
    else:
        leadership = "科技与大盘表现接近"
    return {
        "leadership": leadership,
        "growth_gap": f"{growth_gap:+.2f}%",
        "credit_tone": "信用环境支撑风险资产" if credit > 0 else "信用环境偏谨慎",
        "notes": [
            f"纳指相对标普：{growth_gap:+.2f}%",
            f"高收益债平均表现：{credit:+.2f}%",
        ]
    }

# ==========================================
# 9. 专业交易员视角的综合策略分析
# ==========================================
def generate_strategy(data, fg_data, vix_strategy, chart_data):
    """
    以拥有10年以上金融行业经验的股票交易员视角，
    结合当日数据、近五日和近一个月走势，逐项分析并给出投资建议。
    """
    # 基础数据
    sp500_px   = data['SP500']['price']
    sp500_chg  = data['SP500']['change_pct']
    nasdaq_px  = data['NASDAQ']['price']
    nasdaq_chg = data['NASDAQ']['change_pct']
    vix_val    = data['VIX']['price']
    vix_chg    = data['VIX']['change_pct']
    tnx_val    = data['TNX']['price']
    tnx_chg    = data['TNX']['change_pct']
    gold_px    = data['GOLD']['price']
    gold_chg   = data['GOLD']['change_pct']
    dxy_px     = data['DXY']['price']
    dxy_chg    = data['DXY']['change_pct']
    hyg_chg    = data['HYG']['change_pct']
    jnk_chg    = data['JNK']['change_pct']
    fg_score   = fg_data['FG_Score']
    fg_status  = fg_data['FG_Status']

    # 走势趋势数据
    t_sp500  = calc_trend(chart_data, 'SP500')
    t_nasdaq = calc_trend(chart_data, 'NASDAQ')
    t_vix    = calc_trend(chart_data, 'VIX')
    t_tnx    = calc_trend(chart_data, 'TNX')
    t_gold   = calc_trend(chart_data, 'GOLD')
    t_dxy    = calc_trend(chart_data, 'DXY')
    t_hyg    = calc_trend(chart_data, 'HYG')

    strategies = []

    # ── 1. 大盘走势分析 ──────────────────────────────────────
    sp_5d  = t_sp500['5d_chg']
    sp_1mo = t_sp500['1mo_chg']
    nd_5d  = t_nasdaq['5d_chg']
    nd_1mo = t_nasdaq['1mo_chg']

    # 判断趋势结构
    if sp_5d is not None and sp_1mo is not None:
        if sp500_chg > 0 and sp_5d > 0 and sp_1mo > 0:
            trend_struct = f"短中长三周期全面偏多——五日涨 {sp_5d:.1f}%，月内涨 {sp_1mo:.1f}%，今日继续收涨 {sp500_chg:.2f}%，多头趋势结构完整。"
        elif sp500_chg > 0 and sp_5d < 0:
            trend_struct = f"今日收涨 {sp500_chg:.2f}%，但五日维度仍下跌 {abs(sp_5d):.1f}%，属于下跌趋势中的技术性反弹，需警惕反弹高度有限。"
        elif sp500_chg < 0 and sp_5d > 0:
            trend_struct = f"今日回调 {abs(sp500_chg):.2f}%，但五日维度仍上涨 {sp_5d:.1f}%，为强势上涨后的正常回踩，可视为短期布局机会。"
        elif sp500_chg < 0 and sp_5d < 0 and sp_1mo < 0:
            trend_struct = f"今日收跌 {abs(sp500_chg):.2f}%，五日跌 {abs(sp_5d):.1f}%，月内跌 {abs(sp_1mo):.1f}%，三周期空头排列，趋势性下行压力较大，应控制仓位。"
        else:
            trend_struct = f"今日标普500 {sp500_chg:+.2f}%，五日 {fmt_trend(sp_5d)}，月内 {fmt_trend(sp_1mo)}，多空信号交织，市场处于震荡整理阶段。"
    else:
        trend_struct = f"今日标普500 {sp500_chg:+.2f}%，纳斯达克 {nasdaq_chg:+.2f}%。"

    # 纳指与标普的分化
    divergence = ""
    if nd_5d is not None and sp_5d is not None:
        diff = nd_5d - sp_5d
        if diff > 2:
            divergence = f"科技/成长股（纳指五日 {nd_5d:+.1f}% vs 标普 {sp_5d:+.1f}%）表现明显强于大盘，市场风险偏好集中于成长赛道。"
        elif diff < -2:
            divergence = f"纳指五日 {nd_5d:+.1f}% 弱于标普 {sp_5d:+.1f}%，科技股相对承压，市场资金有向价值/防御板块轮动的迹象。"

    sp_analysis = f"📊 大盘走势：{trend_struct}"
    if divergence:
        sp_analysis += f" {divergence}"
    strategies.append(sp_analysis)

    # ── 2. 情绪面：VIX + F&G 联合分析 ──────────────────────
    vix_5d  = t_vix['5d_chg']
    vix_1mo = t_vix['1mo_chg']

    # VIX 水平与方向
    if vix_val < 13:
        vix_level = f"VIX 仅 {vix_val:.1f}，处于历史低位区间，市场完全处于自满状态。从逆向角度看，此类低波动往往是大跌前的平静期，需警惕尾部风险。"
    elif vix_val < 18:
        vix_level = f"VIX {vix_val:.1f}，处于正常偏低区间，市场波动预期温和，整体风险偏好良好。"
    elif vix_val < 25:
        vix_level = f"VIX {vix_val:.1f}，恐慌情绪开始升温，已进入历史均值上方区域，操盘时需适当缩减仓位，增加对冲。"
    elif vix_val < 35:
        vix_level = f"VIX {vix_val:.1f}，市场进入高恐慌区间。历史数据显示，VIX 25-35 区间往往对应阶段性底部附近，此时反向布局的胜率显著提升。"
    else:
        vix_level = f"VIX 飙升至 {vix_val:.1f}，进入极度恐慌领域（历史上仅在金融危机、疫情冲击等系统性风险事件中出现）。市场短期可能仍有下行，但中期来看往往是绝佳的抄底窗口。"

    if vix_chg > 10:
        vix_direction = f"今日单日跳升 {vix_chg:.1f}%，恐慌情绪急剧放大，短线宜观望，等待情绪释放。"
    elif vix_chg < -10:
        vix_direction = f"今日单日大幅回落 {abs(vix_chg):.1f}%，市场压力快速缓解，做多窗口打开。"
    elif vix_5d is not None:
        if vix_5d > 20:
            vix_direction = f"五日累计上升 {vix_5d:.1f}%，恐慌情绪持续累积，建议分批而非一次性建仓。"
        elif vix_5d < -15:
            vix_direction = f"五日持续回落 {abs(vix_5d):.1f}%，市场情绪明显修复，风险资产配置可以积极一些。"
        else:
            vix_direction = f"近五日 VIX 变动 {vix_5d:+.1f}%，情绪整体稳定。"
    else:
        vix_direction = ""

    # F&G 分析
    if isinstance(fg_score, int):
        if fg_score >= 80:
            fg_analysis = f"恐惧贪婪指数高达 {fg_score}（{fg_status}），已进入极度贪婪区域——这是老交易员最警惕的信号之一。当所有人都乐观的时候，市场往往离顶部不远。建议减少追高，主动锁定部分利润。"
        elif fg_score >= 65:
            fg_analysis = f"恐惧贪婪指数 {fg_score}（{fg_status}），市场情绪偏乐观但尚未极端。可以继续持有，但新建仓位的性价比已不如情绪低迷时高。"
        elif fg_score >= 45:
            fg_analysis = f"恐惧贪婪指数 {fg_score}（{fg_status}），情绪处于中性区间，市场参与者分歧较大，方向选择更多依赖基本面和技术面的共振信号。"
        elif fg_score >= 25:
            fg_analysis = f"恐惧贪婪指数 {fg_score}（{fg_status}），市场情绪偏悲观。历史回测显示，在该区间分批建仓标普500指数基金，12个月平均回报率显著优于随机时机。"
        else:
            fg_analysis = f"恐惧贪婪指数极低至 {fg_score}（{fg_status}），市场陷入极度恐惧。这种时刻往往让人不敢出手，但恰恰是历史上回报最丰厚的入场时机。华尔街有句老话：'Be greedy when others are fearful.'"
    else:
        fg_analysis = "恐惧贪婪指数数据获取失败，暂以 VIX 作为情绪代理指标。"

    strategies.append(f"😰 情绪研判（VIX + F&G）：{vix_level} {vix_direction} {fg_analysis}")

    # ── 3. 信用市场：HYG / JNK 流动性信号 ──────────────────
    avg_credit_chg = (hyg_chg + jnk_chg) / 2
    hyg_5d = t_hyg['5d_chg']
    hyg_1mo= t_hyg['1mo_chg']

    if avg_credit_chg > 0.5 and sp500_chg > 0:
        credit_signal = "强烈偏多"
        credit_desc   = f"高收益债 HYG（{hyg_chg:+.2f}%）/ JNK（{jnk_chg:+.2f}%）与股市同步上涨，信用利差收窄，机构资金风险偏好显著提升——这是股市上涨质量较高的体现。"
    elif avg_credit_chg > 0 and sp500_chg < 0:
        credit_signal = "潜在支撑"
        credit_desc   = f"高收益债小幅上涨（HYG {hyg_chg:+.2f}%），但股市下跌，信用市场与权益市场出现分化。信用市场通常领先于股市，这一分歧暗示今日股市下跌可能是情绪性而非系统性问题，后市不宜过度悲观。"
    elif avg_credit_chg < -0.5 and sp500_chg < 0:
        credit_signal = "风险偏高"
        credit_desc   = f"高收益债 HYG（{hyg_chg:+.2f}%）/ JNK（{jnk_chg:+.2f}%）与股市同步下跌，信用利差走阔，市场出现系统性去风险迹象，此时应当降低仓位，保留现金应对流动性收紧。"
    elif avg_credit_chg < -0.3 and sp500_chg > 0:
        credit_signal = "需警惕"
        credit_desc   = f"今日股市上涨，但高收益债走弱（HYG {hyg_chg:+.2f}%），信用市场与权益市场出现背离——信用市场通常是更'聪明'的钱，这一背离值得高度警惕，需关注此后数日信用利差的变化。"
    else:
        credit_signal = "中性"
        credit_desc   = f"高收益债 HYG（{hyg_chg:+.2f}%）/ JNK（{jnk_chg:+.2f}%）变动温和，信用市场流动性状况平稳，对股市既无明显支撑也无拖累。"

    if hyg_1mo is not None:
        credit_trend = f"月内高收益债{('上涨' if hyg_1mo > 0 else '下跌')} {abs(hyg_1mo):.1f}%，{'信用环境整体宽松，有利于风险资产。' if hyg_1mo > 0 else '信用环境持续收紧，需保持谨慎。'}"
    else:
        credit_trend = ""

    strategies.append(f"💧 信用市场（{credit_signal}）：{credit_desc} {credit_trend}")

    # ── 4. 利率与美债：TNX 分析 ──────────────────────────────
    tnx_5d  = t_tnx['5d_chg']
    tnx_1mo = t_tnx['1mo_chg']

    if tnx_val > 4.7:
        tnx_level = f"十年期美债收益率高企于 {tnx_val:.3f}%，处于历史相对高位。在此利率水平下，无风险资产的吸引力大幅提升，成长股的折现估值受到明显压制，尤其是高估值科技股承压显著。"
    elif tnx_val > 4.2:
        tnx_level = f"十年期美债收益率 {tnx_val:.3f}%，处于中高位区间。市场正在定价'Higher for Longer'的美联储政策路径，权益市场估值扩张空间受限，但尚不至于引发系统性压制。"
    elif tnx_val > 3.8:
        tnx_level = f"十年期美债收益率 {tnx_val:.3f}%，处于相对温和区间，对成长股估值的压制有限，有利于风险资产整体表现。"
    else:
        tnx_level = f"十年期美债收益率 {tnx_val:.3f}%，处于历史偏低区间，宽松的利率环境对权益市场估值形成有力支撑，成长股在此环境下通常表现优异。"

    if tnx_chg > 3:
        tnx_today = f"今日利率单日急升 {tnx_chg:.1f}%，需警惕其对股市估值的即时冲击。"
    elif tnx_chg < -3:
        tnx_today = f"今日利率大幅回落 {abs(tnx_chg):.1f}%，利好权益资产尤其是长久期成长股。"
    else:
        tnx_today = ""

    if tnx_5d is not None and tnx_1mo is not None:
        if tnx_5d > 5 and tnx_1mo > 8:
            tnx_trend = f"五日上升 {tnx_5d:.1f}%、月内上升 {tnx_1mo:.1f}%，利率持续上行趋势明确，对高估值板块构成持续性压力，建议适度降低组合的久期敞口。"
        elif tnx_5d < -5 and tnx_1mo < -8:
            tnx_trend = f"五日下降 {abs(tnx_5d):.1f}%、月内下降 {abs(tnx_1mo):.1f}%，利率趋势性回落，有利于成长股重新估值，可以考虑增加科技和成长股配置。"
        else:
            tnx_trend = f"五日 {fmt_trend(tnx_5d)}，月内 {fmt_trend(tnx_1mo)}，利率处于区间震荡状态。"
    else:
        tnx_trend = ""

    strategies.append(f"🏦 利率环境（TNX {tnx_val:.3f}%）：{tnx_level} {tnx_today} {tnx_trend}")

    # ── 5. 黄金 + 美元：跨资产信号解读 ──────────────────────
    gold_5d  = t_gold['5d_chg']
    gold_1mo = t_gold['1mo_chg']
    dxy_5d   = t_dxy['5d_chg']
    dxy_1mo  = t_dxy['1mo_chg']

    # 黄金与股市关系
    if gold_chg > 1.0 and sp500_chg < -0.5:
        gold_signal = f"今日黄金上涨 {gold_chg:.2f}% 而股市下跌，经典的'避险流入'结构。资金正在离开风险资产寻求安全港，市场对宏观不确定性的担忧在升温。"
    elif gold_chg > 1.0 and sp500_chg > 1.0:
        gold_signal = f"黄金（{gold_chg:+.2f}%）与股市同步上涨，更多反映的是通胀预期升温或美元走弱，而非避险驱动。需关注 CPI、PPI 等通胀数据。"
    elif gold_chg < -1.0:
        gold_signal = f"黄金下跌 {abs(gold_chg):.2f}%，避险需求减弱，市场风险偏好总体良好，有利于权益资产。"
    else:
        gold_signal = f"黄金当日变动平淡（{gold_chg:+.2f}%），避险情绪无明显异动。"

    if gold_1mo is not None:
        gold_trend_text = f"月内黄金{('涨' if gold_1mo > 0 else '跌')} {abs(gold_1mo):.1f}%，{'持续上涨背后可能反映通胀预期或地缘风险的中期积累。' if gold_1mo > 5 else '整体处于区间整理。' if abs(gold_1mo) < 3 else '持续下跌显示风险偏好的中期修复。'}"
    else:
        gold_trend_text = ""

    # 美元与黄金的关系
    if dxy_chg > 0.5 and gold_chg > 0.5:
        dxy_gold_note = f"值得注意的是，美元（{dxy_chg:+.2f}%）与黄金同步上涨，这种非常规组合通常出现在避险情绪极度强烈时，需关注是否有重大宏观事件驱动。"
    elif dxy_chg > 0.5:
        dxy_gold_note = f"美元走强（DXY {dxy_chg:+.2f}%），美元升值对大宗商品和新兴市场构成压制，同时会压低美国跨国公司的海外盈利。"
    elif dxy_chg < -0.5:
        dxy_gold_note = f"美元走弱（DXY {dxy_chg:+.2f}%），有利于大宗商品、黄金以及新兴市场资产，同时利好美国跨国公司的海外收入换算。"
    else:
        dxy_gold_note = f"美元基本稳定（DXY {dxy_chg:+.2f}%），对跨资产影响中性。"

    if dxy_1mo is not None:
        dxy_trend_text = f"月内美元{('走强' if dxy_1mo > 0 else '走弱')} {abs(dxy_1mo):.1f}%，{'持续强势美元将对非美资产和商品形成中期压制。' if dxy_1mo > 3 else '美元中期走弱释放全球流动性，有利于风险资产。' if dxy_1mo < -3 else '美元震荡，跨资产影响有限。'}"
    else:
        dxy_trend_text = ""

    strategies.append(f"🥇 跨资产信号（黄金 + 美元）：{gold_signal} {gold_trend_text} {dxy_gold_note} {dxy_trend_text}")

    # ── 6. 综合研判与投资建议 ────────────────────────────────
    # 构建多空评分体系（0-10分，越高越偏多）
    score = 5  # 中性基准

    # 大盘趋势
    if sp500_chg > 1.5: score += 1
    elif sp500_chg > 0: score += 0.5
    elif sp500_chg < -1.5: score -= 1
    elif sp500_chg < 0: score -= 0.5

    if sp_5d is not None:
        if sp_5d > 3: score += 1
        elif sp_5d > 0: score += 0.5
        elif sp_5d < -3: score -= 1
        elif sp_5d < 0: score -= 0.5

    if sp_1mo is not None:
        if sp_1mo > 5: score += 1
        elif sp_1mo > 0: score += 0.5
        elif sp_1mo < -5: score -= 1
        elif sp_1mo < 0: score -= 0.5

    # VIX（逆向）
    if vix_val < 15: score -= 0.5   # 过低，自满风险
    elif vix_val < 20: score += 0.5
    elif vix_val > 30: score += 1   # 逆向，底部机会
    elif vix_val > 25: score += 0.5

    if vix_chg > 15: score -= 1
    elif vix_chg < -10: score += 1

    # F&G（逆向）
    if isinstance(fg_score, int):
        if fg_score < 20: score += 1.5   # 极度恐惧，逆向做多
        elif fg_score < 35: score += 0.5
        elif fg_score > 80: score -= 1.5  # 极度贪婪，逆向减仓
        elif fg_score > 65: score -= 0.5

    # 信用市场
    if avg_credit_chg > 0.3: score += 0.5
    elif avg_credit_chg < -0.5: score -= 1

    # 利率
    if tnx_val < 4.0: score += 0.5
    elif tnx_val > 4.7: score -= 0.5
    if tnx_chg > 5: score -= 0.5
    elif tnx_chg < -5: score += 0.5

    # 跨资产：黄金避险信号
    if gold_chg > 1.5 and sp500_chg < 0: score -= 0.5
    if dxy_chg > 1.0: score -= 0.5
    elif dxy_chg < -1.0: score += 0.3

    score = max(0, min(10, score))

    # 生成总结
    if score >= 8:
        bias      = "强烈偏多"
        bias_icon = "🟢"
        summary   = (
            f"综合评分 {score:.1f}/10，市场处于强多头格局。当前大盘趋势、情绪面、信用市场、利率环境多维度共振向上，"
            f"属于值得主动参与的上涨行情。"
        )
        action = (
            f"操作建议：可将仓位提升至七至八成，优先配置动能强劲的板块。"
            f"标普500若出现 1-2% 的回调，是优质加仓窗口。"
            f"建议配置结构：60% 标普500指数基金/ETF（SPY/VOO）+ 30% 纳斯达克成长（QQQ）+ 10% 现金待机。"
            f"止损参考近期支撑位（约为当前价格的 -5%）。"
        )
    elif score >= 6.5:
        bias      = "偏多"
        bias_icon = "🟡"
        summary   = (
            f"综合评分 {score:.1f}/10，市场整体偏多但存在部分矛盾信号，行情持续性有一定不确定性。"
            f"可以积极持股，但追高需保持克制。"
        )
        action = (
            f"操作建议：维持五至六成仓位，以标普500宽基指数为核心压舱石，避免重仓单一个股。"
            f"利用短期回调分批加仓，不宜在高点一次性买入。"
            f"关注信用利差和 VIX 走势，若两者同步恶化需及时减仓。"
        )
    elif score >= 4:
        bias      = "中性震荡"
        bias_icon = "⚪"
        summary   = (
            f"综合评分 {score:.1f}/10，多空信号相互抵消，市场方向不明朗，处于震荡寻方向阶段。"
            f"贸然追涨追跌均风险较大。"
        )
        action = (
            f"操作建议：维持三至四成防御性仓位，以现金和短债为主。"
            f"等待明确的方向性突破信号再行动——具体而言，若标普500站稳近期高点且 VIX 持续回落，则加仓；"
            f"若信用利差走阔且大盘破位下行，则进一步减仓。当前不宜新建大仓位。"
        )
    elif score >= 2.5:
        bias      = "偏空"
        bias_icon = "🟠"
        summary   = (
            f"综合评分 {score:.1f}/10，多项指标偏空，市场下行压力较大。"
            f"短期内需以保护本金为首要任务。"
        )
        action = (
            f"操作建议：将仓位降低至两成以内，持有现金或短期美债等候机会。"
            f"已持仓的标普500/纳指 ETF 可考虑持有少量看跌期权对冲（如买入 SPY Put）作为保险。"
            f"切忌逆势抄底，除非 VIX 出现尖峰并快速回落这一历史上的底部信号。"
        )
    else:
        bias      = "强烈偏空"
        bias_icon = "🔴"
        summary   = (
            f"综合评分 {score:.1f}/10，市场处于明显的风险释放阶段，多个预警信号同时亮起。"
            f"历史上相似的信号组合往往对应较大幅度的下跌过程。"
        )
        action = (
            f"操作建议：清仓或接近清仓，全部转为现金或短期美债。"
            f"极端恐慌阶段不排除出现情绪性超跌——若 VIX 短期内冲高至 40 以上后快速回落，"
            f"且信用市场企稳，可以小仓（5-10%）试探性做多，并严格设定止损。"
            f"保护现有资产比追求潜在收益更重要。"
        )

    strategies.append(
        f"{bias_icon} 综合研判（评分 {score:.1f}/10 · {bias}）：{summary} {action}"
    )

    return {
        "strategies": strategies,
        "score": score,
        "bias": bias,
        "bias_icon": bias_icon,
        "summary": summary,
        "action": action,
    }

# ==========================================
# 9. 核心执行逻辑
# ==========================================
def main():
    print("正在抓取收盘数据...")
    data       = get_market_data()
    fg_data    = fetch_fear_greed()
    print("正在抓取走势图数据...")
    chart_data = get_chart_data()

    vix_val      = data['VIX']['price']
    vix_strategy = get_vix_strategy(vix_val)
    # ✅ 传入 chart_data，用于趋势分析
    strategy_pack = generate_strategy(data, fg_data, vix_strategy, chart_data)
    strategies    = strategy_pack["strategies"]

    data_dt     = get_data_timestamp()
    report_date = data_dt.strftime('%Y年%m月%d日 %H:%M ET')
    date_iso    = data_dt.strftime('%Y-%m-%d')
    print(f"Report date: {report_date}")

    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public')
    os.makedirs(output_dir, exist_ok=True)
    previous_summary = None
    previous_path = os.path.join(output_dir, 'data.json')
    if os.path.exists(previous_path):
        try:
            with open(previous_path, 'r', encoding='utf-8') as f:
                previous_summary = json.load(f)
        except Exception as e:
            print(f"Warning: could not load previous summary: {e}")

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
        "decision_summary": build_decision_summary(
            strategy_pack["score"], strategy_pack["bias"], data, fg_data['FG_Score']
        ),
        "score":         f"{strategy_pack['score']:.1f}",
        "bias":          strategy_pack["bias"],
        "bias_icon":     strategy_pack["bias_icon"],
        "action_plan":   strategy_pack["action"],
        "daily_changes": [],
        "watchlist_triggers": build_watchlist_triggers(data),
        "sector_rotation": build_sector_rotation(data),
        "score_history": [],
        "strategies":    strategies,
        "charts":        chart_data,
    }
    summary_data["daily_changes"] = compare_metric_snapshots(summary_data, previous_summary)
    summary_data["score_history"] = build_score_history(
        date_iso, strategy_pack["score"], previous_summary, strategy_pack["bias"]
    )

    with open(os.path.join(output_dir, 'data.json'), 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=4)

    def get_color(c): return "#16a34a" if c > 0 else "#dc2626"
    def get_arrow(c): return "▲" if c > 0 else "▼"
    strategy_rows = "".join([f"<li style='margin-bottom:10px;line-height:1.7;'>{s}</li>" for s in strategies])
    decision = summary_data['decision_summary']
    change_rows = "".join([
        f"<tr><td>{c['label']}</td><td>{c['previous']}</td><td>{c['current']}</td><td>{c['delta']}</td></tr>"
        for c in summary_data.get('daily_changes', [])
    ]) or "<tr><td colspan='4'>暂无昨日数据</td></tr>"
    trigger_rows = "".join([
        f"<li><strong>{'⚠️' if t['active'] else '✓'} {t['label']}：</strong>{t['detail']}</li>"
        for t in summary_data.get('watchlist_triggers', [])
    ])

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
        .strategy-box li {{ font-size: 9pt; line-height: 1.7; color: #1e3a8a; margin-bottom: 8px; }}
    </style></head><body>
    <div class="header">
        <h1>美股情绪观察每日报告</h1>
        <div style="font-size:10pt;opacity:0.85;">🕐 数据时间：{report_date}</div>
        <div class="disclaimer">数据来自第三方（Yahoo Finance / CNN），由 AI 辅助生成，仅供参考，不构成任何投资建议</div>
    </div>
    <div class="section-title">0. 今日一句话结论</div>
    <div class="strategy-box">
        <div style="font-size:14pt;font-weight:bold;color:#1e3a8a;margin-bottom:8px;">{decision['headline']}</div>
        <table class="data-table">
            <tr><th>综合评分</th><th>市场偏向</th><th>建议仓位</th></tr>
            <tr><td>{decision['score']}/10</td><td>{decision['bias']}</td><td>{decision['allocation']}</td></tr>
        </table>
        <p style="font-size:9pt;margin:10px 0 4px 0;"><strong>主要驱动：</strong>{decision['primary_driver']}</p>
        <p style="font-size:9pt;margin:4px 0 0 0;"><strong>主要风险：</strong>{decision['primary_risk']}</p>
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
    <div class="section-title">5. 昨日 vs 今日</div>
    <table class="data-table">
        <tr><th>指标</th><th>昨日</th><th>今日</th><th>变化</th></tr>
        {change_rows}
    </table>
    <div class="section-title">6. 风险触发器</div>
    <div class="strategy-box"><ul>{trigger_rows}</ul></div>
    <div class="section-title">7. 综合投资策略指引</div>
    <div class="strategy-box"><ul>{strategy_rows}</ul></div>
    </body></html>
    """
    HTML(string=html_template).write_pdf(os.path.join(output_dir, 'report.pdf'))
    print("✅ 完成！")

if __name__ == "__main__":
    main()
