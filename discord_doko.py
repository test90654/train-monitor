import asyncio
import os
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
TARGET_SECONDS_BEFORE = 180

# 初期状態（未選択）
current_line_name = "未選択"
current_line_code = None
current_station_id = None
current_station_name = "未選択"
# ====================================================

# 🎯 路線ごとの全駅データ（路線コード、駅ID、座標）
ROUTES = {
    "常磐線": {
        "line_code": "9041",
        "stations": {
            "友部": {"station_id": "2241211110", "lat": 36.3315, "lon": 140.4076},
            "内原": {"station_id": "2241211130", "lat": 36.3680, "lon": 140.3540},
            "赤塚": {"station_id": "2241211140", "lat": 36.3800, "lon": 140.4130},
            "水戸": {"station_id": "2241211160", "lat": 36.3680, "lon": 140.4710},
            "勝田": {"station_id": "2241211170", "lat": 36.3940, "lon": 140.5360},
            "佐和": {"station_id": "2241211180", "lat": 36.4320, "lon": 140.5510},
            "東海": {"station_id": "2241211190", "lat": 36.4690, "lon": 140.5650},
            "大甕": {"station_id": "2241211200", "lat": 36.5170, "lon": 140.6120},
            "小木津": {"station_id": "2241211210", "lat": 36.5640, "lon": 140.6430},
            "日立": {"station_id": "2241211220", "lat": 36.5980, "lon": 140.6580},
            "常陸多賀": {"station_id": "2241211230", "lat": 36.5450, "lon": 140.6310},
            "十王": {"station_id": "2241211240", "lat": 36.6570, "lon": 140.7220},
            "高萩": {"station_id": "2241211250", "lat": 36.7260, "lon": 140.7160},
            "南中郷": {"station_id": "2241211260", "lat": 36.7620, "lon": 140.7170},
            "磯原": {"station_id": "2241211270", "lat": 36.7900, "lon": 140.7410},
            "大津港": {"station_id": "2241211280", "lat": 36.8370, "lon": 140.7710},
            "勿来": {"station_id": "2241211290", "lat": 36.8770, "lon": 140.7930},
            "植田": {"station_id": "2241211300", "lat": 36.9070, "lon": 140.8170},
            "泉": {"station_id": "2241211310", "lat": 36.9380, "lon": 140.8650},
            "湯本": {"station_id": "2241211320", "lat": 36.9850, "lon": 140.8410},
            "内郷": {"station_id": "2241211330", "lat": 37.0220, "lon": 140.8800},
            "いわき": {"station_id": "2241211340", "lat": 37.0580, "lon": 140.8910},
        },
    },
    "青梅線": {
        "line_code": "145",
        "stations": {
            "青梅": {"station_id": "2241820120", "lat": 35.7890, "lon": 139.2520},
            "宮ノ平": {"station_id": "2241820130", "lat": 35.7930, "lon": 139.2380},
            "日向和田": {"station_id": "2241820140", "lat": 35.7950, "lon": 139.2250},
            "石神前": {"station_id": "2241820150", "lat": 35.7960, "lon": 139.2150},
            "二俣尾": {"station_id": "2241820160", "lat": 35.8020, "lon": 139.2050},
            "軍畑": {"station_id": "2241820170", "lat": 35.8060, "lon": 139.1950},
            "沢井": {"station_id": "2241820180", "lat": 35.8130, "lon": 139.1850},
            "御嶽": {"station_id": "2241820190", "lat": 35.8180, "lon": 139.1720},
            "川井": {"station_id": "2241820200", "lat": 35.8190, "lon": 139.1550},
            "古里": {"station_id": "2241820210", "lat": 35.8170, "lon": 139.1400},
            "鳩ノ巣": {"station_id": "2241820220", "lat": 35.8150, "lon": 139.1250},
            "白丸": {"station_id": "2241820230", "lat": 35.8130, "lon": 139.1100},
            "奥多摩": {"station_id": "2241820240", "lat": 35.8110, "lon": 139.0920},
        },
    },
}

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
    print(f"🤖 ログインしました: {bot.user.name}")
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

        display_style = "block" if r_name == first_route else "none"
        station_buttons_container += f'<div id="stations-{r_name}" class="station-list-group" style="display: {display_style};">'
        for s_name in r_data["stations"].keys():
            station_buttons_container += f'<button class="station-btn" onclick="setStation(\'{r_name}\', \'{s_name}\')">{s_name}</button>'
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
            h2 { font-size: 18px; border-bottom: 1px solid #444; padding-bottom: 8px; margin-top: 20px; }
        </style>
    </head>
    <body>
        <h1>🚄 接近無線 コントローラー</h1>
        
        <button class="gps-btn" onclick="sendLocation()">📍 現在地GPSで自動同期</button>
        <div id="status">現在の監視: __CURRENT_ROUTE__ / __CURRENT_STATION__駅</div>

        <h2>🛤️ 路線選択</h2>
        <div class="route-container">
            __ROUTE_TABS_PLACEHOLDER__
        </div>

        <h2>📍 駅を選択（上り・下り順）</h2>
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
                        status.innerText = `✅ 同期成功！ ${result.route} / ${result.station}駅`;
                    } catch (e) {
                        status.innerText = "❌ 送信失敗エラー";
                    }
                }, () => {
                    status.innerText = "❌ 位置情報の取得が拒否されました";
                }, { enableHighAccuracy: true, timeout: 10000 });
            }

            async function setStation(routeName, stationName) {
                const status = document.getElementById('status');
                status.innerText = `${routeName} ${stationName} に切り替え中...`;
                try {
                    const response = await fetch('/update_gps', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ type: 'manual', route: routeName, station: stationName })
                    });
                    const result = await response.json();
                    status.innerText = `✅ 切替完了！ ${result.route} / ${result.station}駅`;
                } catch (e) {
                    status.innerText = "❌ 切替失敗エラー";
                }
            }
        </script>
    </body>
    </html>
    """.replace("__CURRENT_ROUTE__", current_line_name) \
       .replace("__CURRENT_STATION__", current_station_name) \
       .replace("__ROUTE_TABS_PLACEHOLDER__", route_tabs) \
       .replace("__STATION_CONTAINERS_PLACEHOLDER__", station_buttons_container)
    return web.Response(text=html, content_type="text/html")

async def handle_update_gps(request):
    global current_line_name, current_line_code, current_station_id, current_station_name
    try:
        data = await request.json()
        req_type = data.get("type")

        if req_type == "gps":
            user_lat = data.get("lat")
            user_lon = data.get("lon")

            closest_station = None
            closest_route = None
            min_distance = float("inf")

            for r_name, r_data in ROUTES.items():
                for s_name, s_info in r_data["stations"].items():
                    dist = (s_info["lat"] - user_lat) ** 2 + (s_info["lon"] - user_lon) ** 2
                    if dist < min_distance:
                        min_distance = dist
                        closest_route = r_name
                        closest_station = (s_name, s_info["station_id"])

            if closest_station:
                current_line_name = closest_route
                current_line_code = ROUTES[closest_route]["line_code"]
                current_station_name, current_station_id = closest_station
                print(f"📍 GPS同期完了 → [{current_line_name}] {current_station_name}駅に変更しました！")

        elif req_type == "manual":
            r_name = data.get("route")
            s_name = data.get("station")
            if r_name in ROUTES and s_name in ROUTES[r_name]["stations"]:
                current_line_name = r_name
                current_line_code = ROUTES[r_name]["line_code"]
                current_station_name = s_name
                current_station_id = ROUTES[r_name]["stations"][s_name]["station_id"]
                print(f"👆 手動切替 → [{current_line_name}] {current_station_name}駅に変更しました！")

        return web.json_response({"status": "success", "route": current_line_name, "station": current_station_name})
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
    print("🌐 マルチ路線対応コントローラー用Webサーバーが起動しました (ポート: 8080)")

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
                # PyNaClのインポートチェック
                try:
                    import nacl
                except ImportError:
                    print("⚠️ 音声再生エラー: PyNaClライブラリがインストールされていません。")
                    return

                source = discord.FFmpegPCMAudio(audio_path)
                voice_client.play(source)
                print(f"🔊 接近無線を再生しました: {audio_filename}")
    except Exception as e:
        print(f"音声再生エラー: {e}")

async def train_monitor_loop():
    global current_line_code, current_station_id, current_station_name, last_played

    await bot.wait_until_ready()
    print("🚂 列車監視ループを開始しました（幽霊列車完全排除・特急遅延対応版）。")

    while not bot.is_closed():
        await asyncio.sleep(CHECK_INTERVAL)

        # 駅が選択されていない状態の時は監視をスキップ
        if not current_line_code or not current_station_id:
            continue

        current_time = time.time()

        for direction in ["up", "down"]:
            line_status_url = f"https://doko-train.jp/json/trainstatus/{current_line_code}.json"
            diag_url = f"https://doko-train.jp/json/departure_info/{current_line_code}/{current_station_id}_{direction}.json"
            
            params = {"_": int(current_time * 1000)}

            try:
                # 1. 路線全体の列車ステータス（今実際に走っている列車リスト）を取得
                line_res = await asyncio.to_thread(requests.get, line_status_url, headers=headers, params=params, timeout=10)
                active_train_ids = set()
                train_details = {}
                
                if line_res.status_code == 200:
                    raw_train_status = line_res.json().get("LINE_STATUS", {}).get("TRAIN_STATUS", {})
                    for key, info in raw_train_status.items():
                        train_id_prefix = key.split(":")[0] # 例: "25M", "27M"
                        active_train_ids.add(train_id_prefix)
                        train_details[train_id_prefix] = info

                # 2. 駅別ダイアグラムを取得
                diag_res = await asyncio.to_thread(requests.get, diag_url, headers=headers, params=params, timeout=10)
                if diag_res.status_code == 200:
                    diag_data = diag_res.json()
                    train_list = diag_data.get("ST_DIAGRAM", [])

                    for train in train_list:
                        train_id = train.get("TRAIN_ID")
                        unit_info = train.get("UNIT_INFO")
                        std_tm = train.get("STD_TM")

                        # 🛑 【重要】路線全体データ（TRAIN_STATUS）に今現在存在しない列車（過去のキャッシュ等）は完全に無視する！
                        if train_id not in active_train_ids:
                            continue

                        # 特急名と遅延の紐付け
                        train_name = "普通/快速"
                        latency = 0
                        if train_id in train_details:
                            info = train_details[train_id]
                            train_nname = info.get("TRAIN_NNAME")
                            if train_nname:
                                train_name = f"特急「{train_nname}」"
                            latency = info.get("LATENCY", 0)

                        # unit_info == "5"（接近フラグ）かつ実在する列車のみ検知
                        if unit_info == "5" and std_tm:
                            remaining_seconds = int(std_tm) - int(current_time)
                            latency_str = f" 【遅延指標(LATENCY): {latency}】" if latency and int(latency) > 0 else ""

                            if 0 <= remaining_seconds <= TARGET_SECONDS_BEFORE:
                                if remaining_seconds <= 60:
                                    dynamic_cooldown = 8
                                elif remaining_seconds <= 120:
                                    dynamic_cooldown = 15
                                else:
                                    dynamic_cooldown = 25

                                print(f"🎯 【{direction.upper()}線 接近検知 @{current_line_name}/{current_station_name}】 列車: {train_id} ({train_name}){latency_str} | 残り約 {remaining_seconds}秒")

                                if current_time - last_played[direction] >= dynamic_cooldown:
                                    audio_file = SOUND_NOBORI if direction == "up" else SOUND_KUDARI
                                    await play_audio_in_vc(audio_file)
                                    last_played[direction] = current_time
                                break

            except Exception as e:
                print(f"API通信エラー ({direction}線): {e}")

bot.run(TOKEN)