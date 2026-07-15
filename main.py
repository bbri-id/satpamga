import os
import asyncio
import random
import discord
import uvicorn
from datetime import datetime
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from upstash_redis.asyncio import Redis

# --- SETUP ENVIRONMENT ---
REDIS = Redis.from_env()
MAIN_TOKEN = os.getenv("MAIN_TOKEN", "").strip()
TUMBAL_TOKENS = [t.strip() for t in os.getenv("TUMBAL_TOKENS", "").split(",") if t.strip()]
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", 0) or 0)
PORT = int(os.getenv("PORT", 8000))

app = FastAPI()

# --- STATE VARIABLES ---
scan_active = False
scan_summary = [] # Untuk menyimpan data laporan scan
processing_lock = set()

# Konversi Waktu Lokal
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"]

def format_time_id(dt):
    return f"{HARI[dt.weekday()]}, {dt.day} {BULAN[dt.month - 1]} {dt.year} {dt.strftime('%H:%M')}"

# --- DISCORD BOT CLASS ---
class GiveawayBot(commands.Bot):
    def __init__(self, role, index, token):
        super().__init__(command_prefix="!", self_bot=True)
        self.role = role
        self.index = index
        self.token = token
        self.last_interaction = None
        self.interaction_event = asyncio.Event()

    async def on_ready(self):
        print(f"[{self.role}] Akun {self.index} ({self.user.name}) Ready")

    async def on_message(self, message):
        # 1. PENANGKAP HASIL CLICKS (SIMPAN OBJEK MESSAGE SEUTUHNYA)
        if message.author.name == "LionNSEX":
            is_target = False
            if message.interaction and message.interaction.user == self.user:
                is_target = True
            elif self.user in message.mentions:
                is_target = True
            elif message.flags.ephemeral: 
                is_target = True
            
            if is_target:
                self.last_interaction = message # Simpan objek, bukan cuma teks
                self.interaction_event.set()

        # 2. LIVE TRACKER TRIGGER (Hanya MAIN Bot yang jadi mandor)
        if self.role == "MAIN" and message.guild and message.guild.id == TARGET_GUILD_ID:
            is_valid, buttons = is_target_giveaway(message)
            if is_valid:
                asyncio.create_task(process_giveaway(message, buttons, "LIVE"))

# INIT BOTS
main_bot = GiveawayBot("MAIN", 0, MAIN_TOKEN) if MAIN_TOKEN else None
tumbal_bots = [GiveawayBot("TUMBAL", i+1, t) for i, t in enumerate(TUMBAL_TOKENS)]
all_bots = ([main_bot] if main_bot else []) + tumbal_bots

# --- SMART FILTER ---
def is_target_giveaway(message):
    if message.author.name != "LionNSEX":
        return False, []
    
    buttons = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
    if not buttons:
        return False, []
        
    keywords = ["giveaway", "mystery", "box"]
    content = message.content.lower()
    if any(kw in content for kw in keywords):
        return True, buttons
        
    for embed in message.embeds:
        title = (embed.title or "").lower()
        desc = (embed.description or "").lower()
        if any(kw in title for kw in keywords) or any(kw in desc for kw in keywords):
            return True, buttons
            
    return False, []

# --- EVALUATOR PESAN BALASAN ---
def evaluate_response(msg):
    """Mengevaluasi pesan balasan (ephemeral) untuk menentukan status ZONK / WIN / EXHAUSTED"""
    if not msg: return "timeout"
    
    content = msg.content.lower()
    
    # 1. Syarat ZONK / TRAP
    if "zonk" in content or "trap" in content or "http" in content:
        return "zonk"
    
    # Cek gambar/attachment (Trap monyet dll)
    if msg.attachments:
        return "zonk"
    for embed in msg.embeds:
        if embed.image or embed.thumbnail:
            return "zonk"
        embed_desc = (embed.description or "").lower()
        if "http" in embed_desc or "trap" in embed_desc:
            return "zonk"
            
    # 2. Syarat ALREADY CLAIMED
    if "kamu sudah klaim" in content or "already picked" in content:
        return "already_claimed"
        
    # 3. Syarat LIMIT / HABIS
    if "limit" in content or "full" in content or "max" in content:
        return "exhausted"
        
    # Jika tidak ada indikasi zonk/limit, kembalikan teks aslinya sebagai nama hadiah
    return msg.content

# --- LOGIKA SWARM (MINESWEEPER) ---
async def click_and_wait(bot, button, timeout=3.5):
    bot.interaction_event.clear()
    bot.last_interaction = None
    try:
        await button.click()
        await asyncio.wait_for(bot.interaction_event.wait(), timeout=timeout)
        return evaluate_response(bot.last_interaction)
    except asyncio.TimeoutError:
        return "timeout"
    except Exception as e:
        return "error"

async def process_giveaway(message, buttons, source="SCAN"):
    if message.id in processing_lock: return
    if await REDIS.hexists(f"giveaway:{message.id}", "result"): return

    processing_lock.add(message.id)

    available_tumbals = list(tumbal_bots)
    random.shuffle(available_tumbals)
    
    ga_resolved = False
    final_result = "unknown"
    
    # Menyiapkan data laporan untuk Web UI
    report_data = {
        "link": message.jump_url,
        "time": format_time_id(message.created_at),
        "results": []
    }

    for i, button in enumerate(buttons):
        button_safe = False
        
        # FASE 1: VANGUARD TEST
        while available_tumbals:
            vanguard = available_tumbals.pop(0)
            res = await click_and_wait(vanguard, button)
            report_data["results"].append({"name": f"[Tumbal] {vanguard.user.name}", "res": res})
            
            if res == "zonk":
                break # Zonk! Tombol ini hangus, ganti tombol berikutnya.
            elif res == "already_claimed":
                # Tumbal ini sudah pernah klaim, kita BUTUH tumbal lain untuk ngetes tombol ini!
                continue 
            elif res == "exhausted":
                break # Tombol habis
            elif res == "timeout" or res == "error":
                continue # Skip error, coba tumbal lain
            else:
                # AMAN!
                button_safe = True
                break
                
        if not available_tumbals and not button_safe:
            # Tumbal habis sebelum menemukan tombol aman
            break

        # FASE 2: AKUN UTAMA EKSEKUSI
        if button_safe:
            main_res = await click_and_wait(main_bot, button)
            report_data["results"].insert(0, {"name": f"[UTAMA] {main_bot.user.name}", "res": main_res})

            if main_res == "zonk":
                # Jika kecolongan zonk
                continue
            elif main_res == "already_claimed" or main_res == "exhausted":
                continue # Cari tombol lain
            else:
                final_result = main_res
                ga_resolved = True
                
                # FASE 3: STEALTH FREE-FOR-ALL
                ffa_tasks = []
                for t_bot in available_tumbals:
                    jitter = random.uniform(0.5, 2.5)
                    ffa_tasks.append(delayed_click(t_bot, button, jitter, report_data))
                
                # Tunggu semua FFA selesai agar laporannya komplit
                if ffa_tasks:
                    await asyncio.gather(*ffa_tasks)
                
                break # Selesai, Akun utama sudah dapat hadiah!

    # Simpan Checkpoint ke Redis
    if ga_resolved or final_result != "unknown":
        await REDIS.hset(f"giveaway:{message.id}", mapping={
            "channel_id": str(message.channel.id),
            "timestamp": str(datetime.now().timestamp()),
            "result": final_result
        })
        if source == "LIVE":
            await REDIS.set("system:last_live_claim", str(datetime.now().timestamp()))
            
    # Masukkan ke summary jika berasal dari SCAN
    if source == "SCAN" and len(report_data["results"]) > 0:
        scan_summary.append(report_data)
    
    processing_lock.discard(message.id)

async def delayed_click(bot, button, delay, report_data):
    await asyncio.sleep(delay)
    try:
        bot.interaction_event.clear()
        bot.last_interaction = None
        await button.click()
        await asyncio.wait_for(bot.interaction_event.wait(), timeout=3.5)
        res = evaluate_response(bot.last_interaction)
        report_data["results"].append({"name": f"[Tumbal] {bot.user.name}", "res": res})
    except:
        report_data["results"].append({"name": f"[Tumbal] {bot.user.name}", "res": "timeout/error"})

async def run_full_scan():
    global scan_active, scan_summary
    if not main_bot or scan_active: return
    
    scan_active = True
    scan_summary = [] # Reset laporan
    
    guild = main_bot.get_guild(TARGET_GUILD_ID)
    if not guild:
        scan_active = False
        return

    await REDIS.set("system:last_full_scan", str(datetime.now().timestamp()))
    
    cache_key = f"guild_channels:{TARGET_GUILD_ID}"
    channel_ids = await REDIS.smembers(cache_key)
    
    if not channel_ids:
        text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        for c in text_channels: await REDIS.sadd(cache_key, c.id)
        channel_ids = [str(c.id) for c in text_channels]

    for ch_id in channel_ids:
        channel = main_bot.get_channel(int(ch_id))
        if not channel:
            try: channel = await main_bot.fetch_channel(int(ch_id))
            except: continue

        try:
            async for msg in channel.history(limit=500):
                # CEK REDIS CHECKPOINT
                if await REDIS.hexists(f"giveaway:{msg.id}", "result"):
                    break # Langsung stop scan channel ini
                
                is_valid, buttons = is_target_giveaway(msg)
                if is_valid:
                    await process_giveaway(msg, buttons, "SCAN")
                        
        except discord.errors.Forbidden:
            # BUG FIX: Handle 403 Forbidden secara spesifik
            print(f"Skipping channel #{channel.name} due to Missing Access (403).")
            continue
        except Exception as e:
            continue
            
    scan_active = False


# --- UI & API ROUTER ---
@app.get("/get-summary")
async def get_summary():
    return {
        "is_scanning": scan_active,
        "total": len(scan_summary),
        "results": scan_summary
    }

@app.get("/", response_class=HTMLResponse)
async def home():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Swarm Dashboard</title>
        <style>
            body {{ background: #121212; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; border: 1px solid #333; }}
            button {{ background: #4caf50; color: white; border: none; padding: 12px 20px; cursor: pointer; border-radius: 4px; font-weight: bold; width: 100%; font-size: 16px; }}
            button:disabled {{ background: #555; cursor: not-allowed; }}
            .info-box {{ display: flex; justify-content: space-between; margin-bottom: 20px; background: #222; padding: 15px; border-radius: 4px; border-left: 4px solid #4caf50; font-size: 14px; }}
            .ga-card {{ background: #2a2a2a; padding: 15px; margin-top: 15px; border-radius: 6px; border-left: 4px solid #cf6679; }}
            .ga-card a {{ color: #4dabf7; text-decoration: none; font-weight: bold; font-size: 16px; }}
            .ga-card a:hover {{ text-decoration: underline; }}
            .ga-date {{ color: #999; font-size: 13px; margin-bottom: 10px; display: block; }}
            .res-list {{ margin: 0; padding-left: 20px; font-family: monospace; font-size: 14px; }}
            .res-item {{ padding: 3px 0; }}
            .status-text {{ font-weight: bold; color: #ffeb3b; margin-top: 20px; text-align: center; }}
        </style>
    </head>
    <body>
        <h2>Minesweeper Scan Report</h2>
        <div class="card">
            <div class="info-box">
                <div><strong>Main Account:</strong> {main_bot.user.name if main_bot and main_bot.user else "Loading..."}</div>
                <div><strong>Tumbals Active:</strong> {len(tumbal_bots)}</div>
            </div>
            
            <button id="scanBtn" onclick="runScan()">RUN FULL SCAN</button>
            <div id="statusIndicator" class="status-text"></div>
            
            <div id="reportContainer" style="margin-top: 20px;">
                <!-- Hasil scan akan muncul disini -->
            </div>
        </div>

        <script>
            function runScan() {{
                fetch('/scan');
                renderState();
            }}

            function renderState() {{
                fetch('/get-summary').then(r => r.json()).then(data => {{
                    const btn = document.getElementById('scanBtn');
                    const status = document.getElementById('statusIndicator');
                    const container = document.getElementById('reportContainer');
                    
                    if (data.is_scanning) {{
                        btn.disabled = true;
                        btn.innerText = "SCANNING IN PROGRESS...";
                        status.innerText = "Mengeksekusi penyisiran otomatis... Harap tunggu.";
                    }} else {{
                        btn.disabled = false;
                        btn.innerText = "RUN FULL SCAN";
                        status.innerText = data.total > 0 ? `Scan Selesai! Total ada ${{data.total}} GA Active yang diproses.` : "Menunggu perintah scan...";
                    }}

                    // Render list
                    container.innerHTML = "";
                    data.results.forEach((ga, index) => {{
                        let liHTML = "";
                        ga.results.forEach((res, idx) => {{
                            liHTML += `<li class="res-item"><strong>${{res.name}}</strong> : ${{res.res}}</li>`;
                        }});
                        
                        container.innerHTML += `
                            <div class="ga-card">
                                <a href="${{ga.link}}" target="_blank">GA ${{index + 1}} (Klik untuk buka pesan)</a>
                                <span class="ga-date">${{ga.time}}</span>
                                <ul class="res-list">${{liHTML}}</ul>
                            </div>
                        `;
                    }});
                }});
            }}

            // Auto-refresh setiap 2 detik
            setInterval(renderState, 2000);
            renderState(); // Load pertama kali
        </script>
    </body>
    </html>
    """

@app.get("/scan")
async def trigger_scan():
    asyncio.create_task(run_full_scan())
    return {"status": "scanning"}

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    
    tasks = []
    if main_bot: tasks.append(main_bot.start(main_bot.token))
    for t_bot in tumbal_bots: tasks.append(t_bot.start(t_bot.token))
    
    tasks.append(server.serve())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
