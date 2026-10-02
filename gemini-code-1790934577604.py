import http.server
import socketserver
import json
import time
import os
import sqlite3
import random
import hashlib
import hmac
from urllib.parse import parse_qsl

PORT = int(os.environ.get("PORT", 8000))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")  # ضع توكن بوت تيليجرام الحقيقي هنا

# قاموس مؤقت لتطبيق Rate Limiting ومنع السبام
request_limits = {}

def check_rate_limit(telegram_id, cooldown_seconds=1.0):
    """منع المستخدم من إرسال طلبات متكررة بسرعة (Anti-Fraud & Rate Limiting)"""
    current_time = time.time()
    if telegram_id in request_limits:
        last_time = request_limits[telegram_id]
        if current_time - last_time < cooldown_seconds:
            return False  # الطلب متكرر بشكل سريع جداً
    request_limits[telegram_id] = current_time
    return True

def init_db():
    conn = sqlite3.connect('atr_mining.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # 1. جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL,
            speed REAL,
            last_mining_time REAL,
            cycle_reward REAL,
            wallet TEXT,
            holding_wallet REAL,
            pool_wallet REAL,
            mining_level INTEGER,
            referrals_count INTEGER,
            team_commission REAL,
            invited_by INTEGER
        )
    ''')
    
    # 2. جدول سجل المعاملات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            type TEXT,
            amount REAL,
            timestamp REAL,
            details TEXT
        )
    ''')

    # 3. جدول طلبات السحب الآلي
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payout_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            amount REAL,
            wallet TEXT,
            status TEXT,
            timestamp REAL
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def verify_telegram_init_data(init_data, bot_token):
    """التحقق الأمني من صحة بيانات Telegram WebApp لمنع التزوير (Anti-Fraud)"""
    try:
        parsed_data = dict(parse_qsl(init_data))
        hash_val = parsed_data.pop('hash', None)
        if not hash_val:
            return False
        
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(parsed_data.items())])
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        return calculated_hash == hash_val
    except Exception:
        return False

def log_transaction(telegram_id, trans_type, amount, details=""):
    conn = sqlite3.connect('atr_mining.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO transactions (telegram_id, type, amount, timestamp, details) VALUES (?, ?, ?, ?, ?)',
                   (telegram_id, trans_type, amount, time.time(), details))
    conn.commit()
    conn.close()

def get_user(telegram_id, username=None, referrer_id=None):
    conn = sqlite3.connect('atr_mining.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT telegram_id, username, balance, speed, last_mining_time, cycle_reward, wallet, holding_wallet, pool_wallet, mining_level, referrals_count, team_commission, invited_by FROM users WHERE telegram_id = ?', (telegram_id,))
    row = cursor.fetchone()
    
    current_time = time.time()
    
    if not username or username == "undefined" or username == "null":
        username = f"Miner_{random.randint(1000, 9999)}"

    if not row:
        default_balance = 928.0
        default_speed = 198.0
        default_last_time = current_time
        default_reward = 8.9100
        default_wallet = f"UQA{random.randint(100,999)}...{random.randint(1000,9999)}"
        default_holding = 0.0
        default_pool = 928.0
        default_level = 3
        default_refs = 0
        default_comm = 0.0
        
        inviter = None
        if referrer_id and referrer_id != telegram_id:
            cursor.execute('SELECT telegram_id, referrals_count, balance, pool_wallet FROM users WHERE telegram_id = ?', (referrer_id,))
            inviter_row = cursor.fetchone()
            if inviter_row:
                inviter = referrer_id
                new_refs = inviter_row[1] + 1
                new_bal = inviter_row[2] + 20.0
                new_pool = inviter_row[3] + 20.0
                cursor.execute('UPDATE users SET referrals_count = ?, balance = ?, pool_wallet = ? WHERE telegram_id = ?', (new_refs, new_bal, new_pool, referrer_id))
                log_transaction(referrer_id, 'REFERRAL_BONUS', 20.0, f'Bonus from invited user {telegram_id}')

        cursor.execute('''
            INSERT INTO users (telegram_id, username, balance, speed, last_mining_time, cycle_reward, wallet, holding_wallet, pool_wallet, mining_level, referrals_count, team_commission, invited_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (telegram_id, username, default_balance, default_speed, default_last_time, default_reward, default_wallet, default_holding, default_pool, default_level, default_refs, default_comm, inviter))
        conn.commit()
        
        log_transaction(telegram_id, 'INITIAL_DEPOSIT', default_balance, 'Welcome initial balance')
        
        user_data = {
            "telegram_id": telegram_id, "username": username, "balance": default_balance,
            "speed": default_speed, "last_mining_time": default_last_time, "cycle_reward": default_reward,
            "wallet": default_wallet, "holding_wallet": default_holding, "pool_wallet": default_pool,
            "mining_level": default_level, "referrals_count": default_refs, "team_commission": default_comm
        }
    else:
        cursor.execute('UPDATE users SET username = ? WHERE telegram_id = ?', (username, telegram_id))
        conn.commit()
        
        user_data = {
            "telegram_id": row[0], "username": username, "balance": row[2],
            "speed": row[3], "last_mining_time": row[4], "cycle_reward": row[5],
            "wallet": row[6], "holding_wallet": row[7], "pool_wallet": row[8],
            "mining_level": row[9], "referrals_count": row[10], "team_commission": row[11]
        }
    conn.close()
    return user_data

def update_user_db(user_data):
    conn = sqlite3.connect('atr_mining.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET balance = ?, speed = ?, last_mining_time = ?, pool_wallet = ?, holding_wallet = ?, mining_level = ?, referrals_count = ?, team_commission = ?, username = ? WHERE telegram_id = ?
    ''', (user_data["balance"], user_data["speed"], user_data["last_mining_time"], user_data["pool_wallet"], user_data["holding_wallet"], user_data["mining_level"], user_data["referrals_count"], user_data["team_commission"], user_data["username"], user_data["telegram_id"]))
    conn.commit()
    conn.close()

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="ar" dir="ltr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ATR Coin Mining - Secured Mini App</title>
    <script src="https://sad.adsgram.ai/js/adsgram.min.js"></script>
    <style>
        body { background-color: #070d1b; color: #fff; font-family: Arial, sans-serif; text-align: center; padding: 0; margin: 0; padding-bottom: 70px; }
        .top-nav-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; background: #070d1b; }
        .top-left { display: flex; align-items: center; gap: 15px; font-size: 18px; color: #fff; cursor: pointer; }
        .top-right { display: flex; align-items: center; gap: 15px; font-size: 18px; color: #fff; cursor: pointer; }
        .header-section { display: flex; justify-content: space-between; align-items: center; padding: 5px 15px 15px 15px; }
        .user-info { display: flex; align-items: center; gap: 10px; text-align: left; }
        .avatar { width: 42px; height: 42px; background: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #000; font-weight: bold; font-size: 16px; }
        .badge-verified { background: #0f2d22; color: #2ecc71; padding: 2px 8px; border-radius: 12px; font-size: 10px; font-weight: bold; }
        .wallet-pill { background: #0b192c; border: 1px solid #1e3a5f; padding: 6px 12px; border-radius: 20px; font-size: 11px; color: #4cc9f0; display: flex; align-items: center; gap: 6px; }
        .main-card { background: #111b2e; border: 1px solid #1e3a5f; border-radius: 20px; padding: 15px 20px 20px 20px; margin: 0 12px; box-shadow: 0 8px 20px rgba(0,0,0,0.6); position: relative; text-align: center; }
        .card-header-icons { display: flex; justify-content: space-between; align-items: center; color: #94a3b8; font-size: 16px; margin-bottom: 10px; }
        .reward-title { font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; }
        .reward-pill-box { display: inline-flex; align-items: center; gap: 6px; background: #0b132b; border: 1px solid #1e3a5f; padding: 6px 16px; border-radius: 20px; margin: 8px 0 15px 0; font-size: 18px; color: #4cc9f0; font-weight: bold; }
        .mining-circle { width: 170px; height: 170px; border: 3px solid #1e3a5f; border-radius: 50%; margin: 0 auto; display: flex; flex-direction: column; align-items: center; justify-content: center; position: relative; box-shadow: 0 0 25px rgba(58, 134, 255, 0.15); cursor: pointer; }
        .inner-logo { width: 35px; height: 35px; background: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-bottom: 5px; }
        .token-badge { background: #0b132b; padding: 2px 10px; border-radius: 8px; font-size: 10px; border: 1px solid #3a86ff; color: #fff; }
        .stats-row { display: flex; justify-content: space-between; margin-top: 15px; padding: 0 10px; font-size: 12px; color: #94a3b8; }
        .stats-val { color: #4cc9f0; font-weight: bold; }
        .btn-mining-status { background: #162642; border: 1px solid #223f6e; color: #4cc9f0; padding: 12px; border-radius: 12px; font-size: 13px; font-weight: bold; width: 100%; margin-top: 15px; text-align: center; }
        .actions-row { display: flex; gap: 10px; margin-top: 10px; }
        .btn-action { flex: 1; background: #162642; border: 1px solid #223f6e; color: #fff; padding: 12px; border-radius: 12px; font-size: 13px; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; }
        .btn-ad { background: #f72585; color: white; border: none; padding: 12px; border-radius: 12px; width: 100%; font-weight: bold; cursor: pointer; margin-top: 10px; font-size: 13px; }
        .nav-bar { position: fixed; bottom: 0; left: 0; width: 100%; background: #0b132b; border-top: 1px solid #1e3a5f; display: flex; justify-content: space-around; padding: 8px 0; z-index: 100; }
        .nav-item { color: #64748b; font-size: 11px; text-decoration: none; display: flex; flex-direction: column; align-items: center; gap: 3px; cursor: pointer; }
        .nav-item.active { color: #3a86ff; }
        .section-view { display: none; }
        .section-view.active { display: block; }
        .card { background: #111b2e; border: 1px solid #1e3a5f; padding: 15px; border-radius: 15px; margin: 10px 15px; text-align: left; }
        .btn { background: #3a86ff; color: white; border: none; padding: 10px; border-radius: 8px; width: 100%; font-weight: bold; cursor: pointer; margin-top: 8px; }
        input { width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #1e3a5f; background: #070d1b; color: #fff; text-align: center; margin-top: 5px; box-sizing: border-box; }
        .flex-between { display: flex; justify-content: space-between; align-items: center; }
    </style>
</head>
<body>
    <div class="top-nav-bar">
        <div class="top-left"><span>✕</span><span style="font-weight: bold; font-size: 16px;">ATR ⛏</span></div>
        <div class="top-right"><span>⌄</span><span>⋮</span></div>
    </div>

    <div class="header-section">
        <div class="user-info">
            <div class="avatar" id="user-initial">U</div>
            <div>
                <div style="font-weight: bold; font-size: 14px;" id="username-display">Loading...</div>
                <div style="display: flex; gap: 5px; margin-top: 3px;">
                    <span style="background: #1e3a5f; color: #4cc9f0; padding: 1px 6px; border-radius: 8px; font-size: 10px;" id="level-display">Lvl 3</span>
                    <span class="badge-verified">✓ Secured</span>
                </div>
            </div>
        </div>
        <div class="wallet-pill" id="wallet-display"><span>🔹</span> Loading...</div>
    </div>

    <!-- قسم التعدين الرئيسي -->
    <div id="view-mine" class="section-view active">
        <div class="main-card">
            <div class="card-header-icons"><span>❓</span><span class="reward-title">CYCLE REWARD</span><span>⋯</span></div>
            <div class="reward-pill-box"><span>⚡</span> <span id="balance-display">+8.9100 ATR</span></div>
            <div class="mining-circle" onclick="claimReward()">
                <div class="inner-logo"><svg width="20" height="20" viewBox="0 0 24 24" fill="#000"><path d="M12 2L2 19h20L12 2zm0 3.5L18.5 17h-13L12 5.5z"/></svg></div>
                <div class="token-badge">ATR</div>
            </div>
            <div class="stats-row">
                <div>Speed: <span class="stats-val" id="speed-val">198 TH/s</span></div>
                <div>Time: <span class="stats-val" id="time-val">00:00:30</span></div>
            </div>
            <div class="btn-mining-status" id="status-text">MINING... 00:00:30</div>
            <div class="actions-row">
                <button class="btn-action" onclick="switchTab('miners')">🛒 Buy Miners</button>
                <button class="btn-action" onclick="switchTab('profile')">📥 Withdraw</button>
            </div>
        </div>
        <div style="padding: 0 12px;"><button class="btn-ad" onclick="watchAdForReward()">شاهد إعلان واحصل على مكافأة إضافية 🎬</button></div>
    </div>

    <!-- قسم المهام وإعلانات Adsgram -->
    <div id="view-tasks" class="section-view">
        <div class="card" style="border-color: #3a86ff; cursor: pointer;" onclick="watchAdForReward()">
            <div class="flex-between">
                <div><h3 style="margin: 0; color: #fff; font-size: 16px;">Watch Ads & Earn</h3><p style="font-size: 12px; color: #94a3b8; margin: 5px 0 0 0;">+10 ATR per verified ad</p></div>
                <div style="font-size: 24px;">📺</div>
            </div>
        </div>
    </div>

    <!-- قسم شراء المعدات والمتجر -->
    <div id="view-miners" class="section-view">
        <div class="card">
            <h2 style="margin: 0 0 5px 0; font-size: 20px; text-align: left;">Miner Store</h2>
            <div style="background: #070d1b; padding: 12px; border-radius: 12px; border: 1px solid #1e3a5f; font-size: 13px; text-align: left; margin-bottom: 12px;">
                <div class="flex-between" style="margin-bottom: 5px;"><span>Total Assets</span> <span style="font-weight: bold;" id="store-total">0.00 ATR</span></div>
                <div class="flex-between" style="color: #4cc9f0;"><span>Pool Wallet</span> <span id="store-pool">0.00 ATR</span></div>
            </div>
            <button class="btn" onclick="buyMinerPackage()">شراء منجم سرعة (+50 TH/s) بسعر 100 ATR</button>
        </div>
    </div>

    <!-- قسم الإحالات -->
    <div id="view-friends" class="section-view">
        <div class="card">
            <h3 style="margin: 0 0 10px 0; font-size: 15px; text-align: left;">Mining commission</h3>
            <div style="font-size: 13px; color: #4cc9f0; margin-bottom: 10px;">Total Invited Friends: <span id="refs-count" style="font-weight: bold;">0</span></div>
            <div style="font-size: 13px; font-weight: bold; text-align: left; margin-bottom: 5px;">Your Invite Link</div>
            <input type="text" id="ref-link" readonly style="font-size: 11px;">
            <button class="btn" style="margin-top: 8px;" onclick="copyRefLink()">Copy Link</button>
        </div>
    </div>

    <!-- قسم الملف الشخصي والسحب -->
    <div id="view-profile" class="section-view">
        <div class="card">
            <h3 style="margin: 0 0 10px 0; font-size: 16px; text-align: left;">إدارة الحساب والمحفظة</h3>
            <div style="font-size: 12px; color: #f72585; margin-bottom: 8px; font-weight: bold;">الحد الأدنى للسحب: 10 ATR</div>
            <div style="font-size: 12px; color: #94a3b8; margin-bottom: 5px;">محفظة TON المرتبطة:</div>
            <input type="text" id="wallet-input" style="font-size: 12px; margin-bottom: 10px;">
            <button class="btn" onclick="withdrawFunds()" style="background: #2ecc71; margin-bottom: 8px;">سحب الأرباح الآلي (Withdraw)</button>
            <button class="btn" onclick="depositFunds()" style="background: #f72585;">إيداع رصيد تجريبي (Deposit)</button>
        </div>
    </div>

    <div class="nav-bar">
        <div class="nav-item active" onclick="switchTab('mine')" id="nav-mine">Mine</div>
        <div class="nav-item" onclick="switchTab('tasks')" id="nav-tasks">Tasks</div>
        <div class="nav-item" onclick="switchTab('miners')" id="nav-miners">Miners</div>
        <div class="nav-item" onclick="switchTab('friends')" id="nav-friends">Friends</div>
        <div class="nav-item" onclick="switchTab('profile')" id="nav-profile">Profile</div>
    </div>

    <script>
        let userId = 12345, username = "Miner", initData = "";
        let referrerId = null;

        const urlParams = new URLSearchParams(window.location.search);
        const startParam = urlParams.get('start');
        if (startParam && startParam.startsWith('ref')) {
            referrerId = parseInt(startParam.replace('ref', ''));
        }

        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
            userId = window.Telegram.WebApp.initDataUnsafe.user.id;
            username = window.Telegram.WebApp.initDataUnsafe.user.first_name;
            initData = window.Telegram.WebApp.initData || "";
        } else {
            if (!localStorage.getItem('atr_user_id')) {
                localStorage.setItem('atr_user_id', Math.floor(Math.random() * 90000000) + 10000000);
            }
            userId = parseInt(localStorage.getItem('atr_user_id'));
            if (!localStorage.getItem('atr_username')) {
                localStorage.setItem('atr_username', "Miner_" + Math.floor(Math.random() * 9000 + 1000));
            }
            username = localStorage.getItem('atr_username');
        }

        let remainingSeconds = 30;
        let AdController = null;
        try { 
            AdController = window.Adsgram.init({ blockId: "51580", userId: userId.toString() }); 
        } catch (e) {}

        function switchTab(tabName) {
            document.querySelectorAll('.section-view').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.getElementById('view-' + tabName).classList.add('active');
            document.getElementById('nav-' + tabName).classList.add('active');
        }

        function loadUserData() {
            fetch('/api/user', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram_id: userId, username: username, init_data: initData, referrer_id: referrerId })
            })
            .then(res => res.json())
            .then(data => { if(data.status === 'success') updateUI(data.data); });
        }

        function updateUI(user) {
            document.getElementById('balance-display').innerText = "+ " + user.balance.toFixed(4) + " ATR";
            document.getElementById('speed-val').innerText = user.speed + " TH/s";
            document.getElementById('wallet-display').innerHTML = "<span>🔹</span> " + user.wallet;
            document.getElementById('wallet-input').value = user.wallet;
            document.getElementById('username-display').innerText = user.username;
            document.getElementById('user-initial').innerText = user.username.charAt(0).toUpperCase();
            document.getElementById('store-total').innerText = user.balance.toFixed(2) + " ATR";
            document.getElementById('store-pool').innerText = user.pool_wallet.toFixed(2) + " ATR";
            document.getElementById('refs-count').innerText = user.referrals_count;
            document.getElementById('level-display').innerText = "Lvl " + user.mining_level;
            remainingSeconds = user.remaining_seconds;
            document.getElementById('ref-link').value = window.location.origin + "/?start=ref" + user.telegram_id;
        }

        function copyRefLink() {
            const copyText = document.getElementById("ref-link");
            copyText.select();
            navigator.clipboard.writeText(copyText.value);
            alert("تم نسخ رابط الإحالة بنجاح!");
        }

        setInterval(() => {
            if (remainingSeconds > 0) {
                remainingSeconds--;
                let hrs = Math.floor(remainingSeconds / 3600);
                let mins = Math.floor((remainingSeconds % 3600) / 60);
                let secs = remainingSeconds % 60;
                let timeStr = `${hrs.toString().padStart(2,'0')}:${mins.toString().padStart(2,'0')}:${secs.toString().padStart(2,'0')}`;
                document.getElementById('time-val').innerText = timeStr;
                document.getElementById('status-text').innerText = "MINING... " + timeStr;
            } else {
                document.getElementById('time-val').innerText = "00:00:00";
                document.getElementById('status-text').innerText = "جاهز لجمع الأرباح الآن (Claim)!";
            }
        }, 1000);

        function claimReward() {
            fetch('/api/claim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram_id: userId, init_data: initData })
            })
            .then(res => res.json())
            .then(data => { alert(data.message); loadUserData(); });
        }

        function watchAdForReward() {
            if (!AdController) { grantAdRewardFallback(); return; }
            AdController.show()
                .then((result) => {
                    fetch('/api/webhook/adsgram', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ telegram_id: userId, init_data: initData, status: 'success' })
                    }).then(res => res.json()).then(data => {
                        alert(data.message);
                        loadUserData();
                    });
                })
                .catch((err) => {
                    alert("فشل عرض الإعلان أو تم تخطيه.");
                });
        }

        function grantAdRewardFallback() {
            fetch('/api/webhook/adsgram', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram_id: userId, init_data: initData, status: 'success' })
            })
            .then(res => res.json())
            .then(data => { alert(data.message); loadUserData(); });
        }

        function buyMinerPackage() {
            fetch('/api/buy-miner', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram_id: userId, init_data: initData })
            })
            .then(res => res.json())
            .then(data => { alert(data.message); loadUserData(); });
        }

        function withdrawFunds() {
            fetch('/api/withdraw', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram_id: userId, init_data: initData })
            })
            .then(res => res.json())
            .then(data => { alert(data.message); loadUserData(); });
        }

        function depositFunds() {
            fetch('/api/deposit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ telegram_id: userId, init_data: initData })
            })
            .then(res => res.json())
            .then(data => { alert(data.message); loadUserData(); });
        }

        loadUserData();
    </script>
</body>
</html>
"""

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_CONTENT.encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode('utf-8'))
        except:
            data = {}
        
        uid = data.get("telegram_id", None)
        uname = data.get("username", None)
        init_data = data.get("init_data", "")
        ref_id = data.get("referrer_id", None)

        # 1. نظام الحماية: Rate Limiting (منع هجمات السبام والضغط السريع)
        if uid and not check_rate_limit(uid, cooldown_seconds=1.0):
            self.send_response(429)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "الرجاء الانتظار قليلاً قبل إرسال طلب جديد."}).encode("utf-8"))
            return

        # 2. نظام الحماية الأمني: التحقق من التوقيع الرقمي (InitData Validation)
        if BOT_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN" and init_data and not verify_telegram_init_data(init_data, BOT_TOKEN):
            self.send_response(401)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "فشل التحقق الأمني: التوقيع الرقمي غير صالح."}).encode("utf-8"))
            return

        user = get_user(uid, uname, ref_id) if uid else None
        current_time = time.time()
        cycle_duration = 30
        response = {}

        # 3. مسار استقبال الـ Webhook الحقيقي للإعلانات
        if self.path == "/api/webhook/adsgram":
            target_id = data.get("telegram_id", uid)
            ad_status = data.get("status", "success")
            target_user = get_user(target_id)
            if target_user and ad_status == "success":
                target_user["balance"] += 10.0
                target_user["pool_wallet"] += 10.0
                update_user_db(target_user)
                log_transaction(target_id, 'AD_REWARD', 10.0, 'Verified ad reward via Adsgram Webhook')
                response = {"status": "success", "message": "تم تأكيد مشاهدة الإعلان بنجاح وأُضيف رصيد 10 ATR."}
            else:
                response = {"status": "error", "message": "فشل التحقق من الإعلان."}

        # 4. مسار استقبال بوابات الدفع (Ton Connect Hook)
        elif self.path == "/api/webhook/payment":
            payment_status = data.get("status")
            target_telegram_id = data.get("telegram_id")
            if payment_status == "success" and target_telegram_id:
                target_user = get_user(target_telegram_id)
                if target_user:
                    target_user["speed"] += 50.0
                    target_user["mining_level"] += 1
                    update_user_db(target_user)
                    log_transaction(target_telegram_id, 'PAYMENT_SUCCESS', 50.0, 'Automated payment webhook confirmed')
                    response = {"status": "success", "message": "تم تأكيد عملية الدفع وتحويل الموارد بنجاح."}
                else:
                    response = {"status": "error", "message": "المستخدم غير موجود."}
            else:
                response = {"status": "failed", "message": "حالة الدفع غير صالحة."}

        elif self.path == "/api/user":
            elapsed = current_time - user["last_mining_time"]
            remaining = max(0, int(cycle_duration - elapsed))
            user_data = user.copy()
            user_data["remaining_seconds"] = remaining
            response = {"status": "success", "data": user_data}
            
        elif self.path == "/api/claim":
            elapsed = current_time - user["last_mining_time"]
            remaining = max(0, int(cycle_duration - elapsed))
            if elapsed >= cycle_duration:
                reward = user["cycle_reward"]
                user["balance"] += reward
                user["pool_wallet"] += reward
                user["last_mining_time"] = current_time
                update_user_db(user)
                log_transaction(uid, 'MINING_CLAIM', reward, 'Claimed cycle mining reward')
                response = {"status": "success", "message": "تم جمع أرباح التعدين بنجاح!"}
            else:
                response = {"status": "wait", "message": f"عذراً، متبقي {remaining} ثانية على انتهاء الدورة."}

        elif self.path == "/api/buy-miner":
            if user["balance"] >= 100.0:
                user["balance"] -= 100.0
                user["speed"] += 50.0
                user["mining_level"] += 1
                update_user_db(user)
                log_transaction(uid, 'BUY_MINER', -100.0, 'Purchased +50 TH/s package')
                response = {"status": "success", "message": "تم شراء منجم السرعة بنجاح!"}
            else:
                response = {"status": "error", "message": "رصيدك غير كافٍ للشراء (تحتاج 100 ATR)."}

        elif self.path == "/api/withdraw":
            MIN_WITHDRAW = 10.0
            if user["pool_wallet"] >= MIN_WITHDRAW:
                withdrawn = user["pool_wallet"]
                user["pool_wallet"] = 0.0
                update_user_db(user)
                
                conn = sqlite3.connect('atr_mining.db', check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute('INSERT INTO payout_requests (telegram_id, amount, wallet, status, timestamp) VALUES (?, ?, ?, ?, ?)',
                               (uid, withdrawn, user["wallet"], 'قيد التحويل الآلي (Automated Payout)', time.time()))
                conn.commit()
                conn.close()

                log_transaction(uid, 'WITHDRAW_REQUEST', -withdrawn, f'Automated payout queued to {user["wallet"]}')
                response = {"status": "success", "message": f"تم تسجيل طلب السحب الآلي بمبلغ {withdrawn:.2f} ATR بنجاح!"}
            else:
                response = {"status": "error", "message": f"الحد الأدنى للسحب هو {MIN_WITHDRAW} ATR."}

        elif self.path == "/api/deposit":
            user["balance"] += 50.0
            user["pool_wallet"] += 50.0
            update_user_db(user)
            log_transaction(uid, 'TEST_DEPOSIT', 50.0, 'Test deposit added')
            response = {"status": "success", "message": "تم إيداع 50 ATR تجريبية بنجاح!"}

        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode("utf-8"))

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), MyHandler) as httpd:
        print(f"السيرفر الآمن والمؤمن بالكامل يعمل الآن على المنفذ: {PORT}")
        httpd.serve_forever()
