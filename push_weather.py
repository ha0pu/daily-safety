# -*- coding: utf-8 -*-
"""
每日天气推送（彩云天气 API，GitHub Actions 云端运行）
- 每天推送 1 条当天天气：温度、天气现象、降雨提醒、空气质量、紫外线、穿衣建议、气象预警
- Token 从环境变量 CAIYUN_TOKEN 读取（在 GitHub Secrets 里配置），不要写死在代码里
"""
import html
import os
import time
from datetime import datetime, timezone, timedelta

import requests

API_URL = "https://api.caiyunapp.com/v2.6"
# 山西省运城市垣曲县新城镇
LOCATION = "111.671,35.299"
CITY_NAME = "垣曲·新城"
PUSHPLUS_URL = "https://www.pushplus.plus/send"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
CAIYUN_TOKEN = os.environ.get("CAIYUN_TOKEN", "")

SKYCON = {
    "CLEAR_DAY": "晴", "CLEAR_NIGHT": "晴夜",
    "PARTLY_CLOUDY_DAY": "多云", "PARTLY_CLOUDY_NIGHT": "多云",
    "CLOUDY": "阴", "LIGHT_HAZE": "轻度雾霾", "MODERATE_HAZE": "中度雾霾",
    "HEAVY_HAZE": "重度雾霾", "LIGHT_RAIN": "小雨", "MODERATE_RAIN": "中雨",
    "HEAVY_RAIN": "大雨", "STORM_RAIN": "暴雨", "FOG": "雾",
    "LIGHT_SNOW": "小雪", "MODERATE_SNOW": "中雪", "HEAVY_SNOW": "大雪",
    "STORM_SNOW": "暴雪", "DUST": "浮尘", "SAND": "沙尘", "WIND": "大风",
}


def log(msg):
    print(f"[{datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')}] {msg}", flush=True)


def push(title, content, template="html", channel="wechat"):
    payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content,
               "template": template, "channel": channel}
    for attempt in range(3):
        try:
            r = requests.post(PUSHPLUS_URL, json=payload, timeout=10)
            data = r.json()
            if data.get("code") == 200:
                log(f"已提交推送[{channel}]：{title}")
                return True
            log(f"PushPlus 返回异常[{channel}]：{data}")
            return False
        except Exception as exc:
            log(f"推送请求失败(第{attempt + 1}次)[{channel}]：{exc}")
            time.sleep(3)
    return False


def build_plain_text(res, now_str):
    """给 cmcc（移动新消息，纯文本）用的正文。"""
    rt, daily = res["realtime"], res["daily"]
    d0 = daily["temperature"][0]
    sky = skycon_cn(daily["skycon"][0]["value"])
    lines = [
        f"{now_str} {CITY_NAME}天气",
        f"{sky} {d0['min']}~{d0['max']}℃ 当前{rt['temperature']}℃(体感{rt.get('apparent_temperature', rt['temperature'])}℃)",
        f"空气：{rt.get('air_quality', {}).get('description', '暂无')}",
        f"紫外线：{daily['life_index']['ultraviolet'][0]['desc']}｜穿衣：{daily['life_index']['dressing'][0]['desc']}",
    ]
    if daily["precipitation"][0]["max"] >= 0.5:
        lines.append("今天可能有降雨，记得带伞！")
    for a in (res.get("alert") or {}).get("content", []):
        if a.get("title"):
            lines.append(f"⚠{a['title']}")
    return "\n".join(lines)


def skycon_cn(code):
    return SKYCON.get(code, code or "未知")


def fetch_weather():
    token = CAIYUN_TOKEN.strip()   # 去掉复制时可能带上的空格/换行
    if not token or not token.startswith("T"):
        raise RuntimeError(f"彩云 Token 格式不对（应以 T 开头，当前开头是：{token[:3]!r}...），请检查 GitHub Secret CAIYUN_TOKEN")
    url = f"{API_URL}/{token}/{LOCATION}/weather.json"
    params = {"dailysteps": 2, "alert": "true"}
    r = requests.get(url, params=params, timeout=15)
    log(f"彩云 API HTTP 状态码：{r.status_code}")
    body = r.text.strip()
    if r.status_code != 200 or not body.startswith("{"):
        # 把服务器实际返回的内容打出来，方便定位（Token 错/额度用完/接口地址错都能看出来）
        raise RuntimeError(f"彩云 API 返回异常 HTTP {r.status_code}，返回内容：{body[:300]}")
    data = r.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"彩云 API 返回异常：{data}")
    return data["result"]


def build_content(res, now_str):
    rt = res["realtime"]
    daily = res["daily"]
    d0 = daily["temperature"][0]          # 今天 最低/最高
    sky_day = skycon_cn(daily["skycon_08h_20h"][0]["value"])
    sky_night = skycon_cn(daily["skycon_20h_32h"][0]["value"])
    sky_all = skycon_cn(daily["skycon"][0]["value"])
    today = daily["precipitation"][0]     # 降水量
    uv = daily["life_index"]["ultraviolet"][0]["desc"]
    dress = daily["life_index"]["dressing"][0]["desc"]
    aqi = rt.get("air_quality", {}).get("aqi", {})
    aqi_desc = aqi.get("description", "")
    temp_now = rt["temperature"]
    apparent = rt.get("apparent_temperature", temp_now)

    # 降雨提醒
    if today["max"] >= 8:
        rain_tip = "☔ <b>今天有明显降雨，出门务必带伞！</b>"
    elif today["max"] >= 0.5:
        rain_tip = "🌦 今天可能有降雨，建议随身带把伞。"
    else:
        rain_tip = "☀ 今天基本无降水，不用带伞。"

    # 温差提醒
    gap = d0["max"] - d0["min"]
    gap_tip = f"（昼夜温差{gap:.0f}℃，注意增减衣物）" if gap >= 10 else ""

    tomorrow = daily["temperature"][1]
    t_sky = skycon_cn(daily["skycon"][1]["value"])

    # 气象预警
    alert_html = ""
    for a in (res.get("alert") or {}).get("content", []):
        title_a = a.get("title") or ""
        desc = (a.get("description") or "").strip()
        if title_a:
            alert_html += f"<p style='color:#c0392b'>⚠ <b>{html.escape(title_a)}</b>"
            if desc:
                alert_html += f"<br>{html.escape(desc[:120])}"
            alert_html += "</p>"

    return f"""
    <h3>🌤 {CITY_NAME} 今日天气（{now_str}）</h3>
    {alert_html}
    <p style='font-size:18px'><b>{sky_all}</b>　当前 {temp_now}℃（体感 {apparent}℃）</p>
    <p><b>温度：</b>{d0['min']} ~ {d0['max']}℃ {gap_tip}</p>
    <p><b>白天：</b>{sky_day}　<b>夜间：</b>{sky_night}</p>
    <p>{rain_tip}</p>
    <p><b>空气质量：</b>{aqi_desc or '暂无数据'}</p>
    <p><b>紫外线：</b>{uv}　<b>穿衣：</b>{dress}</p>
    <p style='color:#888'>明日：{t_sky} {tomorrow['min']} ~ {tomorrow['max']}℃</p>
    """


def main():
    if not PUSHPLUS_TOKEN:
        raise RuntimeError("缺少环境变量 PUSHPLUS_TOKEN")
    if not CAIYUN_TOKEN:
        raise RuntimeError("缺少环境变量 CAIYUN_TOKEN")
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%m月%d日")
    log("开始获取彩云天气数据")
    try:
        res = fetch_weather()
    except Exception as exc:
        log(f"获取天气失败：{exc}")
        push(f"{now_str}天气推送异常", f"今日天气数据获取失败，请检查彩云 API 额度或 Token。", "txt")
        raise
    content = build_content(res, now_str)
    d0 = res["daily"]["temperature"][0]
    title = f"{now_str}天气｜{CITY_NAME} {skycon_cn(res['daily']['skycon'][0]['value'])} {d0['min']}~{d0['max']}℃"

    # 通道1：微信公众号（富文本）
    push(title, content)

    # 通道2：移动「新消息ClawBot」（纯文本；需先在 pushplus 绑定 cmcc 渠道，未绑定只会打日志不影响主推送）
    push(f"{now_str}天气 {CITY_NAME}", build_plain_text(res, now_str),
         template="txt", channel="cmcc")

    log("双通道推送完成")


if __name__ == "__main__":
    main()
