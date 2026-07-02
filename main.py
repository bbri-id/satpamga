import os
import asyncio
import re
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.requests import Request
from fastapi.responses import StreamingResponse
import discord
from discord.ext import commands
import uvicorn

# ==========================================
# 1. SETUP FASTAPI, STATE & LOG STREAM
# ==========================================
app = FastAPI()

WIB = timezone(timedelta(hours=7))

bot_state = {
    "status_mode": "Standby (New Messages Only)",
    "last_scan_time": "Belum pernah scan",
    "scanning_in_progress": False,
    "progress_text": "" # Untuk menampung teks "32% Completed"
}

stats_giveaway = {
    "Fixed Reward": 0,
    "Random Reward": 0,
    "Unknown Type": 0,
    "Total Terdeteksi": 0
}

# Menyimpan data giveaway yang masih aktif untuk ditampilkan di UI
active_giveaways = []

log_queue = asyncio.Queue()

def custom_log(text: str):
    timestamp = datetime.now(WIB).strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {text}"
    print(log_entry)
    asyncio.create_task(log_queue.put(log_entry))

@app.get("/", response_class=HTMLResponse)
async def home():
    status_color = "#43b581" if not bot_state["scanning_in_progress"] else "#faa61a"
    
    # Render daftar giveaway yang aktif ke bentuk elemen HTML
    giveaways_html = ""
    if not active_giveaways:
        giveaways_html = "<p style='color: #888; text-align: center; font-size: 13px;'>Tidak ada giveaway aktif saat ini.</p>"
    else:
        for gw in active_giveaways:
            giveaways_html += f"""
            <div class="gw-card">
                <div class="gw-title">🎁 {gw['title']}</div>
                <div class="gw-desc">{gw['description'].replace('\n', '<br>')}</div>
                <div class="gw-meta">
                    <span>👥 Claims: {gw['claims']}</span>
                    <a href="{gw['url']}" target="_blank" class="gw-link">Jump to Message ↗</a>
                </div>
            </div>
            """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Giveaway Watcher Control Panel</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #1a1a1a; color: #ffffff; margin: 40px; }}
            .container {{ max-width: 650px; margin: auto; background: #2d2d2d; padding: 20px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
            h1 {{ text-align: center; color: #7289da; border-bottom: 2px solid #404040; padding-bottom: 10px; margin-bottom: 5px; }}
            .last-scan {{ text-align: center; color: #aaaaaa; font-size: 13px; margin-bottom: 25px; }}
            .stat-box {{ display: flex; justify-content: space-between; padding: 12px 15px; margin: 10px 0; background: #3d3d3d; border-radius: 5px; font-size: 18px; }}
            .stat-box.total {{ background: #7289da; font-weight: bold; }}
            .status {{ text-align: center; color: {status_color}; font-weight: bold; margin-top: 20px; font-size: 16px; }}
            .progress-display {{ text-align: center; color: #faa61a; font-size: 14px; font-weight: bold; margin-top: -10px; margin-bottom: 15px; }}
            
            .btn-container {{ display: flex; gap: 10px; margin-top: 25px; justify-content: center; }}
            .btn {{ padding: 12px 24px; border: none; border-radius: 5px; font-weight: bold; font-size: 14px; cursor: pointer; text-decoration: none; color: white; transition: background 0.2s; }}
            .btn-scanall {{ background-color: #faa61a; width: 100%; text-align: center; }}
            .btn-scanall:hover {{ background-color: #e09516; }}
            button[disabled] {{ background-color: #555555 !important; cursor: not-allowed; color: #888888; }}
            
            /* Section Giveaway Aktif */
            .section-title {{ font-size: 14px; color: #888; margin-top: 25px; margin-bottom: 8px; font-weight: bold; text-transform: uppercase; }}
            .gw-container {{ max-height: 250px; overflow-y: auto; background: #222; padding: 10px; border-radius: 5px; border: 1px solid #333; }}
            .gw-card {{ background: #2d2d2d; padding: 12px; border-radius: 5px; margin-bottom: 10px; border-left: 4px solid #43b581; }}
            .gw-title {{ font-weight: bold; color: #43b581; font-size: 15px; margin-bottom: 5px; }}
            .gw-desc {{ font-size: 13px; color: #ddd; line-height: 1.4; }}
            .gw-meta {{ display: flex; justify-content: space-between; margin-top: 8px; font-size: 12px; color: #aaa; align-items: center; }}
            .gw-link {{ color: #7289da; text-decoration: none; font-weight: bold; }}
            .gw-link:hover {{ text-decoration: underline; }}

            .terminal {{ background-color: #000000; font-family: 'Courier New', Courier, monospace; padding: 15px; border-radius: 5px; box-shadow: inset 0 0 10px #000; height: 150px; overflow-y: auto; white-space: pre-wrap; font-size: 12px; line-height: 1.5; color: #39ff14; border: 1px solid #333; margin-top: 5px; }}
            .terminal-header {{ color: #888; font-size: 11px; margin-top: 20px; font-bottom: 5px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Giveaway Watcher Panel</h1>
            <div class="last-scan">🕒 Terakhir Scan: <strong>{bot_state['last_scan_time']}</strong></div>
            
            <div class="stat-box"><span>📦 Fixed Reward</span> <span>{stats_giveaway['Fixed Reward']}</span></div>
            <div class="stat-box"><span>🎲 Random Reward</span> <span>{stats_giveaway['Random Reward']}</span></div>
            <div class="stat-box"><span>❓ Unknown Type</span> <span>{stats_giveaway['Unknown Type']}</span></div>
            <div class="stat-box total"><span>🚀 Total Terdeteksi</span> <span>{stats_giveaway['Total Terdeteksi']}</span></div>
            
            <p class="status">🟢 Status Server: {bot_state['status_mode']}</p>
            {f'<div class="progress-display">{bot_state["progress_text"]}</div>' if bot_state['scanning_in_progress'] else ''}
            
            <div class="btn-container">
                <button onclick="location.href='/action/scanall'" class="btn btn-scanall" {"disabled" if bot_state['scanning_in_progress'] else ""}>Scan All History Server</button>
            </div>

            <div class="section-title">🎁 Active Giveaways Found ({len(active_giveaways)}):</div>
            <div class="gw-container">
                {giveaways_html}
            </div>

            <div class="terminal-header">📟 LIVE CONSOLE LOGS:</div>
            <div id="log-terminal" class="terminal">🤖 Menunggu aktivitas sistem...</div>
        </div>

        <script>
            const eventSource = new EventSource("/stream-logs");
            const terminal = document.getElementById("log-terminal");
            let firstLog = true;

            eventSource.onmessage = function(event) {{
                if (firstLog) {{
                    terminal.innerHTML = "";
                    firstLog = false;
                }}
                terminal.innerHTML += event.data + "\\n";
                terminal.scrollTop = terminal.scrollHeight;
                
                // Reload halaman otomatis jika mendeteksi scanning selesai agar tabel data ter-refresh
                if (event.data.includes("Scanning Selesai!") || event.data.includes("Sistem diubah ke mode Standby")) {{
                    setTimeout(() => {{ location.reload(); }}, 1000);
                }}
            }};
        </script>
    </body>
    </html>
    """
    return html_content

@app.get("/stream-logs")
async def stream_logs(request: Request):
    async def log_generator():
        while True:
            if await request.is_disconnected():
                break
            log_msg = await log_queue.get()
            yield f"data: {log_msg}\n\n"
    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.get("/action/scanall")
async def trigger_scan_all():
    if not bot_state["scanning_in_progress"]:
        asyncio.create_task(scan_history())
    return RedirectResponse(url="/", status_code=303)

# ==========================================
# 2. SETUP DISCORD SELFBOT
# ==========================================
bot = commands.Bot(command_prefix="self!", self_bot=True)

def proses_pesan_giveaway(message):
    global stats_giveaway, active_giveaways
    terdeteksi = False
    
    if message.author.bot and message.author.name == "LionNSEX":
        if message.embeds:
            for embed in message.embeds:
                title = embed.title if embed.title else ""
                description = embed.description if embed.description else ""
                
                if "Mystery Box Giveaway" in title:
                    stats_giveaway["Total Terdeteksi"] += 1
                    if "FIXED" in description:
                        stats_giveaway["Fixed Reward"] += 1
                    elif "RANDOM" in description:
                        stats_giveaway["Random Reward"] += 1
                    else:
                        stats_giveaway["Unknown Type"] += 1
                    terdeteksi = True
                    
                    # Logika Pencarian Batas Klaim Terhadap Status Keaktifan
                    max_claims = 0
                    current_claims = 0
                    
                    # Gunakan regex untuk membaca parameter angka "Max Claims" di dalam deskripsi embed
                    max_match = re.search(r"Max Claims:\s*(\d+)", description)
                    if max_match:
                        max_claims = int(max_match.group(1))
                    
                    # Membaca total klik yang sudah dilakukan pada komponen tombol pesan tersebut
                    if message.components:
                        for action_row in message.components:
                            for component in action_row.children:
                                # Jika komponen tersebut adalah button bertuliskan klaim box
                                if component.type == discord.ComponentType.button:
                                    # Mengambil jumlah interaksi klik user pada tombol (jika data tersedia dari gateway)
                                    pass 
                    
                    # Kondisi Penentuan Keaktifan: Jika klaim saat ini masih di bawah batas maksimal kuota
                    if current_claims < max_claims or max_claims == 0:
                        claims_display = f"{current_claims}/{max_claims}" if max_claims > 0 else "Unlimited/Unknown"
                        
                        # Simpan ke daftar aktif jika link pesan belum terdata sebelumnya
                        if not any(gw['url'] == message.jump_url for gw in active_giveaways):
                            active_giveaways.append({
                                "title": title,
                                "description": description,
                                "claims": claims_display,
                                "url": message.jump_url
                            })
    return terdeteksi

@bot.event
async def on_ready():
    custom_log(f"Selfbot Sukses Login sebagai: {bot.user.name}")

# BOT selalu standby memantau real-time setiap saat secara default
@bot.event
async def on_message(message):
    target_env = os.environ.get("TARGET_GUILD_ID")
    if target_env and message.guild and not bot_state["scanning_in_progress"]:
        try:
            if message.guild.id == int(target_env):
                is_giveaway = proses_pesan_giveaway(message)
                if is_giveaway:
                    bot_state["last_scan_time"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
                    custom_log(f"[Standby Realtime] Terdeteksi giveaway aktif baru di #{message.channel.name}!")
        except ValueError:
            pass
    await bot.process_commands(message)

# Fungsi Scan History dengan kalkulasi persentase (%) ruangan chat
async def scan_history():
    target_env = os.environ.get("TARGET_GUILD_ID")
    if not target_env:
        custom_log("[Error] TARGET_GUILD_ID belum dikonfigurasi!")
        return
        
    guild_id = int(target_env)
    guild = bot.get_guild(guild_id)
    if not guild:
        custom_log(f"[Error] Server ID {guild_id} tidak ditemukan.")
        return

    bot_state["scanning_in_progress"] = True
    bot_state["status_mode"] = "Scanning History"
    
    # Reset penampung data lama
    for key in stats_giveaway: stats_giveaway[key] = 0
    active_giveaways.clear()

    # Menyaring text channels valid yang bisa dibaca akun kita
    valid_channels = []
    for channel in guild.text_channels:
        permissions = channel.permissions_for(guild.me)
        if permissions.read_messages and permissions.read_message_history:
            valid_channels.append(channel)
            
    total_channels = len(valid_channels)
    custom_log(f"Memulai pemindaian riwayat di server: {guild.name} ({total_channels} text channels terdeteksi)")
    
    for index, channel in enumerate(valid_channels, start=1):
        # Hitung kalkulasi matematika persentase progress penjelajahan room
        percentage = int((index / total_channels) * 100)
        bot_state["progress_text"] = f"scanning channel #{channel.name} ({index}/{total_channels}) | {percentage}% Completed"
        custom_log(f"Scanning channel: #{channel.name} ({index}/{total_channels})")
        
        try:
            async for msg in channel.history(limit=None):
                proses_pesan_giveaway(msg)
        except discord.Forbidden:
            custom_log(f"  [Skip] Akses ditolak di channel: #{channel.name}")
        except Exception as e:
            custom_log(f"  [Error] Gagal membaca channel #{channel.name}: {e}")
                
    bot_state["scanning_in_progress"] = False
    bot_state["status_mode"] = "Standby (New Messages Only)"
    bot_state["last_scan_time"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    custom_log(f"Scanning Selesai! Berhasil mengumpulkan {stats_giveaway['Total Terdeteksi']} data.")

# ==========================================
# 3. RUNNER
# ==========================================
async def main():
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN tidak ditemukan!")
        return

    await asyncio.gather(
        server.serve(),
        bot.start(token)
    )

if __name__ == "__main__":
    asyncio.run(main())
