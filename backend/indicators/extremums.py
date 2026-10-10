"""
================================================================================
 indicators/extremums.py  -  PIPELINE STEP 4
================================================================================
Finds the "anchor" price the Chandelier Exit hangs its stops from.

    upper_anchor  -> long stop  = upper_anchor - ATR_mult x ATR
    lower_anchor  -> short stop = lower_anchor + ATR_mult x ATR

Four formulas can produce the anchors (parameter `extremum_formula`):
    "close"        highest / lowest over the last `atr_period` HA bars
                   (use_close=True -> uses HA closes, wicks ignored)
    "range_ma"     highest / lowest over the last `lookback` bars
    "crest_trough" the last peak / valley of an EMA(ma_len) of HA closes
    "pivot_sr"     last 3-bar swing high (resistance) / swing low (support)

Also returns the amount of "wick noise" (distance between HA close and the
wick tips) that is ignored when use_close=True.
"""


def compute_extremums_raw(
    ha_candles,
    atr_period: int = 22,
    use_close: bool = False,
    extremum_formula: str = "close",
    ma_len: int = 20,
    lookback: int = 5,
):
    """
    Pipeline Stage 3: Extremums Engine & Noise Reduction
    Candle -> Heikin-Ashi -> Extremums -> Chandelier Exit

    “Use Close Price for Extremums” means:
    When calculating highest high and lowest low used by Chandelier Exit,
    use the candle's Close price instead of its High/Low wick.

    Without “Use Close Price” (OFF):
      Highest = max(High_1, High_2, ..., High_22)
      Lowest  = min(Low_1, Low_2, ..., Low_22)
      -> Candle wicks are included (contains noise).

    With “Use Close Price” = ON:
      Highest = max(Close_1, Close_2, ..., Close_22)
      Lowest  = min(Close_1, Close_2, ..., Close_22)
      -> Wicks are ignored for finding the extreme (pure noise reduction).
    """
    n = len(ha_candles)
    if n == 0:
        return {
            "highest_close": [], "lowest_close": [],
            "highest_high": [], "lowest_low": [],
            "upper_anchor": [], "lower_anchor": [],
            "upper_wick_noise": [], "lower_wick_noise": [],
            "total_wick_noise": 0.0,
        }

    highest_close = [0.0] * n
    lowest_close = [0.0] * n
    highest_high = [0.0] * n
    lowest_low = [0.0] * n
    f1_upper = [0.0] * n
    f1_lower = [0.0] * n
    upper_wick_noise = [0.0] * n
    lower_wick_noise = [0.0] * n

    for i in range(n):
        s = max(0, i - atr_period + 1)
        h_max = max(ha_candles[j]["ha_high"] for j in range(s, i + 1))
        l_min = min(ha_candles[j]["ha_low"] for j in range(s, i + 1))
        c_max = max(ha_candles[j]["ha_close"] for j in range(s, i + 1))
        c_min = min(ha_candles[j]["ha_close"] for j in range(s, i + 1))

        highest_high[i] = h_max
        lowest_low[i] = l_min
        highest_close[i] = c_max
        lowest_close[i] = c_min

        f1_upper[i] = c_max if use_close else h_max
        f1_lower[i] = c_min if use_close else l_min

        upper_wick_noise[i] = max(0.0, ha_candles[i]["ha_high"] - ha_candles[i]["ha_close"])
        lower_wick_noise[i] = max(0.0, ha_candles[i]["ha_close"] - ha_candles[i]["ha_low"])

    # Formula 2 & 3: Moving Average (EMA)
    closes = [c["ha_close"] for c in ha_candles]
    ma = [0.0] * n
    if n > 0:
        ma[0] = closes[0]
        k = 2.0 / (ma_len + 1)
        for i in range(1, n):
            ma[i] = closes[i] * k + ma[i - 1] * (1.0 - k)

    # Formula 2: Rolling Range Envelope over lookback
    prev_high = [0.0] * n
    prev_low = [0.0] * n
    for i in range(n):
        s = max(0, i - lookback + 1)
        prev_high[i] = max((ha_candles[j]["ha_close"] if use_close else ha_candles[j]["ha_high"]) for j in range(s, i + 1))
        prev_low[i] = min((ha_candles[j]["ha_close"] if use_close else ha_candles[j]["ha_low"]) for j in range(s, i + 1))

    # Formula 3: Track Crests & Troughs along MA
    crests = [False] * n
    troughs = [False] * n
    last_crest = [highest_high[0]] * n
    last_trough = [lowest_low[0]] * n
    c_crest = highest_high[0]
    c_trough = lowest_low[0]

    for i in range(2, n):
        d_cur = ma[i] - ma[i - 1]
        d_prev = ma[i - 1] - ma[i - 2]
        if d_prev > 0 and d_cur <= 0:
            crests[i] = True
            c_crest = ma[i - 1]
        if d_prev < 0 and d_cur >= 0:
            troughs[i] = True
            c_trough = ma[i - 1]
        last_crest[i] = c_crest
        last_trough[i] = c_trough

    # Formula 4: Structural Swing Pivots
    p_high = [False] * n
    p_low = [False] * n
    active_res = [highest_high[0]] * n
    active_sup = [lowest_low[0]] * n
    c_res = highest_high[0]
    c_sup = lowest_low[0]

    for i in range(2, n):
        h_prev = ha_candles[i - 1]["ha_close"] if use_close else ha_candles[i - 1]["ha_high"]
        h_cur = ha_candles[i]["ha_close"] if use_close else ha_candles[i]["ha_high"]
        h_prev2 = ha_candles[i - 2]["ha_close"] if use_close else ha_candles[i - 2]["ha_high"]

        l_prev = ha_candles[i - 1]["ha_close"] if use_close else ha_candles[i - 1]["ha_low"]
        l_cur = ha_candles[i]["ha_close"] if use_close else ha_candles[i]["ha_low"]
        l_prev2 = ha_candles[i - 2]["ha_close"] if use_close else ha_candles[i - 2]["ha_low"]

        if h_prev > h_cur and h_prev > h_prev2:
            p_high[i - 1] = True
            c_res = h_prev
        if l_prev < l_cur and l_prev < l_prev2:
            p_low[i - 1] = True
            c_sup = l_prev

        active_res[i] = c_res
        active_sup[i] = c_sup

    # Select Active Upper and Lower Anchors
    upper_anchor = [0.0] * n
    lower_anchor = [0.0] * n

    for i in range(n):
        if extremum_formula == "range_ma":
            upper_anchor[i] = prev_high[i]
            lower_anchor[i] = prev_low[i]
        elif extremum_formula == "crest_trough":
            upper_anchor[i] = last_crest[i]
            lower_anchor[i] = last_trough[i]
        elif extremum_formula == "pivot_sr":
            upper_anchor[i] = active_res[i]
            lower_anchor[i] = active_sup[i]
        else:
            upper_anchor[i] = f1_upper[i]
            lower_anchor[i] = f1_lower[i]

    return {
        "highest_close": highest_close,
        "lowest_close": lowest_close,
        "highest_high": highest_high,
        "lowest_low": lowest_low,
        "upper_anchor": upper_anchor,
        "lower_anchor": lower_anchor,
        "upper_wick_noise": upper_wick_noise,
        "lower_wick_noise": lower_wick_noise,
        "total_wick_noise": sum(upper_wick_noise) + sum(lower_wick_noise),
        "prev_high": prev_high,
        "prev_low": prev_low,
        "ma": ma,
        "crests": crests,
        "troughs": troughs,
        "last_crest": last_crest,
        "last_trough": last_trough,
        "active_res": active_res,
        "active_sup": active_sup,
    }
