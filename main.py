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
scan_summary = []
processing_lock = set()
logs = ["System Initialized... Menunggu perintah."]

# Konversi Waktu Lokal
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"]

def format_time_id(dt):
    return f"{HARI[dt.weekday()]}, {dt.day} {BULAN[dt.month - 1]} {dt.year} {dt.strftime('%H:%M')}"

def add_log(msg):
    print(msg)
    time_str = datetime.now().strftime("%H:%M:%S")
    logs.insert(0, f"[{time_str}] > {msg}")
    if len(logs) > 100: logs.pop()

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
        add_log(f"[{self.role}] Akun {self.index} ({self.user.name}) Ready")

    async def on_message(self, message):
        # 1. PENANGKAP HASIL CLICKS
        if message.author.name == "LionNSEX":
            is_target = False
            if message.interaction and message.interaction.user == self.user:
                is_target = True
            elif self.user in message.mentions:
                is_target = True
            elif message.flags.ephemeral: 
                is_target = True
            
            if is_target:
                self.last_interaction = message 
                self.interaction_event.set()

        # 2. LIVE TRACKER TRIGGER
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
    
    valid_buttons = []
    for r in message.components:
        for c in r.children:
            if c.type == discord.ComponentType.button:
                # ANTI "START GAME" BUTTON BUG
                if c.label and "start" in str(c.label).lower():
                    continue
                valid_buttons.append(c)
                
    if not valid_buttons:
        return False, []
        
    keywords = ["giveaway", "mystery", "box"]
    content = message.content.lower()
    if any(kw in content for kw in keywords):
        return True, valid_buttons
        
    for embed in message.embeds:
        title = (embed.title or "").lower()
        desc = (embed.description or "").lower()
        if any(kw in title for kw in keywords) or any(kw in desc for kw in keywords):
            return True, valid_buttons
            
    return False, []

# --- EVALUATOR PESAN BALASAN ---
def evaluate_response(msg):
    if not msg: return "timeout"
    
    content = msg.content.lower()
    
    if "zonk" in content or "trap" in content or "http" in content:
        return "zonk"
    
    if msg.attachments:
        return "zonk"
    for embed in msg.embeds:
        if embed.image or embed.thumbnail:
            return "zonk"
        embed_desc = (embed.description or "").lower()
        if "http" in embed_desc or "trap" in embed_desc:
            return "zonk"
            
    if "kamu sudah klaim" in content or "already picked" in content:
        return "already_claimed"
        
    if "limit" in content or "full" in content or "max" in content:
        return "exhausted"
        
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
    add_log(f"[{source}] Menemukan GA: {message.id}. Memulai eksekusi...")

    available_tumbals = list(tumbal_bots)
    random.shuffle(available_tumbals)
    
    ga_resolved = False
    final_result = "unknown"
    
    report_data = {
        "link": message.jump_url,
        "time": format_time_id(message.created_at),
        "results": []
    }

    for i, button in enumerate(buttons):
        button_safe = False
        
        while available_tumbals:
            vanguard = available_tumbals.pop(0)
            res = await click_and_wait(vanguard, button)
            report_data["results"].append({"name": f"[Tumbal] {vanguard.user.name}", "res": res})
            
            if res == "zonk":
                break 
            elif res == "already_claimed":
                continue 
            elif res == "exhausted":
                break 
            elif res == "timeout" or res == "error":
                continue 
            else:
                button_safe = True
                break
                
        if not available_tumbals and not button_safe:
            break

        if button_safe:
            main_res = await click_and_wait(main_bot, button)
            report_data["results"].insert(0, {"name": f"[UTAMA] {main_bot.user.name}", "res": main_res})

            if main_res == "zonk" or main_res == "already_claimed" or main_res == "exhausted":
                continue 
            else:
                final_result = main_res
                ga_resolved = True
                
                ffa_tasks = []
                for t_bot in available_tumbals:
                    jitter = random.uniform(0.5, 2.5)
                    ffa_tasks.append(delayed_click(t_bot, button, jitter, report_data))
                
                if ffa_tasks:
                    await asyncio.gather(*ffa_tasks)
                
                break 

    if ga_resolved or final_result != "unknown":
        await REDIS.hset(f"giveaway:{message.id}", mapping={
            "channel_id": str(message.channel.id),
            "timestamp": str(datetime.now().timestamp()),
            "result": final_result
        })
        if source == "LIVE":
            await REDIS.set("system:last_live_claim", str(datetime.now().timestamp()))
            
    if source == "SCAN" and len(report_data["results"]) > 0:
        scan_summary.append(report_data)
        add_log(f"[{source}] GA {message.id} selesai. Ditambahkan ke report.")
    
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
    if not main_bot: 
        add_log("Error: Bot utama (MAIN_TOKEN) tidak terbaca/belum siap!")
        return
    if scan_active: 
        add_log("Scan sedang berjalan, harap tunggu.")
        return
    
    scan_active = True
    scan_summary = [] 
    scan_finished_text = "Scan Selesai! 0 GA baru ditemukan." # Default text
    
    try:
        guild = main_bot.get_guild(TARGET_GUILD_ID)
        if not guild:
            add_log(f"Error: Tidak dapat menemukan server dengan ID {TARGET_GUILD_ID}")
            scan_finished_text = "Error: Guild tidak ditemukan."
            return

        add_log(f"Memulai Full Scan di server: {guild.name}")
        await REDIS.set("system:last_full_scan", str(datetime.now().timestamp()))
        
        cache_key = f"guild_channels:{TARGET_GUILD_ID}"
        channel_ids = await REDIS.smembers(cache_key)
        
        if not channel_ids:
            text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
            for c in text_channels: await REDIS.sadd(cache_key, c.id)
            channel_ids = [str(c.id) for c in text_channels]

        add_log(f"Total {len(channel_ids)} channel siap di-scan.")

        for ch_id in channel_ids:
            channel = main_bot.get_channel(int(ch_id))
            if not channel:
                try: channel = await main_bot.fetch_channel(int(ch_id))
                except: continue

            add_log(f"Menyapu channel: #{channel.name}...")
            try:
                async for msg in channel.history(limit=500):
                    if await REDIS.hexists(f"giveaway:{msg.id}", "result"):
                        add_log(f"Tembok Checkpoint tercapai di #{channel.name} (GA lama). Stop scan channel ini.")
                        break 
                    
                    is_valid, buttons = is_target_giveaway(msg)
                    if is_valid:
                        await process_giveaway(msg, buttons, "SCAN")
                            
            except discord.errors.Forbidden:
                add_log(f"Skipped #{channel.name} (403 Forbidden - Missing Access)")
                continue
            except Exception as e:
                add_log(f"Error di #{channel.name}: {str(e)}")
                continue
                
        if len(scan_summary) > 0:
            scan_finished_text = f"Scan Selesai! {len(scan_summary)} GA diproses."
            
    finally:
        scan_active = False
        add_log(scan_finished_text)


# --- UI & API ROUTER ---
@app.get("/get-summary")
async def get_summary():
    return {
        "is_scanning": scan_active,
        "total": len(scan_summary),
        "results": scan_summary,
        "logs": logs
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
            button {{ background: #4caf50; color: white; border: none; padding: 12px 20px; cursor: pointer; border-radius: 4px; font-weight: bold; width: 100%; font-size: 16px; margin-bottom: 10px; }}
            button:disabled {{ background: #555; cursor: not-allowed; }}
            .info-box {{ display: flex; justify-content: space-between; margin-bottom: 20px; background: #222; padding: 15px; border-radius: 4px; border-left: 4px solid #4caf50; font-size: 14px; }}
            .ga-card {{ background: #2a2a2a; padding: 15px; margin-top: 15px; border-radius: 6px; border-left: 4px solid #cf6679; }}
            .ga-card a {{ color: #4dabf7; text-decoration: none; font-weight: bold; font-size: 16px; }}
            .ga-card a:hover {{ text-decoration: underline; }}
            .ga-date {{ color: #999; font-size: 13px; margin-bottom: 10px; display: block; }}
            .res-list {{ margin: 0; padding-left: 20px; font-family: monospace; font-size: 14px; }}
            .res-item {{ padding: 3px 0; }}
            .status-text {{ font-weight: bold; color: #ffeb3b; text-align: center; margin-bottom: 20px; }}
            .layout {{ display: flex; gap: 20px; }}
            .col {{ flex: 1; }}
            pre {{ background: #000; color: #00ff00; padding: 15px; height: 500px; overflow-y: auto; font-size: 12px; border: 1px solid #333; border-radius: 6px; font-family: monospace; }}
        </style>
    </head>
    <body>
        <h2>Minesweeper Global Command</h2>
        <div class="card">
            <div class="info-box">
                <div><strong>Main Account:</strong> {main_bot.user.name if main_bot and main_bot.user else "Loading..."}</div>
                <div><strong>Tumbals Active:</strong> {len(tumbal_bots)}</div>
            </div>
            
            <button id="scanBtn" onclick="runScan()">RUN FULL SCAN</button>
            <div id="statusIndicator" class="status-text">Menunggu perintah...</div>
            
            <div class="layout">
                <div class="col">
                    <h3>Summary Scan (Hasil)</h3>
                    <div id="reportContainer">
                        <!-- Hasil scan akan muncul disini -->
                    </div>
                </div>
                <div class="col">
                    <h3>Live System Logs</h3>
                    <pre id="log-box"></pre>
                </div>
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
                    const logBox = document.getElementById('log-box');
                    
                    // Render Logs
                    logBox.innerText = data.logs.join('\\n');

                    if (data.is_scanning) {{
                        btn.disabled = true;
                        btn.innerText = "SCANNING IN PROGRESS...";
                        status.innerText = "Mengeksekusi penyisiran otomatis... Harap tunggu.";
                    }} else {{
                        btn.disabled = false;
                        btn.innerText = "RUN FULL SCAN";
                        if(data.total > 0) {{
                            status.innerText = `Scan Selesai! Total ada ${{data.total}} GA Active yang diproses.`;
                        }} else {{
                            status.innerText = "Scan Selesai! 0 GA baru ditemukan (Atau semua mentok di Checkpoint).";
                        }}
                    }}

                    // Render list
                    container.innerHTML = "";
                    if(data.results.length === 0 && !data.is_scanning) {{
                        container.innerHTML = "<div style='color:#777; font-style:italic;'>Belum ada data summary di sesi ini.</div>";
                    }}
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

            setInterval(renderState, 1000);
            renderState(); 
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
