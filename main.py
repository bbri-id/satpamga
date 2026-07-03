import os
import asyncio
import re
import json
import random
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.requests import Request
from fastapi.responses import StreamingResponse
import discord
from discord.ext import commands
import uvicorn

# ==========================================
# 1. SETUP FASTAPI, STATE & STREAM QUEUE
# ==========================================
app = FastAPI()

WIB = timezone(timedelta(hours=7))

bot_state = {
    "status_mode": "Standby (New Messages Only)",
    "last_scan_time": "Belum pernah scan",
    "scanning_in_progress": False,
    "progress_text": "Sistem siap memantau."
}

active_giveaways = []

# ID Channel yang di-exclude dari aktivitas scan history
EXCLUDE_CHANNEL_IDS = [
    1515589036142493896,
    1514896523635200002,
    1513912852275138630,
    1513914332721709217,
    1513685847420047371,
    1513685938528718848,
    1513686147560247296,
    1513933744916926525
]

# File lokal untuk menyimpan ID giveaway yang sudah pernah diklaim sebelumnya (Persistent Storage)
CLAIMED_FILE = "claimed_ids.txt"

def load_claimed_ids():
    if os.path.exists(CLAIMED_FILE):
        with open(CLAIMED_FILE, "r") as f:
            return [int(line.strip()) for line in f if line.strip().isdigit()]
    return []

def save_claimed_id(msg_id: int):
    global ALREADY_CLAIMED_IDS
    if msg_id not in ALREADY_CLAIMED_IDS:
        ALREADY_CLAIMED_IDS.append(msg_id)
        with open(CLAIMED_FILE, "a") as f:
            f.write(f"{msg_id}\n")

ALREADY_CLAIMED_IDS = load_claimed_ids()
update_queue = asyncio.Queue()

def broadcast_update(log_text: str):
    """Mengirim data perubahan state terpusat ke browser UI"""
    # Gunakan progress_text untuk menampung log aktivitas utama agar terlihat di bawah status
    bot_state["progress_text"] = log_text
    print(f"[{datetime.now(WIB).strftime('%H:%M:%S')}] {log_text}")
    
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
                    <span>🤖 Hasil: <strong style="color: #faa61a;">{gw['claim_status']}</strong></span>
                    <a href="{gw['url']}" target="_blank" class="gw-link">Jump to Message ↗</a>
                </div>
            </div>
            """

    payload = {
        "status_mode": bot_state["status_mode"],
        "last_scan_time": bot_state["last_scan_time"],
        "scanning_in_progress": bot_state["scanning_in_progress"],
        "progress_text": bot_state["progress_text"],
        "active_count": len(active_giveaways),
        "giveaways_html": giveaways_html
    }
    
    asyncio.create_task(update_queue.put(payload))

@app.get("/", response_class=HTMLResponse)
async def home():
    status_color = "#43b581" if not bot_state["scanning_in_progress"] else "#faa61a"
    
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
            .status {{ text-align: center; color: {status_color}; font-weight: bold; margin-top: 20px; font-size: 18px; }}
            .progress-display {{ text-align: center; color: #39ff14; font-family: 'Courier New', monospace; font-size: 13px; font-weight: bold; margin-top: 5px; margin-bottom: 25px; background: #111; padding: 10px; border-radius: 5px; border: 1px solid #333; }}
            
            .btn-container {{ display: flex; gap: 10px; margin-top: 25px; justify-content: center; }}
            .btn {{ padding: 12px 24px; border: none; border-radius: 5px; font-weight: bold; font-size: 14px; cursor: pointer; text-decoration: none; color: white; transition: background 0.2s; }}
            .btn-scanall {{ background-color: #faa61a; width: 100%; text-align: center; }}
            .btn-scanall:hover {{ background-color: #e09516; }}
            button[disabled] {{ background-color: #555555 !important; cursor: not-allowed; color: #888888; }}
            
            .section-title {{ font-size: 15px; color: #7289da; margin-top: 25px; margin-bottom: 8px; font-weight: bold; text-transform: uppercase; border-left: 3px solid #7289da; padding-left: 8px; }}
            .gw-container {{ max-height: 400px; overflow-y: auto; background: #222; padding: 10px; border-radius: 5px; border: 1px solid #333; }}
            .gw-card {{ background: #2d2d2d; padding: 12px; border-radius: 5px; margin-bottom: 10px; border-left: 4px solid #7289da; }}
            .gw-title {{ font-weight: bold; color: #43b581; font-size: 15px; margin-bottom: 5px; }}
            .gw-desc {{ font-size: 13px; color: #ddd; line-height: 1.4; }}
            .gw-meta {{ display: flex; justify-content: space-between; margin-top: 8px; font-size: 12px; color: #aaa; align-items: center; }}
            .gw-link {{ color: #7289da; text-decoration: none; font-weight: bold; }}
            .gw-link:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Giveaway Watcher Panel</h1>
            <div class="last-scan">🕒 Terakhir Scan: <strong id="val-last-scan">{bot_state['last_scan_time']}</strong></div>
            
            <p class="status" id="val-status">🟢 Status Server: {bot_state['status_mode']}</p>
            <div class="progress-display" id="val-progress">{bot_state['progress_text']}</div>
            
            <div class="btn-container">
                <button id="btn-scan" onclick="location.href='/action/scanall'" class="btn btn-scanall">Scan All History Server</button>
            </div>

            <div class="section-title" id="val-counter">🎁 {len(active_giveaways)} Active Giveaway Found!</div>
            <div class="gw-container" id="gw-list">
                <p style='color: #888; text-align: center; font-size: 13px;'>Tidak ada giveaway aktif saat ini.</p>
            </div>
        </div>

        <script>
            const eventSource = new EventSource("/stream-updates");
            
            eventSource.onmessage = function(event) {{
                const data = JSON.parse(event.data);
                
                document.getElementById("val-last-scan").innerText = data.last_scan_time;
                document.getElementById("val-status").innerText = "🟢 Status Server: " + data.status_mode;
                document.getElementById("val-progress").innerText = data.progress_text;
                document.getElementById("val-counter").innerText = "🎁 " + data.active_count + " Active Giveaway Found!";
                document.getElementById("gw-list").innerHTML = data.giveaways_html;
                
                const btnScan = document.getElementById("btn-scan");
                const statusP = document.getElementById("val-status");
                
                if (data.scanning_in_progress) {{
                    statusP.style.color = "#faa61a";
                    btnScan.disabled = true;
                }} else {{
                    statusP.style.color = "#43b581";
                    btnScan.disabled = false;
                }}
            }};
        </script>
    </body>
    </html>
    """
    return html_content

@app.get("/stream-updates")
async def stream_updates(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            payload = await update_queue.get()
            yield f"data: {json.dumps(payload)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.get("/action/scanall")
async def trigger_scan_all():
    if not bot_state["scanning_in_progress"]:
        asyncio.create_task(scan_history())
    return RedirectResponse(url="/", status_code=303)

# ==========================================
# 2. SETUP DISCORD SELFBOT & AUTO-CLAIM
# ==========================================
bot = commands.Bot(command_prefix="self!", self_bot=True)

async def eksekusi_auto_claim(message, title, description):
    """Fungsi pembantu untuk melakukan interaksi klik tombol acak dan membaca output server"""
    global active_giveaways
    
    status_pelacakan = "Mencoba mengklaim..."
    
    # Ambil daftar tombol 'Open Box' yang tersedia pada struktur pesan komponen
    tombol_boxes = []
    if message.components:
        for action_row in message.components:
            for component in action_row.children:
                if component.type == discord.ComponentType.button:
                    tombol_boxes.append(component)

    if not tombol_boxes:
        status_pelacakan = "Gagal (Tombol tidak ditemukan)"
        return status_pelacakan

    # Pilih salah satu tombol secara acak/random sesuai instruksi
    target_button = random.choice(tombol_boxes)
    broadcast_update(f"🤖 Menekan tombol box acak pada pesan [{message.id}]...")

    try:
        # Eksekusi Trigger Interaksi Klik Tombol Server
        await target_button.click()
        
        # Berikan jeda waktu tunggu sekitar 2.5 detik bagi bot LionNSEX untuk memproses input & mengeluarkan respon chat
        await asyncio.sleep(2.5)
        
        # Cari pesan respon terbaru dari bot target di channel yang sama
        status_ditemukan = False
        async for reply in message.channel.history(limit=5):
            if reply.author.bot and reply.author.name == "LionNSEX":
                konten_respon = reply.content.lower() if reply.content else ""
                
                # Periksa jika ada objek embed respon interaksi
                if reply.embeds:
                    for emb in reply.embeds:
                        if emb.description: konten_respon += " " + emb.description.lower()
                        if emb.title: konten_respon += " " + emb.title.lower()

                # Cabang Analisis Output Status Respons Server
                if "already" in konten_respon or "pernah" in konten_respon or "claimed" in konten_respon:
                    status_pelacakan = "Sudah Pernah Diclaim (Skipped)"
                    save_claimed_id(message.id) # Masukkan ke blacklist pengecualian
                    status_ditemukan = True
                    break
                elif "zonk" in konten_respon or "empty" in konten_respon or "bukan keberuntungan" in konten_respon:
                    status_pelacakan = "Zonk / Ampas 💔"
                    status_ditemukan = True
                    break
                elif "win" in konten_respon or "menang" in konten_respon or "success" in konten_respon:
                    status_pelacakan = "🎉 MENANG / BERHASIL KLAIM!"
                    status_ditemukan = True
                    break
                    
        if not status_ditemukan:
            status_pelacakan = "Klaim Terkirim (Respon tidak terbaca)"
            
    except discord.HTTPException as e:
        status_pelacakan = f"Error Klik: {e.text}"
    except Exception as e:
        status_pelacakan = f"Gagal Klaim: {str(e)}"
        
    return status_pelacakan

def proses_pesan_giveaway(message):
    global active_giveaways
    
    # Proteksi penyaringan: Lewati proses jika ID chat ini ada di blacklist sudah pernah diclaim
    if message.id in ALREADY_CLAIMED_IDS:
        return False

    if message.author.bot and message.author.name == "LionNSEX":
        if message.embeds:
            for embed in message.embeds:
                title = embed.title if embed.title else ""
                description = embed.description if embed.description else ""
                
                if "Mystery Box Giveaway" in title:
                    max_claims = 0
                    max_match = re.search(r"Max Claims:\s*(\d+)", description)
                    if max_match:
                        max_claims = int(max_match.group(1))
                    
                    # Deteksi Keaktifan Awal
                    if max_claims > 0: # Dianggap aktif saat pemindaian awal
                        if not any(gw['url'] == message.jump_url for gw in active_giveaways):
                            idx = len(active_giveaways)
                            
                            # Daftarkan struktur data ke panel web
                            active_giveaways.append({
                                "title": title,
                                "description": description,
                                "url": message.jump_url,
                                "claim_status": "Memulai Klaim..."
                            })
                            
                            # Jalankan pekerja background async untuk mengeklik tombol secara otomatis
                            async def background_claim_worker():
                                hasil_output = await eksekusi_auto_claim(message, title, description)
                                active_giveaways[idx]["claim_status"] = hasil_output
                                broadcast_update(f"Hasil klaim box [{message.id}]: {hasil_output}")
                                
                            asyncio.create_task(background_claim_worker())
                            return True
    return False

@bot.event
async def on_ready():
    broadcast_update(f"Selfbot Sukses Login sebagai: {bot.user.name}")

@bot.event
async def on_message(message):
    target_env = os.environ.get("TARGET_GUILD_ID")
    if target_env and message.guild and not bot_state["scanning_in_progress"]:
        try:
            if message.guild.id == int(target_env):
                if message.channel.id in EXCLUDE_CHANNEL_IDS:
                    return
                proses_pesan_giveaway(message)
        except ValueError:
            pass
    await bot.process_commands(message)

async def scan_history():
    target_env = os.environ.get("TARGET_GUILD_ID")
    if not target_env:
        broadcast_update("[Error] TARGET_GUILD_ID belum dikonfigurasi!")
        return
        
    guild_id = int(target_env)
    guild = bot.get_guild(guild_id)
    if not guild:
        broadcast_update(f"[Error] Server ID {guild_id} tidak ditemukan.")
        return

    bot_state["scanning_in_progress"] = True
    bot_state["status_mode"] = "Scanning History"
    active_giveaways.clear()

    valid_channels = []
    for channel in guild.text_channels:
        permissions = channel.permissions_for(guild.me)
        if permissions.read_messages and permissions.read_message_history:
            if channel.id not in EXCLUDE_CHANNEL_IDS:
                valid_channels.append(channel)
            
    total_channels = len(valid_channels)
    broadcast_update(f"Memulai scan riwayat di server... (0/{total_channels}) | 0% Completed")
    
    for index, channel in enumerate(valid_channels, start=1):
        percentage = int((index / total_channels) * 100)
        broadcast_update(f"scanning channel #{channel.name} ({index}/{total_channels}) | {percentage}% Completed")
        
        try:
            async for msg in channel.history(limit=None):
                proses_pesan_giveaway(msg)
        except discord.Forbidden:
            pass
        except Exception as e:
            broadcast_update(f"[Error] Gagal membaca #{channel.name}: {e}")
                
    bot_state["scanning_in_progress"] = False
    bot_state["status_mode"] = "Standby (New Messages Only)"
    bot_state["last_scan_time"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    broadcast_update(f"Scanning Selesai! Menunggu giveaway baru...")

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
