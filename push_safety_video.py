# -*- coding: utf-8 -*-
"""
每日安全生产推送（GitHub Actions 云端运行）
- 3 条安全生产视频（B 站，72小时~7天内最新，自动去重）
- 2 条安全生产短语（内置语库轮换）
- 共 5 条消息，逐条推送到微信（PushPlus）
Token 从环境变量 PUSHPLUS_TOKEN 读取，不要写死在代码里。
"""
import json
import hashlib
import html
import os
import re
import time
import urllib.parse
import uuid
from datetime import datetime, timezone, timedelta

import requests

PUSHPLUS_URL = "https://www.pushplus.plus/send"
TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
KEYWORD = "安全生产"          # 视频搜索关键词，想换主题改这里
VIDEO_WINDOW_HOURS = 24 * 7   # 只推最近 7 天内发布的视频
VIDEO_COUNT = 3               # 每天推几条视频
PHRASE_COUNT = 2              # 每天推几条短语
PUSH_INTERVAL = 16            # 逐条推送间隔（秒），避开频率限制
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushed.json")

# 安全生产短语语库（按天轮换，够用一两个月不重复）
PHRASES = [
    "安全一万天，事故一瞬间。",
    "上岗一分钟，安全六十秒。",
    "宁绕百米远，不冒一步险。",
    "安全帽是生命的守护伞，进入现场请规范佩戴。",
    "隐患不除，事故难堵；排查治理，重在平时。",
    "违章操作等于自杀，违章指挥等于杀人。",
    "生命只有一次，安全伴君一生。",
    "安全生产，人人有责；防微杜渐，警钟长鸣。",
    "作业之前多预想，事故之后少悲伤。",
    "小洞不补，大洞吃苦；隐患不排，事故频出。",
    "高高兴兴上班来，平平安安回家去。",
    "规程是生命线，侥幸是事故源。",
    "今日的隐患，就是明日的事故；今日的整改，就是明日的平安。",
    "安全来自长期警惕，事故源于瞬间麻痹。",
    "不怕千日紧，只怕一时松。",
    "一人把关一处安，众人把关稳如山。",
    "抓安全从小事做起，防事故从隐患入手。",
    "唯有按章作业，才有平安归来。",
    " experiential检查走过场，事故来时泪两行；隐患排查要较真。",
    "杜绝三违：不违章指挥、不违章作业、不违反劳动纪律。",
    "消防通道生命道，请勿占用和堵塞。",
    "用电用气要规范，人走断电气关严。",
    "有限空间莫蛮干，先通风来再检测，后作业。",
    "吊装作业站位准，吊臂之下不站人。",
    "高处作业系好安全带，高挂低用莫悬空。",
    "机械运转莫伸手，停机断电再检修。",
    "雨天路滑慢行车，冰雪路面防侧滑。",
    "雨天防触电，雷天避高杆。",
    "夏季高温防中暑，错峰作业保体力。",
    "冬季防火防爆，取暖莫忘通风。",
    "动火作业办票证，监护人不到位不动火。",
    "危化品安全无小事，标签MSDS要记牢。",
    "应急演练常态化，关键时刻不抓瞎。",
    "安全培训是福利，考试过关再上岗。",
    "发现隐患速上报，整改闭环见实效。",
    "安全投入不能省，省了小钱赔大本。",
    "班组安全天天讲，班前提醒记心上。",
    "风险分级管控好，隐患排查治理牢。",
    "双重预防机制是盾，本质安全是本。",
    "安全生产无小事，一枝一叶总关情。",
]

MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43,
             5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16,
             24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59,
             6, 63, 57, 62, 11, 36, 20, 34, 44, 52]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}


def log(msg):
    print(f"[{datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------- PushPlus ----------------
def push(title, content, template="html"):
    payload = {"token": TOKEN, "title": title, "content": content, "template": template,
               "channel": "wechat"}
    for attempt in range(3):
        try:
            r = requests.post(PUSHPLUS_URL, json=payload, timeout=10)
            data = r.json()
            if data.get("code") == 200:
                log(f"已提交推送：{title}")
                return True
            log(f"PushPlus 返回异常：{data}")
            return False
        except Exception as exc:
            log(f"推送请求失败(第{attempt + 1}次)：{exc}")
            time.sleep(3)
    return False


# ---------------- B 站搜索（wbi 签名） ----------------
def get_wbi_keys():
    r = requests.get("https://api.bilibili.com/x/web-interface/nav", headers=HEADERS, timeout=10)
    wbi = r.json()["data"]["wbi_img"]
    img = wbi["img_url"].rsplit("/", 1)[1].split(".")[0]
    sub = wbi["sub_url"].rsplit("/", 1)[1].split(".")[0]
    return img + sub


def wbi_sign(params, raw_key):
    mixin = "".join(raw_key[i] for i in MIXIN_TAB)[:32]
    params["wts"] = int(time.time())
    params = {k: str(v).replace("!", "").replace("'", "").replace("(", "")
                 .replace(")", "").replace("*", "") for k, v in sorted(params.items())}
    query = urllib.parse.urlencode(params)
    params["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return params


def fetch_videos(state):
    """返回最近 VIDEO_WINDOW_HOURS 内、未推送过的视频列表（最多 VIDEO_COUNT 条）。"""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.update({"buvid3": str(uuid.uuid4()), "b_nut": str(int(time.time()))})
    raw_key = get_wbi_keys()
    params = wbi_sign({"search_type": "video", "keyword": KEYWORD, "order": "pubdate",
                       "page": 1}, raw_key)
    r = session.get("https://api.bilibili.com/x/web-interface/wbi/search/type",
                    params=params, timeout=10)
    result = r.json().get("data", {}).get("result") or []
    log(f"B 站搜索到 {len(result)} 条结果")

    pushed = set(state["bvids"])
    deadline = time.time() - VIDEO_WINDOW_HOURS * 3600
    picked = []
    for item in result:
        bvid = item.get("bvid")
        pubdate = item.get("pubdate", 0)
        if not bvid or bvid in pushed or pubdate < deadline:
            continue
        title = html.unescape(re.sub(r"<.*?>", "", item.get("title", "")))
        picked.append({"bvid": bvid, "title": title, "author": item.get("author", ""),
                       "desc": html.unescape(re.sub(r"<.*?>", "", item.get("description", "") or ""))[:80],
                       "pubdate": pubdate})
        if len(picked) >= VIDEO_COUNT:
            break
    log(f"筛出待推视频 {len(picked)} 条")
    return picked


# ---------------- 状态（去重记录） ----------------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {"bvids": []}
    state.setdefault("bvids", [])
    return state


def save_state(state):
    state["bvids"] = state["bvids"][-300:]  # 只保留最近 300 条，防止无限膨胀
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def fmt_date():
    now = datetime.now(timezone(timedelta(hours=8)))
    try:  # Linux（GitHub Actions）
        return now.strftime("%-m月%-d日")
    except ValueError:  # Windows 兼容
        return now.strftime("%m月%d日").lstrip("0").replace("月0", "月")


def main():
    if not TOKEN:
        raise RuntimeError("缺少环境变量 PUSHPLUS_TOKEN")
    state = load_state()
    day_index = int(datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d"))

    # 1. 拉取 3 条视频
    videos = fetch_videos(state)

    # 2. 取 2 条短语（按天 + 序号轮换，语库循环）
    phrases = [PHRASES[(day_index + i) % len(PHRASES)] for i in range(PHRASE_COUNT)]

    total = len(videos) + len(phrases)
    if total == 0:
        push(f"{fmt_date()}安全生产提醒", "今日未获取到新的安全生产视频，请注意作业安全。", "txt")
        return

    log(f"开始逐条推送，共 {total} 条")
    n = 0
    for v in videos:
        n += 1
        url = f"https://www.bilibili.com/video/{v['bvid']}"
        title = f"{fmt_date()}安全生产视频{n}｜{v['title'][:24]}"
        content = (
            f"<h3>🎬 安全生产视频 {n}/{len(videos)}</h3>"
            f"<p><b>{html.escape(v['title'])}</b></p>"
            + (f"<p>简介：{html.escape(v['desc'])}</p>" if v["desc"] else "")
            + f"<p>UP主：{html.escape(v['author'])}</p>"
            f"<p>👉 <a href='{url}'>点击观看视频</a></p>"
        )
        if push(title, content):
            state["bvids"].append(v["bvid"])
        time.sleep(PUSH_INTERVAL)

    for i, p in enumerate(phrases, 1):
        n += 1
        push(f"{fmt_date()}安全短语 {i}/{len(phrases)}",
             f"<div style='font-size:17px;line-height:1.8'>💡 {p}</div>")
        time.sleep(PUSH_INTERVAL)

    save_state(state)
    log("全部推送完成")


if __name__ == "__main__":
    main()
