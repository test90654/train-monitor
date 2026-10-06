import asyncio
import math
import os
import sys
import time
import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
import requests

# ==================== 設定エリア ====================
TOKEN = os.environ.get("DISCORD_TOKEN")

SOUND_NOBORI = "nobori.mp3"
SOUND_KUDARI = "kudari.mp3"

CHECK_INTERVAL = 5
last_played = {"up": 0, "down": 0}

# GPS同期時、最寄り駅がこの距離(m)以内なら「駅」、それより離れていれば「駅間」を監視する
STATION_RADIUS_M = 300

# 初期状態（未選択）
current_line_name = "未選択"
current_line_code = None
current_range = None  # 監視範囲 (始点index, 終点index)。駅なら同じ値、駅間なら隣り合う2駅
current_target_label = "未選択"
# ====================================================

# 🎯 路線ごとの全駅データ（どこトレ駅マスタ準拠・index は線路上の並び順）
ROUTES = {
    "常磐線": {
        "line_code": "9041",
        "stations": {
            "友部": {"station_id": "2241211110", "lat": 36.3511, "lon": 140.3075, "index": 1},
            "内原": {"station_id": "2241211130", "lat": 36.3706, "lon": 140.3538, "index": 2},
            "赤塚": {"station_id": "2241211140", "lat": 36.3820, "lon": 140.4170, "index": 3},
            "偕楽園": {"station_id": "2241211150", "lat": 36.3729, "lon": 140.4577, "index": 4},
            "水戸": {"station_id": "2241211160", "lat": 36.3709, "lon": 140.4783, "index": 5},
            "勝田": {"station_id": "2241211170", "lat": 36.3949, "lon": 140.5244, "index": 6},
            "佐和": {"station_id": "2241211180", "lat": 36.4313, "lon": 140.5409, "index": 7},
            "東海": {"station_id": "2241211190", "lat": 36.4662, "lon": 140.5669, "index": 8},
            "大甕": {"station_id": "2241211200", "lat": 36.5134, "lon": 140.6197, "index": 9},
            "常陸多賀": {"station_id": "2241211210", "lat": 36.5522, "lon": 140.6328, "index": 10},
            "日立": {"station_id": "2241211220", "lat": 36.5917, "lon": 140.6625, "index": 11},
            "小木津": {"station_id": "2241211230", "lat": 36.6355, "lon": 140.6757, "index": 12},
            "十王": {"station_id": "2241211240", "lat": 36.6705, "lon": 140.6853, "index": 13},
            "高萩": {"station_id": "2241211250", "lat": 36.7132, "lon": 140.7168, "index": 14},
            "南中郷": {"station_id": "2241211260", "lat": 36.7543, "lon": 140.7294, "index": 15},
            "磯原": {"station_id": "2241211270", "lat": 36.7908, "lon": 140.7466, "index": 16},
            "大津港": {"station_id": "2241211280", "lat": 36.8468, "lon": 140.7781, "index": 17},
            "勿来": {"station_id": "2241211290", "lat": 36.8829, "lon": 140.7871, "index": 18},
            "植田": {"station_id": "2241211300", "lat": 36.9200, "lon": 140.7965, "index": 19},
            "泉": {"station_id": "2241211310", "lat": 36.9554, "lon": 140.8532, "index": 20},
            "湯本": {"station_id": "2241211320", "lat": 37.0078, "lon": 140.8494, "index": 21},
            "内郷": {"station_id": "2241211330", "lat": 37.0356, "lon": 140.8545, "index": 22},
            "いわき": {"station_id": "2241211340", "lat": 37.0583, "lon": 140.8941, "index": 23},
        },
    },
    "青梅線": {
        "line_code": "145",
        "stations": {
            "青梅": {"station_id": "2241820120", "lat": 35.7905, "lon": 139.2588, "index": 1},
            "宮ノ平": {"station_id": "2241820130", "lat": 35.7878, "lon": 139.2378, "index": 2},
            "日向和田": {"station_id": "2241820140", "lat": 35.7883, "lon": 139.2297, "index": 3},
            "石神前": {"station_id": "2241820150", "lat": 35.7965, "lon": 139.2254, "index": 4},
            "二俣尾": {"station_id": "2241820160", "lat": 35.8037, "lon": 139.2164, "index": 5},
            "軍畑": {"station_id": "2241820170", "lat": 35.8078, "lon": 139.2080, "index": 6},
            "沢井": {"station_id": "2241820180", "lat": 35.8058, "lon": 139.1939, "index": 7},
            "御嶽": {"station_id": "2241820190", "lat": 35.8014, "lon": 139.1825, "index": 8},
            "川井": {"station_id": "2241820200", "lat": 35.8138, "lon": 139.1639, "index": 9},
            "古里": {"station_id": "2241820210", "lat": 35.8163, "lon": 139.1517, "index": 10},
            "鳩ノ巣": {"station_id": "2241820220", "lat": 35.8153, "lon": 139.1293, "index": 11},
            "白丸": {"station_id": "2241820230", "lat": 35.8115, "lon": 139.1146, "index": 12},
            "奥多摩": {"station_id": "2241820240", "lat": 35.8093, "lon": 139.0970, "index": 13},
        },
    },
}

# 駅ID → index の逆引き（列車位置の判定用）
STATION_INDEX = {
    r_name: {s["station_id"]: s["index"] for s in r_data["stations"].values()}
    for r_name, r_data in ROUTES.items()
}


def ordered_stations(r_name):
    return sorted(ROUTES[r_name]["stations"].items(), key=lambda kv: kv[1]["index"])


def set_target(r_name, from_name, to_name=None):
    """監視対象を設定する。to_name を渡すと from〜to の駅間を監視する。"""
    global current_line_name, current_line_code, current_range, current_target_label
    stations = ROUTES[r_name]["stations"]
    a = stations[from_name]["index"]
    b = stations[to_name]["index"] if to_name else a
    if a > b:
        a, b = b, a
        from_name, to_name = to_name, from_name
    current_line_name = r_name
    current_line_code = ROUTES[r_name]["line_code"]
    current_range = (a, b)
    current_target_label = f"{from_name}駅" if a == b else f"{from_name}〜{to_name} 駅間"


def train_in_range(info, index_map, lo, hi):
    """列車が監視範囲 [lo, hi] に停車中・走行中、または範囲へ向かっているか"""
    cur = index_map.get(str(info.get("CUR_STATION", "0")))
    pos = index_map.get(str(info.get("POS_STATION", "0")))
    pre = index_map.get(str(info.get("PRE_STATION", "0")))
    # 範囲内の駅に停車中
    if cur is not None and lo <= cur <= hi:
        return True
    # 次の到着駅が範囲内（範囲へ接近中 or 範囲内を走行中）
    if pos is not None and lo <= pos <= hi:
        return True
    # 駅間走行中で、前駅〜次駅の区間が監視範囲にかかっている（境界駅から離れていく列車は除く）
    if cur is None and pre is not None and pos is not None:
        if min(pre, pos) < hi and max(pre, pos) > lo:
            return True
    return False


def find_nearest_target(user_lat, user_lon):
    """現在地に最も近い駅、または駅間を返す: (路線名, 駅A, 駅B or None)"""
    def to_xy(lat, lon):
        # 狭い範囲なので平面近似（メートル）
        return (lon - user_lon) * 111320 * math.cos(math.radians(user_lat)), (lat - user_lat) * 110540

    best_station = (float("inf"), None, None)
    best_section = (float("inf"), None, None, None)
    for r_name in ROUTES:
        stations = ordered_stations(r_name)
        for s_name, s in stations:
            d = math.hypot(*to_xy(s["lat"], s["lon"]))
            if d < best_station[0]:
                best_station = (d, r_name, s_name)
        for (a_name, a), (b_name, b) in zip(stations, stations[1:]):
            ax, ay = to_xy(a["lat"], a["lon"])
            bx, by = to_xy(b["lat"], b["lon"])
            dx, dy = bx - ax, by - ay
            seg_len2 = dx * dx + dy * dy
            if seg_len2 == 0:
                continue
            # 現在地(原点)から線分ABへの垂線の足
            t = -(ax * dx + ay * dy) / seg_len2
            if 0 < t < 1:
                d = math.hypot(ax + t * dx, ay + t * dy)
                if d < best_section[0]:
                    best_section = (d, r_name, a_name, b_name)

    if best_station[0] <= STATION_RADIUS_M or best_section[1] is None or best_station[0] <= best_section[0]:
        return best_station[1], best_station[2], None
    return best_section[1], best_section[2], best_section[3]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

headers = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "referer": "https://doko-train.jp/sp/",
    "user-agent": "Mozilla/5.0 (Linux; Android 14; Pixel 9 Pro Fold) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
}

@bot.event
async def on_ready():
    sys.stderr.write(f"🤖 [DEBUG] on_ready発火: ログインユーザー = {bot.user.name}\n")
    sys.stderr.flush()
    bot.loop.create_task(train_monitor_loop())
    bot.loop.create_task(start_web_server())

# ==================== Webサーバー＆コントロール画面 ====================
async def handle_index(request):
    route_tabs = ""
    station_buttons_container = ""

    first_route = list(ROUTES.keys())[0]

    for r_name, r_data in ROUTES.items():
        active_class = "active" if r_name == first_route else ""
        route_tabs += f'<button class="route-btn {active_class}" onclick="switchRoute(\'{r_name}\')">{r_name}</button>'

        display_style = "flex" if r_name == first_route else "none"
        station_buttons_container += f'<div id="stations-{r_name}" class="station-list-group" style="display: {display_style};">'
        stations = ordered_stations(r_name)
        for i, (s_name, _) in enumerate(stations):
            station_buttons_container += f'<button class="station-btn" onclick="setStation(\'{r_name}\', \'{s_name}\')">{s_name}</button>'
            if i + 1 < len(stations):
                next_name = stations[i + 1][0]
                station_buttons_container += f'<button class="section-btn" onclick="setSection(\'{r_name}\', \'{s_name}\', \'{next_name}\')">↕ {s_name}〜{next_name} 駅間</button>'
        station_buttons_container += "</div>"

    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>接近無線 - マルチ路線コントローラー</title>
        <style>
            body { font-family: sans-serif; text-align: center; padding: 20px; background: #111; color: #fff; }
            .gps-btn { background: #ff4757; color: white; border: none; padding: 15px 30px; font-size: 18px; border-radius: 10px; cursor: pointer; width: 100%; max-width: 400px; margin-bottom: 20px; }
            .gps-btn:active { background: #ff6b81; }
            #status { margin: 15px 0; font-size: 16px; color: #00d2d3; font-weight: bold; }
            .route-container { display: flex; justify-content: center; gap: 10px; margin-bottom: 15px; }
            .route-btn { background: #353b48; color: white; border: none; padding: 10px 20px; font-size: 16px; border-radius: 8px; cursor: pointer; }
            .route-btn.active { background: #e84118; font-weight: bold; }
            .station-list-group { display: flex; flex-direction: column; gap: 8px; max-width: 400px; margin: 0 auto; }
            .station-btn { background: #2f3640; color: white; border: none; padding: 14px; font-size: 16px; border-radius: 8px; cursor: pointer; text-align: left; padding-left: 20px; }
            .station-btn:active { background: #718093; }
            .section-btn { background: transparent; color: #a4b0be; border: 1px dashed #57606f; padding: 8px; font-size: 14px; border-radius: 8px; cursor: pointer; text-align: left; margin-left: 24px; padding-left: 16px; }
            .section-btn:active { background: #57606f; }
            h2 { font-size: 18px; border-bottom: 1px solid #444; padding-bottom: 8px; margin-top: 20px; }
        </style>
    </head>
    <body>
        <h1>🚄 接近無線 コントローラー</h1>
        
        <button class="gps-btn" onclick="sendLocation()">📍 現在地GPSで自動同期</button>
        <div id="status">現在の監視: __CURRENT_ROUTE__ / __CURRENT_TARGET__</div>

        <h2>🛤️ 路線選択</h2>
        <div class="route-container">
            __ROUTE_TABS_PLACEHOLDER__
        </div>

        <h2>📍 駅・駅間を選択（上り・下り順）</h2>
        __STATION_CONTAINERS_PLACEHOLDER__

        <script>
            function switchRoute(routeName) {
                document.querySelectorAll('.station-list-group').forEach(el => el.style.display = 'none');
                document.getElementById('stations-' + routeName).style.display = 'flex';
                
                document.querySelectorAll('.route-btn').forEach(el => el.classList.remove('active'));
                event.target.classList.add('active');
            }

            function sendLocation() {
                const status = document.getElementById('status');
                if (!navigator.geolocation) {
                    status.innerText = "❌ お使いのブラウザは位置情報に対応していません";
                    return;
                }
                status.innerText = "位置情報を取得中...";
                navigator.geolocation.getCurrentPosition(async (position) => {
                    const lat = position.coords.latitude;
                    const lon = position.coords.longitude;

                    try {
                        const response = await fetch('/update_gps', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ type: 'gps', lat: lat, lon: lon })
                        });
                        const result = await response.json();
                        status.innerText = `✅ 同期成功！ ${result.route} / ${result.target}`;
                    } catch (e) {
                        status.innerText = "❌ 送信失敗エラー";
                    }
                }, () => {
                    status.innerText = "❌ 位置情報の取得が拒否されました";
                }, { enableHighAccuracy: true, timeout: 10000 });
            }

            async function postTarget(body, label) {
                const status = document.getElementById('status');
                status.innerText = `${body.route} ${label} に切り替え中...`;
                try {
                    const response = await fetch('/update_gps', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    });
                    const result = await response.json();
                    status.innerText = `✅ 切替完了！ ${result.route} / ${result.target}`;
                } catch (e) {
                    status.innerText = "❌ 切替失敗エラー";
                }
            }

            function setStation(routeName, stationName) {
                postTarget({ type: 'manual', route: routeName, station: stationName }, stationName);
            }

            function setSection(routeName, fromName, toName) {
                postTarget({ type: 'section', route: routeName, from: fromName, to: toName }, `${fromName}〜${toName} 駅間`);
            }
        </script>
    </body>
    </html>
    """.replace("__CURRENT_ROUTE__", current_line_name) \
       .replace("__CURRENT_TARGET__", current_target_label) \
       .replace("__ROUTE_TABS_PLACEHOLDER__", route_tabs) \
       .replace("__STATION_CONTAINERS_PLACEHOLDER__", station_buttons_container)
    return web.Response(text=html, content_type="text/html")

async def handle_update_gps(request):
    try:
        data = await request.json()
        req_type = data.get("type")

        if req_type == "gps":
            r_name, from_name, to_name = find_nearest_target(data.get("lat"), data.get("lon"))
            if r_name:
                set_target(r_name, from_name, to_name)
                sys.stderr.write(f"📍 [GPS同期完了] [{current_line_name}] {current_target_label}\n")
                sys.stderr.flush()

        elif req_type == "manual":
            r_name = data.get("route")
            s_name = data.get("station")
            if r_name in ROUTES and s_name in ROUTES[r_name]["stations"]:
                set_target(r_name, s_name)
                sys.stderr.write(f"👆 [手動切替] [{current_line_name}] {current_target_label}\n")
                sys.stderr.flush()

        elif req_type == "section":
            r_name = data.get("route")
            from_name = data.get("from")
            to_name = data.get("to")
            if r_name in ROUTES and from_name in ROUTES[r_name]["stations"] and to_name in ROUTES[r_name]["stations"]:
                set_target(r_name, from_name, to_name)
                sys.stderr.write(f"👆 [手動切替] [{current_line_name}] {current_target_label}\n")
                sys.stderr.flush()

        return web.json_response({"status": "success", "route": current_line_name, "target": current_target_label})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)})

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/update_gps", handle_update_gps)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    sys.stderr.write("🌐 [WEB] コントローラー用Webサーバーが起動しました (ポート: 8080)\n")
    sys.stderr.flush()

# ==================== 音声＆列車監視ループ ====================
async def play_audio_in_vc(audio_filename):
    try:
        target_channel = None
        for guild in bot.guilds:
            for channel in guild.voice_channels:
                if "接近無線" in channel.name:
                    target_channel = channel
                    break
            if target_channel:
                break
        
        if not target_channel:
            for guild in bot.guilds:
                if guild.voice_channels:
                    target_channel = guild.voice_channels[0]
                    break

        if not target_channel:
            return

        voice_client = discord.utils.get(bot.voice_clients, guild=target_channel.guild)
        if not voice_client or not voice_client.is_connected():
            voice_client = await target_channel.connect()

        if voice_client and not voice_client.is_playing():
            audio_path = os.path.join(os.path.dirname(__file__), audio_filename)
            if os.path.exists(audio_path):
                source = discord.FFmpegPCMAudio(audio_path)
                voice_client.play(source)
                sys.stderr.write(f"🔊 [音声再生] {audio_filename}\n")
                sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"音声再生エラー: {e}\n")
        sys.stderr.flush()

async def train_monitor_loop():
    global last_played

    await bot.wait_until_ready()
    sys.stderr.write("🚂 [監視ループ] 列車監視ループを開始しました。\n")
    sys.stderr.flush()

    while not bot.is_closed():
        await asyncio.sleep(CHECK_INTERVAL)

        if not current_line_code or not current_range:
            continue

        lo, hi = current_range
        index_map = STATION_INDEX[current_line_name]
        current_time = time.time()
        line_status_url = f"https://doko-train.jp/json/trainstatus/{current_line_code}.json"
        params = {"_": int(current_time * 1000)}

        try:
            line_res = await asyncio.to_thread(requests.get, line_status_url, headers=headers, params=params, timeout=10)
            if line_res.status_code == 200:
                line_data = line_res.json()
                raw_train_status = line_data.get("LINE_STATUS", {}).get("TRAIN_STATUS", {})

                for key, info in raw_train_status.items():
                    train_id = key.split(":")[0]
                    train_nname = info.get("TRAIN_NNAME", "")
                    train_name = f"特急「{train_nname}」" if train_nname else "普通/快速"
                    latency = info.get("LATENCY", 0)
                    bound = str(info.get("BOUND", "1"))

                    if train_in_range(info, index_map, lo, hi):
                        latency_str = f" 【遅延: {latency}分】" if latency and int(latency) > 0 else ""
                        
                        # 🔴 上下線の判定を反転（BOUND "2" を下り、"1" を上りに修正）
                        direction = "down" if bound == "2" else "up"

                        sys.stderr.write(f"🎯 [{direction.upper()}線検知 @{current_line_name}/{current_target_label}] 列車: {train_id} ({train_name}){latency_str} (BOUND:{bound})\n")
                        sys.stderr.flush()

                        if current_time - last_played[direction] >= 20:
                            # upならnobori.mp3、downならkudari.mp3を再生
                            audio_file = SOUND_NOBORI if direction == "up" else SOUND_KUDARI
                            await play_audio_in_vc(audio_file)
                            last_played[direction] = current_time

        except Exception as e:
            sys.stderr.write(f"API通信エラー: {e}\n")
            sys.stderr.flush()

sys.stderr.write("🚀 [起動] ボットの起動処理を開始します...\n")
sys.stderr.flush()
bot.run(TOKEN)