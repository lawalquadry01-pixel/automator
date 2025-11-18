import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import random
import sqlite3
import time
import threading
import requests
import json
from types import SimpleNamespace
import hashlib

# Replace with your bot token
TOKEN = '8545496074:AAEk36BhoJC2X6Beue2YaqSA-3nEdhDrvSk'

# AI Service
GROQ_API_KEY = "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"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Helius for Solana monitoring
HELIUS_API_KEY = "7fa3cc87-15d9-4fe4-94fc-59b4918a7d2c"
HELIUS_API_URL = "https://api.helius.xyz/v0"
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com"

# Alchemy for EVM monitoring
ALCHEMY_ETH_BASE_KEY = "g6LUFcseRIjREhKr_sR8l"
ALCHEMY_BSC_KEY = "1x-gGusRgMp5ZS5HrTwGO"

bot = telebot.TeleBot(TOKEN)

# Database setup for persistence
conn = sqlite3.connect('memecoin_bot.db', check_same_thread=False)
cursor = conn.cursor()

# Migration for new columns if needed
try:
    cursor.execute("ALTER TABLE users ADD COLUMN referrer_username TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass  # Column already exists

try:
    cursor.execute("ALTER TABLE groups ADD COLUMN token_address TEXT")
    cursor.execute("ALTER TABLE groups ADD COLUMN token_chain TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass  # Columns already exist

try:
    cursor.execute("ALTER TABLE groups ADD COLUMN group_invite_link TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass  # Column already exists

# Create tables
cursor.execute('''
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    title TEXT,
    welcome_msg TEXT,
    goodbye_msg TEXT,
    introduction_msg TEXT,
    banned_words TEXT,
    anti_spam_enabled INTEGER DEFAULT 1,
    buy_alerts_enabled INTEGER DEFAULT 0,
    raiding_enabled INTEGER DEFAULT 0,
    twitter_handle TEXT,
    channel_link TEXT,
    bot_link TEXT,
    token_address TEXT,
    token_chain TEXT,
    group_invite_link TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    verified INTEGER DEFAULT 0,
    referrer_id INTEGER,
    referrer_username TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS referrals (
    group_id INTEGER,
    user_id INTEGER,
    referred_count INTEGER DEFAULT 0,
    PRIMARY KEY (group_id, user_id)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS engagement (
    group_id INTEGER,
    user_id INTEGER,
    message_count INTEGER DEFAULT 0,
    PRIMARY KEY (group_id, user_id)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS admins (
    group_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (group_id, user_id)
)
''')

conn.commit()

# User states for stateful flows
user_states = {}

# Verification pending users in groups (for anti-spam kick)
pending_verifications = {}

# Track user message violations
user_violations = {}

# Function to generate random verification challenge
def generate_challenge():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    correct = a + b
    options = [correct, correct - 1, correct + 1, correct + 2]
    random.shuffle(options)
    return a, b, correct, options

# AI Moderation with Groq
def check_message_with_ai(text):
    """Check if message contains hate speech, spam, or offensive content using Groq"""
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a content moderator. Analyze messages for hate speech, spam, offensive content, or scams. Respond with only 'VIOLATES' or 'OK'."
                },
                {
                    "role": "user",
                    "content": f"Analyze this message: {text}"
                }
            ],
            "temperature": 0.1,
            "max_tokens": 10
        }
        
        response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            result = response.json()
            answer = result['choices'][0]['message']['content'].strip().upper()
            return 'VIOLATES' in answer
        return False
    except Exception as e:
        print(f"AI moderation error: {e}")
        return False

# Blockchain monitoring functions
def monitor_solana_token(group_id, token_address):
    """Monitor Solana token buys using Helius"""
    while True:
        try:
            cursor.execute("SELECT buy_alerts_enabled FROM groups WHERE id = ?", (group_id,))
            result = cursor.fetchone()
            if not result or not result[0]:
                time.sleep(60)
                continue
            
            # Use Helius Enhanced Transactions API
            url = f"{HELIUS_RPC_URL}/?api-key={HELIUS_API_KEY}"
            payload = {
                "jsonrpc": "2.0",
                "id": "helius-test",
                "method": "getSignaturesForAddress",
                "params": [token_address, {"limit": 5}]
            }
            
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'result' in data and data['result']:
                    # Process transactions (simplified - you'll need to parse transaction details)
                    # This is a placeholder for actual transaction parsing
                    for tx in data['result']:
                        # You would need to fetch transaction details and parse for buys
                        # send_buy_alert(group_id, token_address, "amount", "buyer", "solana")
                        pass
            
        except Exception as e:
            print(f"Solana monitoring error for group {group_id}: {e}")
        
        time.sleep(30)  # Check every 30 seconds

def monitor_evm_token(group_id, token_address, chain="eth"):
    """Monitor EVM token buys using Alchemy"""
    while True:
        try:
            cursor.execute("SELECT buy_alerts_enabled FROM groups WHERE id = ?", (group_id,))
            result = cursor.fetchone()
            if not result or not result[0]:
                time.sleep(60)
                continue
            
            # Select appropriate Alchemy key based on chain
            if chain == "eth" or chain == "base":
                api_key = ALCHEMY_ETH_BASE_KEY
                network = "eth-mainnet" if chain == "eth" else "base-mainnet"
            elif chain == "bsc":
                api_key = ALCHEMY_BSC_KEY
                network = "bnb-mainnet"
            else:
                time.sleep(60)
                continue
            
            url = f"https://{network}.g.alchemy.com/v2/{api_key}"
            
            # Get latest block
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_blockNumber",
                "params": []
            }
            
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                # This is a simplified placeholder
                # You would need to:
                # 1. Get token transfer events
                # 2. Filter for buys (transfers to the token address)
                # 3. Parse amounts and buyer addresses
                # send_buy_alert(group_id, token_address, "amount", "buyer", chain)
                pass
            
        except Exception as e:
            print(f"EVM monitoring error for group {group_id} on {chain}: {e}")
        
        time.sleep(30)  # Check every 30 seconds

def send_buy_alert(group_id, token_address, amount, buyer_address, chain="solana"):
    """Send buy alert to group"""
    try:
        cursor.execute("SELECT buy_alerts_enabled FROM groups WHERE id = ?", (group_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            message = f"🚀 New Buy Alert!\n"
            message += f"Chain: {chain.upper()}\n"
            message += f"Amount: {amount}\n"
            message += f"Token: {token_address[:8]}...{token_address[-6:]}\n"
            message += f"Buyer: {buyer_address[:8]}...{buyer_address[-6:]}"
            
            bot.send_message(group_id, message)
    except Exception as e:
        print(f"Error sending buy alert: {e}")

# Polling thread for raiding (Twitter/X posts)
def poll_twitter(group_id, twitter_handle):
    last_tweet_id = None
    while True:
        try:
            cursor.execute("SELECT raiding_enabled FROM groups WHERE id = ?", (group_id,))
            result = cursor.fetchone()
            if not result or not result[0]:
                time.sleep(300)
                continue
            
            # Note: Twitter API v2 requires authentication
            # This is a placeholder - you'll need to implement actual Twitter API v2
            # For now, this will just sleep
            # response = requests.get(f"https://api.twitter.com/2/users/by/username/{twitter_handle}/tweets", 
            #                        headers={"Authorization": "Bearer YOUR_TWITTER_BEARER_TOKEN"})
            
        except Exception as e:
            print(f"Twitter polling error: {e}")
        time.sleep(300)  # Poll every 5 minutes

# Start monitoring threads for groups
def start_monitoring_threads():
    cursor.execute("SELECT id, token_address, token_chain FROM groups WHERE buy_alerts_enabled = 1")
    for group_id, token_address, chain in cursor.fetchall():
        if token_address and chain:
            if chain == "solana":
                threading.Thread(target=monitor_solana_token, args=(group_id, token_address), daemon=True).start()
            elif chain in ["eth", "bsc", "base"]:
                threading.Thread(target=monitor_evm_token, args=(group_id, token_address, chain), daemon=True).start()
    
    cursor.execute("SELECT id, twitter_handle FROM groups WHERE raiding_enabled = 1")
    for group_id, twitter_handle in cursor.fetchall():
        if twitter_handle:
            threading.Thread(target=poll_twitter, args=(group_id, twitter_handle), daemon=True).start()

# Handle bot start for users
@bot.message_handler(commands=['start'])
def start(message):
    # Ignore start commands in groups - only process in private chat
    if message.chat.type in ['group', 'supergroup']:
        return
    
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    # Check for referral parameter
    has_referral = len(message.text.split()) > 1
    
    if not has_referral:
        # Direct start without referral - just show promotional message
        promo_markup = InlineKeyboardMarkup(row_width=2)
        promo_markup.add(InlineKeyboardButton("Add Automator to Your Group", url=f"t.me/{bot.get_me().username}?startgroup=true"))
        promo_markup.add(InlineKeyboardButton("Use LumiFlash Bot", url="t.me/lumiflash_bot"))
        bot.send_message(message.chat.id, 
                        "Automator is your community AI manager 🤖\n\n"
                        "It verifies members, tracks engagement, and grows your project automatically.\n\n"
                        "Meet LumiFlash — your smart trading bot for Solana & EVM.",
                        reply_markup=promo_markup)
        return
    
    # Has referral parameter - proceed with verification flow
    ref_param = message.text.split()[1]
    
    # Check if already verified
    cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
    existing_user = cursor.fetchone()
    
    if existing_user and existing_user[0] == 1:
        # Already verified, show referral info
        group_invite = None
        ref_link = None
        
        # Get group info from referral parameter if provided
        if has_referral:
            parts = ref_param.split('_')
            if len(parts) >= 3:
                group_hash = parts[-1]
                cursor.execute("SELECT id, title, group_invite_link FROM groups")
                for gid, gtitle, ginvite in cursor.fetchall():
                    if hashlib.md5(str(gid).encode()).hexdigest()[:6] == group_hash:
                        group_name_clean = gtitle.lower().replace(' ', '').replace('-', '')[:15]
                        ref_link = f"t.me/{bot.get_me().username}?start={username}_{group_name_clean}_{group_hash}"
                        group_invite = ginvite
                        break
        
        # If no group found from referral, use first available group
        if not ref_link:
            target_group_id = user_states.get(user_id, {}).get('target_group_id')
            
            if target_group_id:
                cursor.execute("SELECT id, title, group_invite_link FROM groups WHERE id = ?", (target_group_id,))
            else:
                cursor.execute("SELECT id, title, group_invite_link FROM groups WHERE group_invite_link IS NOT NULL ORDER BY id ASC LIMIT 1")
            group_data = cursor.fetchone()
            if group_data:
                group_id_for_link = group_data[0]
                group_title = group_data[1]
                group_invite = group_data[2]
                group_name_clean = group_title.lower().replace(' ', '').replace('-', '')[:15]
                group_hash = hashlib.md5(str(group_id_for_link).encode()).hexdigest()[:6]
                ref_link = f"t.me/{bot.get_me().username}?start={username}_{group_name_clean}_{group_hash}"
            else:
                # No groups at all
                ref_link = f"t.me/{bot.get_me().username}?start={username}"
        
        cursor.execute("SELECT SUM(referred_count) FROM referrals WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        referred = result[0] if result and result[0] else 0
        
        # Build action buttons
        action_markup = InlineKeyboardMarkup(row_width=2)
        
        # ALWAYS add Join Group button if we have a group invite link
        if group_invite:
            action_markup.add(InlineKeyboardButton("Join Group 👥", url=group_invite))
        
        # Get buttons for the SPECIFIC group
        if group_data:
            cursor.execute("SELECT channel_link, bot_link, twitter_handle FROM groups WHERE id = ?", (group_data[0],))
            links = cursor.fetchone()
            if links:
                if links[0] and links[0] != group_invite:
                    action_markup.add(InlineKeyboardButton("Join Channel 📢", url=links[0]))
                if links[1]:
                    action_markup.add(InlineKeyboardButton("Join Bot 🤖", url=links[1]))
                if links[2]:
                    action_markup.add(InlineKeyboardButton("Follow on X 🐦", url=links[2]))
        if links:
            if links[0] and links[0] != group_invite:
                action_markup.add(InlineKeyboardButton("Join Channel 📢", url=links[0]))
            if links[1]:
                action_markup.add(InlineKeyboardButton("Join Bot 🤖", url=links[1]))
        
        action_markup.add(InlineKeyboardButton("Refresh 🔄", callback_data="refresh"))
        
        bot.send_message(message.chat.id, 
                        f"You're already verified! 🎉\n\nHere's your referral link to invite friends 🚀\n{ref_link}\nUsers referred: {referred}",
                        reply_markup=action_markup)
        
        # Send LumiFlash promotion
        promo_markup = InlineKeyboardMarkup(row_width=2)
        promo_markup.add(InlineKeyboardButton("Add Automator to Your Group", url=f"t.me/{bot.get_me().username}?startgroup=true"))
        promo_markup.add(InlineKeyboardButton("Use LumiFlash Bot", url="t.me/lumiflash_bot"))
        bot.send_message(message.chat.id, 
                        "Automator is your community AI manager 🤖\n\n"
                        "It verifies members, tracks engagement, and grows your project automatically.\n\n"
                        "Meet LumiFlash — your smart trading bot for Solana & EVM.",
                        reply_markup=promo_markup)
        return
    
    # New user or unverified with referral: Parse referral parameter
    referrer_id = None
    referrer_username = None
    referral_group_id = None
    
    if ref_param.startswith('invite_'):
        # Group invite link format: invite_groupname_hash
        parts = ref_param.split('_')
        if len(parts) >= 3:
            group_hash = parts[-1]
            # Find group by matching hash
            cursor.execute("SELECT id FROM groups")
            for (gid,) in cursor.fetchall():
                if hashlib.md5(str(gid).encode()).hexdigest()[:6] == group_hash:
                    referral_group_id = gid
                    break
    else:
        # User referral link format: username_groupname_hash
        parts = ref_param.split('_')
        if len(parts) >= 3:
            group_hash = parts[-1]
            referrer_username = parts[0]
            
            # Find group
            cursor.execute("SELECT id FROM groups")
            for (gid,) in cursor.fetchall():
                if hashlib.md5(str(gid).encode()).hexdigest()[:6] == group_hash:
                    referral_group_id = gid
                    break
            
            # Find referrer
            cursor.execute("SELECT id FROM users WHERE username = ?", (referrer_username,))
            referrer = cursor.fetchone()
            if referrer:
                referrer_id = referrer[0]
        else:
            # Simple username referral (legacy)
            referrer_username = ref_param
            cursor.execute("SELECT id FROM users WHERE username = ?", (referrer_username,))
            referrer = cursor.fetchone()
            if referrer:
                referrer_id = referrer[0]
    
    # Insert or update user
    if referrer_id:
        cursor.execute("INSERT OR REPLACE INTO users (id, username, referrer_id, referrer_username, verified) VALUES (?, ?, ?, ?, 0)", 
                      (user_id, username, referrer_id, referrer_username))
    else:
        cursor.execute("INSERT OR IGNORE INTO users (id, username, verified) VALUES (?, ?, 0)", (user_id, username))
        cursor.execute("UPDATE users SET verified = 0 WHERE id = ?", (user_id,))
    conn.commit()
    
    # Send welcome and verify
    bot.send_message(message.chat.id, "Welcome to the MemeCoin Community Bot! 🎉\nPlease verify to get started.")
    # Store which group user is trying to join
    if user_id not in user_states:
        user_states[user_id] = {}
    user_states[user_id]['target_group_id'] = referral_group_id  # Use referral_group_id, not target_group_id
    send_verification_challenge(message.chat.id, user_id)
    
def send_verification_challenge(chat_id, user_id):
    # Only send verification in private chat
    try:
        chat = bot.get_chat(chat_id)
        if chat.type in ['group', 'supergroup']:
            return
    except:
        pass
    
    a, b, correct, options = generate_challenge()
    markup = InlineKeyboardMarkup(row_width=2)
    for opt in options:
        markup.add(InlineKeyboardButton(f"{opt}", callback_data=f"verif_{a}_{b}_{opt}_{user_id}"))
    
    verif_msg = bot.send_message(chat_id, f"What's {a} + {b}? 🤔", reply_markup=markup)
    user_states[user_id] = {'verif_msg_id': verif_msg.message_id, 'attempts': 0}

@bot.callback_query_handler(func=lambda call: call.data.startswith('verif_'))
def handle_verification(call):
    parts = call.data.split('_')
    a, b, selected, user_id = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
    correct = a + b
    
    if selected == correct:
        cursor.execute("UPDATE users SET verified = 1 WHERE id = ?", (user_id,))
        conn.commit()
        
        # Delete verification message
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        # Send confirmation
        username = call.from_user.username or f"user_{user_id}"
        bot.send_message(call.message.chat.id, f"You're verified, @{username} 🎉")
        
        # Get group info including introduction message
        cursor.execute("SELECT id, title, group_invite_link, introduction_msg FROM groups WHERE group_invite_link IS NOT NULL LIMIT 1")
        group_data = cursor.fetchone()
        
        if group_data:
            group_id_for_link = group_data[0]
            group_title = group_data[1]
            group_invite = group_data[2]
            intro_msg = group_data[3]
            
            # Show custom introduction message if set
            if intro_msg:
                bot.send_message(call.message.chat.id, intro_msg)
            
            # Generate user referral link with group name
            group_name_clean = group_title.lower().replace(' ', '').replace('-', '')[:15]
            group_hash = hashlib.md5(str(group_id_for_link).encode()).hexdigest()[:6]
            ref_link = f"t.me/{bot.get_me().username}?start={username}_{group_name_clean}_{group_hash}"
        else:
            ref_link = f"t.me/{bot.get_me().username}?start={username}"
            group_invite = None
        
        cursor.execute("SELECT SUM(referred_count) FROM referrals WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        referred = result[0] if result and result[0] else 0
        
        # Build action buttons
        action_markup = InlineKeyboardMarkup(row_width=2)
        
        # Add Join Group button FIRST if available
        if group_invite:
            action_markup.add(InlineKeyboardButton("Join Group 👥", url=group_invite))
        
        # Add channel, bot, and Twitter buttons if set
        # Get buttons for the SPECIFIC group user joined from
        if group_data:
            cursor.execute("SELECT channel_link, bot_link, twitter_handle FROM groups WHERE id = ?", (group_id_for_link,))
            links = cursor.fetchone()
            if links:
                if links[0] and (not group_invite or links[0] != group_invite):
                    action_markup.add(InlineKeyboardButton("Join Channel 📢", url=links[0]))
                if links[1]:
                    action_markup.add(InlineKeyboardButton("Join Bot 🤖", url=links[1]))
                if links[2]:
                    action_markup.add(InlineKeyboardButton("Follow on X 🐦", url=links[2]))
        links = cursor.fetchone()
        if links:
            if links[0] and (not group_invite or links[0] != group_invite):
                action_markup.add(InlineKeyboardButton("Join Channel 📢", url=links[0]))
            if links[1]:
                action_markup.add(InlineKeyboardButton("Join Bot 🤖", url=links[1]))
            if links[2]:
                action_markup.add(InlineKeyboardButton("Follow on X 🐦", url=links[2]))
        
        action_markup.add(InlineKeyboardButton("Refresh 🔄", callback_data="refresh"))
        
        # Send referral message with buttons
        bot.send_message(call.message.chat.id, 
                        f"Here's your referral link to invite friends 🚀\n{ref_link}\nUsers referred: {referred}",
                        reply_markup=action_markup)
        
        # Send LumiFlash promotion
        promo_markup = InlineKeyboardMarkup(row_width=2)
        promo_markup.add(InlineKeyboardButton("Add Automator to Your Group", url=f"t.me/{bot.get_me().username}?startgroup=true"))
        promo_markup.add(InlineKeyboardButton("Use LumiFlash Bot", url="t.me/lumiflash_bot"))
        bot.send_message(call.message.chat.id, 
                        "Automator is your community AI manager 🤖\n\n"
                        "It verifies members, tracks engagement, and grows your project automatically.\n\n"
                        "Meet LumiFlash — your smart trading bot for Solana & EVM.",
                        reply_markup=promo_markup)
        
        if user_id in user_states:
            del user_states[user_id]
    else:
        bot.answer_callback_query(call.id, "Wrong! ❌", show_alert=False)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "That was incorrect. Here's a new question:")
        send_verification_challenge(call.message.chat.id, user_id)

# Handle refresh
@bot.callback_query_handler(func=lambda call: call.data == 'refresh')
def refresh(call):
    user_id = call.from_user.id
    username = call.from_user.username or f"user_{user_id}"
    
    # Get group info to build proper referral link
    target_group_id = user_states.get(user_id, {}).get('target_group_id')
    
    if target_group_id:
        cursor.execute("SELECT id, title, group_invite_link FROM groups WHERE id = ?", (target_group_id,))
    else:
        cursor.execute("SELECT id, title, group_invite_link FROM groups WHERE group_invite_link IS NOT NULL ORDER BY id ASC LIMIT 1")
    group_data = cursor.fetchone()
    
    if group_data:
        group_id_for_link = group_data[0]
        group_title = group_data[1]
        group_invite = group_data[2]
        
        # Generate user referral link with group name
        group_name_clean = group_title.lower().replace(' ', '').replace('-', '')[:15]
        group_hash = hashlib.md5(str(group_id_for_link).encode()).hexdigest()[:6]
        ref_link = f"t.me/{bot.get_me().username}?start={username}_{group_name_clean}_{group_hash}"
    else:
        ref_link = f"t.me/{bot.get_me().username}?start={username}"
        group_invite = None
    
    # Get total referrals across all groups for this user
    cursor.execute("SELECT SUM(referred_count) FROM referrals WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    referred = result[0] if result and result[0] else 0
    
    # Build action buttons - always show Join Group if group exists
    action_markup = InlineKeyboardMarkup(row_width=2)
    
    # Always add Join Group button if we have a group
    if group_invite:
        action_markup.add(InlineKeyboardButton("Join Group 👥", url=group_invite))
    
    # Only add channel and bot buttons if admin has set them
    if group_data:
        cursor.execute("SELECT channel_link, bot_link, twitter_handle FROM groups WHERE id = ?", (group_id_for_link,))
        links = cursor.fetchone()
        if links:
            if links[0] and links[0] != group_invite:
                action_markup.add(InlineKeyboardButton("Join Channel 📢", url=links[0]))
            if links[1]:
                action_markup.add(InlineKeyboardButton("Join Bot 🤖", url=links[1]))
            if links[2]:
                action_markup.add(InlineKeyboardButton("Follow on X 🐦", url=links[2]))
    
    action_markup.add(InlineKeyboardButton("Refresh 🔄", callback_data="refresh"))
    
    # Update the message in place (edit it)
    new_text = f"Here's your referral link to invite friends 🚀\n{ref_link}\nUsers referred: {referred}"
    
    try:
        bot.edit_message_text(new_text, call.message.chat.id, call.message.message_id, reply_markup=action_markup)
    except Exception as e:
        # If message hasn't changed, Telegram throws an error - ignore it
        pass
    
    # Show simple notification
    bot.answer_callback_query(call.id, "Refreshed! 🔄")

# Admin dashboard
@bot.message_handler(commands=['admin'])
def admin_dashboard(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    admin_groups = []
    
    # Check ALL groups the bot is in to see if user is admin
    cursor.execute("SELECT id FROM groups")
    for (group_id,) in cursor.fetchall():
        try:
            # Check if bot is still in the group
            bot.get_chat(group_id)
            
            # Check if user is admin in this group
            admins = bot.get_chat_administrators(group_id)
            is_admin = any(admin.user.id == user_id for admin in admins)
            
            if is_admin:
                # Update database with admin status
                cursor.execute("INSERT OR IGNORE INTO admins (group_id, user_id) VALUES (?, ?)", (group_id, user_id))
                conn.commit()
                admin_groups.append(group_id)
                
                # Try to get invite link if missing
                cursor.execute("SELECT group_invite_link FROM groups WHERE id = ?", (group_id,))
                result = cursor.fetchone()
                if not result or not result[0]:
                    try:
                        chat_member = bot.get_chat_member(group_id, bot.get_me().id)
                        if chat_member.status in ['administrator', 'creator']:
                            invite_link = bot.export_chat_invite_link(group_id)
                            cursor.execute("UPDATE groups SET group_invite_link = ? WHERE id = ?", (invite_link, group_id))
                            conn.commit()
                            print(f"✅ Got invite link for group {group_id}: {invite_link}")
                    except Exception as e:
                        print(f"⚠️ Could not get invite link for group {group_id}: {e}")
            else:
                # User is not admin anymore, remove from database
                cursor.execute("DELETE FROM admins WHERE group_id = ? AND user_id = ?", (group_id, user_id))
                conn.commit()
                
        except Exception as e:
            # Bot is no longer in group, remove from database
            print(f"⚠️ Bot not in group {group_id}, removing from database: {e}")
            cursor.execute("DELETE FROM groups WHERE id = ?", (group_id,))
            cursor.execute("DELETE FROM admins WHERE group_id = ?", (group_id,))
            conn.commit()
    
    if not admin_groups:
        bot.send_message(chat_id, "You are not an admin of any group. Add me to your group as admin first! 👑\n\nIf you've already added me to a group, please make me an admin there.")
        return
    
    markup = InlineKeyboardMarkup()
    for group_id in admin_groups:
        cursor.execute("SELECT title FROM groups WHERE id = ?", (group_id,))
        result = cursor.fetchone()
        title = result[0] if result else f"Group {group_id}"
        markup.add(InlineKeyboardButton(f"{title} 📊", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(chat_id, "Select a group to manage:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_group_'))
def admin_group_dashboard(call):
    group_id = int(call.data.split('_')[2])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    # Get group info
    cursor.execute("SELECT title, group_invite_link FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    group_title = result[0] if result else f"Group {group_id}"
    group_invite_link = result[1] if result and result[1] else None
    
    # Check if bot is admin in the group
    is_bot_admin = False
    try:
        chat_member = bot.get_chat_member(group_id, bot.get_me().id)
        is_bot_admin = chat_member.status in ['administrator', 'creator']
    except Exception as e:
        print(f"Error checking bot admin status: {e}")
    
    # If bot is not admin, show warning
    if not is_bot_admin:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Back 🔙", callback_data="back_to_main"))
        
        bot.send_message(call.message.chat.id, 
                        f"📊 Dashboard for {group_title}\n\n"
                        f"⚠️ Please promote me as an admin in this group first!\n\n"
                        f"I need admin rights to:\n"
                        f"• Export group invite links\n"
                        f"• Manage user verification\n"
                        f"• Track referrals and engagement\n\n"
                        f"After promoting me, try /admin again.",
                        reply_markup=markup)
        return
    
    # Only get link if we don't have one stored
    if not group_invite_link:
        try:
            new_invite_link = bot.export_chat_invite_link(group_id)
            cursor.execute("UPDATE groups SET group_invite_link = ? WHERE id = ?", (new_invite_link, group_id))
            conn.commit()
            group_invite_link = new_invite_link
            print(f"✅ Got invite link for group {group_id}")
        except Exception as e:
            print(f"Could not get invite link: {e}")
    
    # Generate group referral link
    group_name_clean = group_title.lower().replace(' ', '').replace('-', '')[:15]
    group_hash = hashlib.md5(str(group_id).encode()).hexdigest()[:6]
    group_ref_link = f"t.me/{bot.get_me().username}?start=invite_{group_name_clean}_{group_hash}"
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Analytics 📈", callback_data=f"analytics_{group_id}"))
    markup.add(InlineKeyboardButton("Settings ⚙️", callback_data=f"settings_{group_id}"))
    markup.add(InlineKeyboardButton("Anti-Spam 🛡️", callback_data=f"antispam_{group_id}"))
    markup.add(InlineKeyboardButton("Welcome/Goodbye ✉️", callback_data=f"messages_{group_id}"))
    markup.add(InlineKeyboardButton("Integrations 🔗", callback_data=f"integrations_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data="back_to_main"))
    
    bot.send_message(call.message.chat.id, 
                    f"📊 Dashboard for {group_title} 👑\n\n"
                    f"This is your referral link:\n{group_ref_link}", 
                    reply_markup=markup)
    
@bot.callback_query_handler(func=lambda call: call.data.startswith('refresh_link_'))
def refresh_group_link(call):
    group_id = int(call.data.split('_')[2])
    
    try:
        # Revoke old link and create new one
        new_invite_link = bot.export_chat_invite_link(group_id)
        cursor.execute("UPDATE groups SET group_invite_link = ? WHERE id = ?", (new_invite_link, group_id))
        conn.commit()
        
        bot.answer_callback_query(call.id, "✅ Group invite link refreshed!", show_alert=True)
        print(f"✅ Manually refreshed invite link for group {group_id}")
        
        # Refresh the dashboard to show updated info
        bot.delete_message(call.message.chat.id, call.message.message_id)
        fake_call = SimpleNamespace(
            data=f"admin_group_{group_id}",
            message=call.message,
            from_user=call.from_user
        )
        admin_group_dashboard(fake_call)
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)
        print(f"Error refreshing link: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('analytics_'))
def show_analytics(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    # Get top referrers with usernames
    cursor.execute("""
        SELECT r.user_id, r.referred_count, u.username 
        FROM referrals r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.group_id = ? 
        ORDER BY r.referred_count DESC 
        LIMIT 5
    """, (group_id,))
    referrals = cursor.fetchall()
    
    if referrals:
        ref_text = "🏆 Top Referrers:\n\n"
        for i, (user_id, count, username) in enumerate(referrals, 1):
            display_name = f"@{username}" if username else f"User {user_id}"
            ref_text += f"{i}. {display_name}: {count} referrals\n"
    else:
        ref_text = "🏆 Top Referrers:\n\nNo referrals yet"
    
    # Get top active members with usernames
    cursor.execute("""
        SELECT e.user_id, e.message_count, u.username 
        FROM engagement e
        LEFT JOIN users u ON e.user_id = u.id
        WHERE e.group_id = ? 
        ORDER BY e.message_count DESC 
        LIMIT 5
    """, (group_id,))
    eng = cursor.fetchall()
    
    if eng:
        eng_text = "\n💬 Top Active Members:\n\n"
        for i, (user_id, count, username) in enumerate(eng, 1):
            display_name = f"@{username}" if username else f"User {user_id}"
            eng_text += f"{i}. {display_name}: {count} messages\n"
    else:
        eng_text = "\n💬 Top Active Members:\n\nNo messages yet"
    
    # Get total stats
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE group_id = ?", (group_id,))
    total_referrers = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(referred_count) FROM referrals WHERE group_id = ?", (group_id,))
    total_referrals = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM engagement WHERE group_id = ?", (group_id,))
    total_members = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(message_count) FROM engagement WHERE group_id = ?", (group_id,))
    total_messages = cursor.fetchone()[0] or 0
    
    stats_text = f"\n📊 Overall Stats:\n\n"
    stats_text += f"Total referrals: {total_referrals}\n"
    stats_text += f"Active referrers: {total_referrers}\n"
    stats_text += f"Total members: {total_members}\n"
    stats_text += f"Total messages: {total_messages}"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, 
                    f"{ref_text}{eng_text}{stats_text}", 
                    reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('settings_'))
def settings_menu(call):
    group_id = int(call.data.split('_')[1])
    
    # DELETE the old message
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    cursor.execute("SELECT buy_alerts_enabled, raiding_enabled FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    buy = result[0] if result else 0
    raid = result[1] if result else 0
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton(f"Buy Alerts {'✅' if buy else '❌'}", callback_data=f"toggle_buy_{group_id}"))
    markup.add(InlineKeyboardButton(f"Raiding {'✅' if raid else '❌'}", callback_data=f"toggle_raid_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, "Settings:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_buy_'))
def toggle_buy(call):
    group_id = int(call.data.split('_')[2])
    cursor.execute("UPDATE groups SET buy_alerts_enabled = 1 - buy_alerts_enabled WHERE id = ?", (group_id,))
    conn.commit()
    
    # Get updated status
    cursor.execute("SELECT buy_alerts_enabled, raiding_enabled FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    buy = result[0] if result else 0
    raid = result[1] if result else 0
    
    # Edit message in place
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton(f"Buy Alerts {'✅' if buy else '❌'}", callback_data=f"toggle_buy_{group_id}"))
    markup.add(InlineKeyboardButton(f"Raiding {'✅' if raid else '❌'}", callback_data=f"toggle_raid_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id, "Buy alerts toggled! ✅")
    
    # Restart monitoring if needed
    start_monitoring_threads()

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_raid_'))
def toggle_raid(call):
    group_id = int(call.data.split('_')[2])
    cursor.execute("UPDATE groups SET raiding_enabled = 1 - raiding_enabled WHERE id = ?", (group_id,))
    conn.commit()
    
    # Get updated status
    cursor.execute("SELECT buy_alerts_enabled, raiding_enabled FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    buy = result[0] if result else 0
    raid = result[1] if result else 0
    
    # Edit message in place
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton(f"Buy Alerts {'✅' if buy else '❌'}", callback_data=f"toggle_buy_{group_id}"))
    markup.add(InlineKeyboardButton(f"Raiding {'✅' if raid else '❌'}", callback_data=f"toggle_raid_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id, "Raiding toggled! ✅")
    
    # Restart monitoring if needed
    start_monitoring_threads()



@bot.callback_query_handler(func=lambda call: call.data.startswith('antispam_'))
def antispam_menu(call):
    group_id = int(call.data.split('_')[1])
    
    # DELETE the old message instead of keeping it
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    cursor.execute("SELECT anti_spam_enabled FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    enabled = result[0] if result else 1
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"AI Moderation {'✅' if enabled else '❌'}", callback_data=f"toggle_spam_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, 
                    "🛡️ Anti-Spam & Moderation\n\n"
                    "✅ Hardcoded ban words (always active)\n"
                    "✅ Pattern-based detection (always active)\n"
                    "✅ AI-powered moderation (toggle below)\n\n"
                    "The bot uses a 3-layer system to catch:\n"
                    "• Profanity & slurs\n"
                    "• Hate speech & harassment\n"
                    "• Scams & spam\n"
                    "• Violent threats", 
                    reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_spam_'))
def toggle_spam(call):
    group_id = int(call.data.split('_')[2])
    cursor.execute("UPDATE groups SET anti_spam_enabled = 1 - anti_spam_enabled WHERE id = ?", (group_id,))
    conn.commit()
    
    # Get updated status
    cursor.execute("SELECT anti_spam_enabled FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    enabled = result[0] if result else 1
    
    # Edit message in place
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"AI Moderation {'✅' if enabled else '❌'}", callback_data=f"toggle_spam_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id, "AI moderation toggled! ✅")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_banned_'))
def set_banned(call):
    group_id = int(call.data.split('_')[2])
    # DON'T delete the menu - just send prompt below
    msg = bot.send_message(call.message.chat.id, "Enter banned words separated by commas (e.g., fuck,bitch)\n\nOr send '-' to clear banned words:")
    user_states[call.from_user.id] = {
        'state': 'waiting_banned', 
        'group_id': group_id, 
        'prompt_msg_id': msg.message_id,
        'menu_msg_id': call.message.message_id  # Store menu message ID
    }
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_banned')
def handle_banned_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    menu_msg_id = user_states[message.from_user.id]['menu_msg_id']
    banned = message.text.strip()
    
    if banned == '-':
        banned = None
    
    cursor.execute("UPDATE groups SET banned_words = ? WHERE id = ?", (banned, group_id))
    conn.commit()
    
    # Delete input and prompt
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    del user_states[message.from_user.id]
    
    # Update the EXISTING menu message
    cursor.execute("SELECT anti_spam_enabled, banned_words FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    enabled = result[0] if result else 1
    banned_words = result[1] if result and result[1] else '-'
    
    banned_display = (banned_words[:20] + '...') if len(banned_words) > 20 else banned_words
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"Anti-Spam {'✅' if enabled else '❌'}", callback_data=f"toggle_spam_{group_id}"))
    markup.add(InlineKeyboardButton(f"Banned Words: {banned_display}", callback_data=f"set_banned_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(message.chat.id, menu_msg_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('messages_'))
def messages_menu(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    cursor.execute("SELECT welcome_msg, introduction_msg FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    welcome = result[0] if result and result[0] else '-'
    introduction = result[1] if result and result[1] else '-'
    
    # Truncate for display
    welcome_display = (welcome[:20] + '...') if len(welcome) > 20 else welcome
    intro_display = (introduction[:20] + '...') if len(introduction) > 20 else introduction
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"Welcome Msg: {welcome_display}", callback_data=f"set_welcome_{group_id}"))
    markup.add(InlineKeyboardButton(f"Introduction: {intro_display}", callback_data=f"set_intro_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, 
                    "✉️ Message Settings:\n\n"
                    "**Welcome Message**: Shown when user joins the group\n"
                    "Default: 'Welcome {username}, you joined via {referrer} referral link'\n\n"
                    "**Introduction Message**: Shown after verification in DM\n"
                    "Default: Standard verification success message\n\n"
                    "Use '-' to reset to default",
                    reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_welcome_'))
def set_welcome(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, 
                          "Enter new welcome message:\n\n"
                          "Use {username} for member's name\n"
                          "Use {referrer} for referrer's name\n\n"
                          "Or send '-' to use default:\n"
                          "'Welcome {username}, you joined via {referrer} referral link'")
    user_states[call.from_user.id] = {
        'state': 'waiting_welcome', 
        'group_id': group_id, 
        'prompt_msg_id': msg.message_id,
        'menu_msg_id': call.message.message_id
    }
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_welcome')
def handle_welcome_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    menu_msg_id = user_states[message.from_user.id]['menu_msg_id']
    welcome = message.text.strip()
    
    if welcome == '-':
        welcome = None
    
    cursor.execute("UPDATE groups SET welcome_msg = ? WHERE id = ?", (welcome, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    del user_states[message.from_user.id]
    
    # Update menu
    cursor.execute("SELECT welcome_msg, introduction_msg FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    welcome = result[0] if result and result[0] else '-'
    introduction = result[1] if result and result[1] else '-'
    
    welcome_display = (welcome[:20] + '...') if len(welcome) > 20 else welcome
    intro_display = (introduction[:20] + '...') if len(introduction) > 20 else introduction
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"Welcome Msg: {welcome_display}", callback_data=f"set_welcome_{group_id}"))
    markup.add(InlineKeyboardButton(f"Introduction: {intro_display}", callback_data=f"set_intro_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(message.chat.id, menu_msg_id, reply_markup=markup)
# ============================================
# 🛡️ MODERATION SYSTEM - SMART 5-STRIKE SYSTEM
# ============================================

import re

# Track user strikes per group
user_strikes = {}  # {(group_id, user_id): strikes_remaining}
MAX_STRIKES = 5

# SEVERITY LEVELS
# LOW = Delete message only (no strike)
# MEDIUM = Delete + warning + 1 strike
# HIGH = Delete + warning + immediate kick + ban

# LAYER 1: Hardcoded Ban Words with Severity
BANNED_WORDS_LOW = {
    # Mild profanity - just delete, no strike (context-dependent)
    'hell', 'damn', 'crap', 'ass', 'wtf', 'omg'
}

# Remove BANNED_WORDS_LOW entirely - we don't need it
# Instead, merge everything into MEDIUM severity

BANNED_WORDS_MEDIUM = {
    # Profanity - delete + 1 strike (works in sentences too)
    'fuck', 'fucking', 'shit', 'bullshit', 'bastard', 'asshole', 
    'dick', 'dickhead', 'bitch', 'pussy', 'cunt', 'motherfucker', 'mf',
    'hell', 'wtf', 'stfu', 'ass',  # Added these
    
    # Scam keywords - delete + 1 strike
    'free crypto', 'airdrop claim', 'send 1 get 10', 'investment bot',
    'dm me privately', 'telegram me privately', 'double your money',
    'quick profit', 'free sol', 'claim reward','dm' 
}

BANNED_WORDS_HIGH = {
    # Severe slurs & hate speech - immediate ban
    'nigger', 'nigga', 'chink', 'kike', 'spic', 'wetback', 'faggot', 'fag',
    'tranny', 'retard', 'retarded', 'coon', 'beaner', 'raghead', 'sandnigger',
    
    # Death threats - immediate ban
    'kys', 'kill yourself', 'go die', 'i will kill you', 'i will murder you',
    "i'll stab you", "i'll hurt you", 'burn you alive', 'i hope you die'
}

# LAYER 2: Regex Patterns with Severity
HATE_PATTERNS_MEDIUM = [
    r'\b(you|ur|u)\s+(are|r)\s+a\s+(idiot|moron|loser|clown)',
    r'\b(shut up|fuck off|stfu)\b',
    r'\byou\'?re so (dumb|stupid|useless)',
]

HATE_PATTERNS_HIGH = [
    r'\byou people are\s+\w+',
    r'\bgo back to (your )?country',
    r'\b(black|white|asian|arab|mexican|indian)\s+(dog|ape|pig|trash|monkey)',
    r'\ball (men|women|gays|trans) are\s+\w+',
    r'\b(kill|hurt|stab|shoot|murder)\s+(you|yourself|him|her)',
]

SCAM_PATTERNS = [
    r'\b(free|claim).{0,20}airdrop',
    r'\bsend\s+\d+.{0,10}get\s+\d+',
    r'\bdouble.{0,10}money',
    r'\b(whatsapp|dm|telegram)\s+me',
    r'\bhttps?://\S+\.(ru|xyz|top|tk)\b',
]

def get_user_strikes(group_id, user_id):
    """Get remaining strikes for user"""
    key = (group_id, user_id)
    if key not in user_strikes:
        user_strikes[key] = MAX_STRIKES
    return user_strikes[key]

def deduct_strike(group_id, user_id):
    """Deduct one strike, return remaining"""
    key = (group_id, user_id)
    if key not in user_strikes:
        user_strikes[key] = MAX_STRIKES
    user_strikes[key] -= 1
    return user_strikes[key]

def check_message_moderation(text, group_id, user_id):
    """
    Returns: (severity, reason, use_ai)
    severity: 'SAFE', 'LOW', 'MEDIUM', 'HIGH'
    """
    text_lower = text.lower()
    
    # Check HIGH severity (immediate ban)
    for word in BANNED_WORDS_HIGH:
        # Use word boundaries to avoid false positives
        if len(word.split()) > 1:  # Multi-word phrase
            if word in text_lower:
                return 'HIGH', f"Severe violation: {word}", False
        else:  # Single word - check boundaries
            import re
            if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
                return 'HIGH', f"Severe violation: {word}", False
    
    # Check MEDIUM severity (delete + strike)
    for word in BANNED_WORDS_MEDIUM:
        if len(word.split()) > 1:  # Multi-word phrase
            if word in text_lower:
                return 'MEDIUM', f"Banned word: {word}", False
        else:  # Single word - check boundaries
            import re
            if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
                return 'MEDIUM', f"Banned word: {word}", False
    
    # Check LOW severity (delete only, no strike)
    # Check LOW severity (delete only, no strike)
    for word in BANNED_WORDS_LOW:
        # Check context - if used positively, allow it
        positive_context = any(phrase in text_lower for phrase in ['hell yeah', 'damn good', 'damn right'])
        if positive_context:
            return 'SAFE', "Context is positive", False
        return 'LOW', f"Mild profanity: {word}", False
    
    # Escalate to AI for ambiguous cases
    if should_send_to_ai(text):
        return 'AI', "Escalating to AI", True
    
    return 'SAFE', "Clean message", False

def should_send_to_ai(text):
    """Behavioral triggers for AI escalation"""
    if len(text) < 10:
        return False
    
    if text.isupper() and len(text) > 20:
        return True
    
    emoji_count = sum(1 for char in text if ord(char) > 127000)
    if emoji_count > 6:
        return True
    
    identity_words = ['black', 'white', 'asian', 'arab', 'mexican', 'gay', 'trans', 'women', 'men']
    if any(word in text.lower() for word in identity_words):
        return True
    
    if 'http' in text.lower() and not any(domain in text.lower() for domain in ['twitter.com', 't.me', 'youtube.com']):
        return True
    
    return False

# AI rate limiting
ai_check_count = {}

def can_use_ai(user_id):
    """Max 3 AI checks per 10 minutes"""
    now = time.time()
    if user_id not in ai_check_count:
        ai_check_count[user_id] = []
    
    ai_check_count[user_id] = [t for t in ai_check_count[user_id] if now - t < 600]
    
    if len(ai_check_count[user_id]) >= 3:
        return False
    
    ai_check_count[user_id].append(now)
    return True


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_intro_'))
def set_intro(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, 
                          "Enter introduction message (shown after verification):\n\n"
                          "Example: 'This is $BMC group for raiding and hunting tokens.'\n\n"
                          "Or send '-' to use default message:")
    user_states[call.from_user.id] = {
        'state': 'waiting_intro', 
        'group_id': group_id, 
        'prompt_msg_id': msg.message_id,
        'menu_msg_id': call.message.message_id
    }
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_intro')
def handle_intro_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    menu_msg_id = user_states[message.from_user.id]['menu_msg_id']
    intro = message.text.strip()
    
    if intro == '-':
        intro = None
    
    cursor.execute("UPDATE groups SET introduction_msg = ? WHERE id = ?", (intro, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    del user_states[message.from_user.id]
    
    # Update menu
    cursor.execute("SELECT welcome_msg, introduction_msg FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    welcome = result[0] if result and result[0] else '-'
    introduction = result[1] if result and result[1] else '-'
    
    welcome_display = (welcome[:20] + '...') if len(welcome) > 20 else welcome
    intro_display = (introduction[:20] + '...') if len(introduction) > 20 else introduction
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"Welcome Msg: {welcome_display}", callback_data=f"set_welcome_{group_id}"))
    markup.add(InlineKeyboardButton(f"Introduction: {intro_display}", callback_data=f"set_intro_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(message.chat.id, menu_msg_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('integrations_'))
def integrations_menu(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    cursor.execute("SELECT channel_link, bot_link, twitter_handle FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    channel = result[0] if result and result[0] else '-'
    bot_link = result[1] if result and result[1] else '-'
    twitter = result[2] if result and result[2] else '-'
    
    # Truncate for display
    channel_display = (channel[:15] + '...') if len(channel) > 15 else channel
    bot_display = (bot_link[:15] + '...') if len(bot_link) > 15 else bot_link
    twitter_display = (twitter[:15] + '...') if len(twitter) > 15 else twitter
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"📢 Channel: {channel_display}", callback_data=f"set_channel_{group_id}"))
    markup.add(InlineKeyboardButton(f"🤖 Bot: {bot_display}", callback_data=f"set_botlink_{group_id}"))
    markup.add(InlineKeyboardButton(f"🐦 Twitter: {twitter_display}", callback_data=f"set_twitter_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, "Integrations Settings:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_channel_'))
def set_channel(call):
    group_id = int(call.data.split('_')[2])
    # DON'T delete menu - just send prompt as separate message
    msg = bot.send_message(call.message.chat.id, "Enter channel link (e.g., t.me/channel):\n\nOr send '-' to clear:")
    user_states[call.from_user.id] = {
        'state': 'waiting_channel', 
        'group_id': group_id, 
        'prompt_msg_id': msg.message_id,
        'menu_msg_id': call.message.message_id
    }
    bot.answer_callback_query(call.id)
    
@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_channel')
def handle_channel_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    menu_msg_id = user_states[message.from_user.id]['menu_msg_id']
    link = message.text.strip()
    
    if link == '-':
        link = None
    
    cursor.execute("UPDATE groups SET channel_link = ? WHERE id = ?", (link, group_id))
    conn.commit()
    
    # Delete input and prompt
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    del user_states[message.from_user.id]
    
    # Update the existing menu message
    cursor.execute("SELECT channel_link, bot_link, twitter_handle FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    channel = result[0] if result and result[0] else '-'
    bot_link = result[1] if result and result[1] else '-'
    twitter = result[2] if result and result[2] else '-'
    
    channel_display = (channel[:15] + '...') if len(channel) > 15 else channel
    bot_display = (bot_link[:15] + '...') if len(bot_link) > 15 else bot_link
    twitter_display = (twitter[:15] + '...') if len(twitter) > 15 else twitter
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"Channel: {channel_display}", callback_data=f"set_channel_{group_id}"))
    markup.add(InlineKeyboardButton(f"Bot Link: {bot_display}", callback_data=f"set_botlink_{group_id}"))
    markup.add(InlineKeyboardButton(f"Twitter: {twitter_display}", callback_data=f"set_twitter_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(message.chat.id, menu_msg_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_botlink_'))
def set_botlink(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter bot link (e.g., t.me/otherbot):\n\nOr send '-' to clear:")
    user_states[call.from_user.id] = {
        'state': 'waiting_botlink', 
        'group_id': group_id, 
        'prompt_msg_id': msg.message_id,
        'menu_msg_id': call.message.message_id
    }
    bot.answer_callback_query(call.id)
    
@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_botlink')
def handle_botlink_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    menu_msg_id = user_states[message.from_user.id]['menu_msg_id']
    link = message.text.strip()
    
    if link == '-':
        link = None
    
    cursor.execute("UPDATE groups SET bot_link = ? WHERE id = ?", (link, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    del user_states[message.from_user.id]
    
    cursor.execute("SELECT channel_link, bot_link, twitter_handle FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    channel = result[0] if result and result[0] else '-'
    bot_link = result[1] if result and result[1] else '-'
    twitter = result[2] if result and result[2] else '-'
    
    channel_display = (channel[:15] + '...') if len(channel) > 15 else channel
    bot_display = (bot_link[:15] + '...') if len(bot_link) > 15 else bot_link
    twitter_display = (twitter[:15] + '...') if len(twitter) > 15 else twitter
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"Channel: {channel_display}", callback_data=f"set_channel_{group_id}"))
    markup.add(InlineKeyboardButton(f"Bot Link: {bot_display}", callback_data=f"set_botlink_{group_id}"))
    markup.add(InlineKeyboardButton(f"Twitter: {twitter_display}", callback_data=f"set_twitter_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(message.chat.id, menu_msg_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_twitter_'))
def set_twitter(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter Twitter handle (without @):\n\nOr send '-' to clear:")
    user_states[call.from_user.id] = {
        'state': 'waiting_twitter', 
        'group_id': group_id, 
        'prompt_msg_id': msg.message_id,
        'menu_msg_id': call.message.message_id
    }
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_twitter')
def handle_twitter_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    menu_msg_id = user_states[message.from_user.id]['menu_msg_id']
    handle = message.text.strip()
    
    if handle == '-':
        handle = None
    elif handle and not handle.startswith('http'):
        # Auto-add https://x.com/ if user only enters username
        if handle.startswith('@'):
            handle = handle[1:]  # Remove @ if present
        handle = f"https://x.com/{handle}"
    
    cursor.execute("UPDATE groups SET twitter_handle = ? WHERE id = ?", (handle, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    del user_states[message.from_user.id]
    
    cursor.execute("SELECT channel_link, bot_link, twitter_handle FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    channel = result[0] if result and result[0] else '-'
    bot_link = result[1] if result and result[1] else '-'
    twitter = result[2] if result and result[2] else '-'
    
    channel_display = (channel[:15] + '...') if len(channel) > 15 else channel
    bot_display = (bot_link[:15] + '...') if len(bot_link) > 15 else bot_link
    twitter_display = (twitter[:15] + '...') if len(twitter) > 15 else twitter
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"📢 Channel: {channel_display}", callback_data=f"set_channel_{group_id}"))
    markup.add(InlineKeyboardButton(f"🤖 Bot: {bot_display}", callback_data=f"set_botlink_{group_id}"))
    markup.add(InlineKeyboardButton(f"🐦 Twitter: {twitter_display}", callback_data=f"set_twitter_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.edit_message_reply_markup(message.chat.id, menu_msg_id, reply_markup=markup)
    
    start_monitoring_threads()

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_main')
def back_to_main(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Find groups where user is admin from DB
    cursor.execute("SELECT group_id FROM admins WHERE user_id = ?", (user_id,))
    admin_groups = []
    
    for (group_id,) in cursor.fetchall():
        try:
            # Check if bot is still in the group
            bot.get_chat(group_id)
            # Check if user is still admin
            admins = bot.get_chat_administrators(group_id)
            is_admin = any(admin.user.id == user_id for admin in admins)
            if is_admin:
                admin_groups.append(group_id)
            else:
                # User is no longer admin, remove from DB
                cursor.execute("DELETE FROM admins WHERE group_id = ? AND user_id = ?", (group_id, user_id))
                conn.commit()
        except Exception as e:
            # Bot is no longer in group, remove from DB
            cursor.execute("DELETE FROM groups WHERE id = ?", (group_id,))
            cursor.execute("DELETE FROM admins WHERE group_id = ?", (group_id,))
            conn.commit()
    
    if not admin_groups:
        # Check if there are any groups bot is in where user is admin
        cursor.execute("SELECT id FROM groups")
        for (group_id,) in cursor.fetchall():
            try:
                admins = bot.get_chat_administrators(group_id)
                is_admin = any(admin.user.id == user_id for admin in admins)
                if is_admin:
                    cursor.execute("INSERT OR IGNORE INTO admins (group_id, user_id) VALUES (?, ?)", (group_id, user_id))
                    conn.commit()
                    admin_groups.append(group_id)
            except:
                pass
        
        if not admin_groups:
            bot.send_message(chat_id, "You are not an admin of any group. Add me to your group as admin first! 👑\n\nIf you've already added me to a group, please make me an admin there.")
            return
    
    markup = InlineKeyboardMarkup()
    for group_id in admin_groups:
        cursor.execute("SELECT title FROM groups WHERE id = ?", (group_id,))
        result = cursor.fetchone()
        title = result[0] if result else f"Group {group_id}"
        markup.add(InlineKeyboardButton(f"{title} 📊", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(chat_id, "Select a group to manage:", reply_markup=markup)

@bot.message_handler(content_types=['migrate_to_chat_id'])
def handle_group_migration(message):
    """Handle when group is upgraded to supergroup"""
    old_group_id = message.chat.id
    new_group_id = message.migrate_to_chat_id
    
    print(f"🔄 Group migrated: {old_group_id} → {new_group_id}")
    
    try:
        # Get old group data
        cursor.execute("SELECT * FROM groups WHERE id = ?", (old_group_id,))
        old_data = cursor.fetchone()
        
        if old_data:
            # Copy to new ID
            cursor.execute("""
                INSERT OR REPLACE INTO groups 
                (id, title, welcome_msg, introduction_msg, banned_words, anti_spam_enabled, 
                 buy_alerts_enabled, raiding_enabled, twitter_handle, channel_link, bot_link, 
                 token_address, token_chain, group_invite_link)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_group_id, old_data[1], old_data[2], old_data[3], old_data[4], 
                  old_data[5], old_data[6], old_data[7], old_data[8], old_data[9], 
                  old_data[10], old_data[11], old_data[12], old_data[13]))
            
            # Migrate admins
            cursor.execute("SELECT user_id FROM admins WHERE group_id = ?", (old_group_id,))
            for (user_id,) in cursor.fetchall():
                cursor.execute("INSERT OR IGNORE INTO admins (group_id, user_id) VALUES (?, ?)", 
                              (new_group_id, user_id))
            
            # Migrate referrals
            cursor.execute("UPDATE referrals SET group_id = ? WHERE group_id = ?", 
                          (new_group_id, old_group_id))
            
            # Migrate engagement
            cursor.execute("UPDATE engagement SET group_id = ? WHERE group_id = ?", 
                          (new_group_id, old_group_id))
            
            # Delete old group
            cursor.execute("DELETE FROM groups WHERE id = ?", (old_group_id,))
            cursor.execute("DELETE FROM admins WHERE group_id = ?", (old_group_id))
            
            conn.commit()
            
            # Try to get new invite link
            try:
                new_invite_link = bot.export_chat_invite_link(new_group_id)
                cursor.execute("UPDATE groups SET group_invite_link = ? WHERE id = ?", 
                              (new_invite_link, new_group_id))
                conn.commit()
                print(f"✅ Migrated group data and got new invite link")
            except:
                print(f"⚠️ Migrated data but couldn't get invite link yet")
                
    except Exception as e:
        print(f"❌ Error migrating group: {e}")

# Group events
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_member(message):
    group_id = message.chat.id
    bot_id = bot.get_me().id
    
    for member in message.new_chat_members:
        if member.id == bot_id:
            # Bot was added to group
            print(f"🤖 Bot added to group {group_id} - {message.chat.title}")
            
            # Store basic group info (without invite link)
            try:
                cursor.execute("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", 
                              (group_id, message.chat.title))
                cursor.execute("UPDATE groups SET title = ? WHERE id = ?", 
                              (message.chat.title, group_id))
                
                # Store all admins
                admins = bot.get_chat_administrators(group_id)
                for admin in admins:
                    cursor.execute("INSERT OR IGNORE INTO admins (group_id, user_id) VALUES (?, ?)", 
                                  (group_id, admin.user.id))
                
                conn.commit()
                print(f"✅ Stored group info: {group_id} - {message.chat.title}")
            except Exception as e:
                print(f"❌ Error storing group info: {e}")
                conn.rollback()
            
            # Check if bot is already admin
            try:
                chat_member = bot.get_chat_member(group_id, bot_id)
                is_admin = chat_member.status in ['administrator', 'creator']
                print(f"Bot admin status: {is_admin}")
            except:
                is_admin = False
            
            # Send appropriate message
            try:
                if is_admin:
                    # Bot is already admin, try to get invite link
                    try:
                        invite_link = bot.export_chat_invite_link(group_id)
                        cursor.execute("UPDATE groups SET group_invite_link = ? WHERE id = ?", 
                                      (invite_link, group_id))
                        conn.commit()
                        print(f"✅ Got invite link: {invite_link}")
                    except Exception as e:
                        print(f"⚠️ Could not get invite link yet: {e}")
                    
                    bot.send_message(group_id, 
                                    "Thanks for adding me! Admins can manage me via /admin in private chat. 👑")
                else:
                    # Bot is NOT admin yet
                    bot.send_message(group_id, 
                                    "Thanks for adding me! Please promote me to admin first, "
                                    "then admins can manage me via /admin in private chat. 👑")
                
                print(f"✅ Welcome message sent to group {group_id}")
            except Exception as e:
                print(f"❌ Error sending welcome message: {e}")
            
            # Skip to next member
            continue
        
        # Process actual user members (not the bot)
        user_id = member.id
        username = member.username or f"user_{user_id}"
        
        cursor.execute("SELECT verified, referrer_id, referrer_username FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            # User is verified
            if result[1]:  # Has a referrer
                referrer_id = result[1]
                referrer_username = result[2] or "someone"
                
                # Update referral count
                cursor.execute("""
                    INSERT INTO referrals (group_id, user_id, referred_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(group_id, user_id) DO UPDATE SET referred_count = referred_count + 1
                """, (group_id, referrer_id))
                conn.commit()
                
                # Send custom welcome or default
                cursor.execute("SELECT welcome_msg FROM groups WHERE id = ?", (group_id,))
                custom_result = cursor.fetchone()
                
                if custom_result and custom_result[0]:
                    # Use custom message
                    welcome_text = custom_result[0].format(username=username, referrer=referrer_username)
                else:
                    # Use default message
                    welcome_text = f"Welcome @{username}, you joined via @{referrer_username} referral link! 🎉"
                
                bot.send_message(group_id, welcome_text)
            else:
                # No referrer, just welcome
                cursor.execute("SELECT welcome_msg FROM groups WHERE id = ?", (group_id,))
                welcome_result = cursor.fetchone()
                if welcome_result and welcome_result[0]:
                    msg = welcome_result[0].format(username=username, referrer="direct")
                else:
                    msg = f"Welcome @{username}! 🎉"
                bot.send_message(group_id, msg)

@bot.message_handler(content_types=['my_chat_member'])
def handle_bot_status_change(message):
    """Detect when bot is promoted to admin"""
    try:
        group_id = message.chat.id
        new_status = message.new_chat_member.status
        old_status = message.old_chat_member.status
        
        print(f"📊 Bot status changed in group {group_id}: {old_status} → {new_status}")
        
        # Bot was promoted to admin
        if new_status in ['administrator', 'creator'] and old_status not in ['administrator', 'creator']:
            print(f"✅ Bot promoted to admin in group {group_id}")
            
            # Check if we already have a link stored
            cursor.execute("SELECT group_invite_link FROM groups WHERE id = ?", (group_id,))
            result = cursor.fetchone()
            existing_link = result[0] if result and result[0] else None
            
            # Only create new link if we don't have one
            if not existing_link:
                try:
                    invite_link = bot.export_chat_invite_link(group_id)
                    cursor.execute("UPDATE groups SET group_invite_link = ? WHERE id = ?", (invite_link, group_id))
                    conn.commit()
                    print(f"✅ Successfully got invite link: {invite_link}")
                    
                    bot.send_message(group_id, "Thanks for promoting me to admin! Admins can now manage me via /admin in private chat. 👑")
                except Exception as e:
                    print(f"❌ Could not get invite link: {e}")
            else:
                print(f"✅ Already have invite link stored: {existing_link}")
                bot.send_message(group_id, "Thanks for promoting me to admin! Admins can now manage me via /admin in private chat. 👑")
        
        # Bot was demoted from admin
        elif old_status in ['administrator', 'creator'] and new_status not in ['administrator', 'creator']:
            print(f"⚠️ Bot demoted from admin in group {group_id}")
            cursor.execute("UPDATE groups SET group_invite_link = NULL WHERE id = ?", (group_id,))
            conn.commit()
            
    except Exception as e:
        print(f"Error handling bot status change: {e}")

def check_pending():
    while True:
        now = time.time()
        to_kick = []
        for user_id, data in list(pending_verifications.items()):
            if now - data['time'] > 300:  # 5 minutes
                try:
                    bot.ban_chat_member(data['group_id'], user_id)
                    bot.unban_chat_member(data['group_id'], user_id)  # Unban so they can rejoin after verification
                except:
                    pass
                to_kick.append(user_id)
        for u in to_kick:
            del pending_verifications[u]
        time.sleep(60)

threading.Thread(target=check_pending, daemon=True).start()

@bot.message_handler(content_types=['left_chat_member'])
def handle_left_member(message):
    # Don't send goodbye if the bot itself was removed
    if message.left_chat_member.id == bot.get_me().id:
        return
    
    try:
        cursor.execute("SELECT goodbye_msg FROM groups WHERE id = ?", (message.chat.id,))
        result = cursor.fetchone()
        msg = result[0] if result and result[0] else "Goodbye, {username}! 👋"
        username = message.left_chat_member.username or "user"
        bot.send_message(message.chat.id, msg.format(username=username))
    except Exception as e:
        print(f"Error sending goodbye message: {e}")

# Message handler for engagement and anti-spam
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text)
def handle_group_message(message):
    group_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    cursor.execute("SELECT anti_spam_enabled FROM groups WHERE id = ?", (group_id,))
    result = cursor.fetchone()
    
    if not result:
        return
    
    ai_enabled = result[0]
    
    # Check moderation
    severity, reason, use_ai = check_message_moderation(message.text, group_id, user_id)
    
    # Handle HIGH severity - immediate ban
    if severity == 'HIGH':
        try:
            bot.delete_message(group_id, message.message_id)
            bot.ban_chat_member(group_id, user_id)
            
            try:
                bot.send_message(user_id, 
                    f"🚫 You have been permanently banned from the group for: {reason}\n"
                    f"Severe violations result in immediate removal.")
            except:
                pass
            
            print(f"🚫 BANNED user {user_id} for: {reason}")
            return
        except Exception as e:
            print(f"Error banning user: {e}")
            return
    
    # Handle MEDIUM severity - delete + strike
    if severity == 'MEDIUM':
        try:
            bot.delete_message(group_id, message.message_id)
            
            strikes_left = deduct_strike(group_id, user_id)
            
            if strikes_left <= 0:
                # Out of strikes - kick user
                bot.ban_chat_member(group_id, user_id)
                bot.unban_chat_member(group_id, user_id)
                
                # Send notice in group
                bot.send_message(group_id, 
                    f"⚠️ @{username} has been removed after {MAX_STRIKES} violations.")
                
                print(f"⚠️ KICKED user {user_id} - exhausted all strikes")
            else:
                # Still has strikes left - warn in GROUP
                bot.send_message(group_id, 
                    f"⚠️ @{username}, your message was deleted for: {reason}\n"
                    f"Strikes remaining: {strikes_left}/{MAX_STRIKES}")
                
                print(f"⚠️ User {user_id} - {strikes_left} strikes left")
            
            return
        except Exception as e:
            print(f"Error in moderation: {e}")
            return
    
    # Handle LOW severity - delete only (no strike)
    if severity == 'LOW':
        try:
            bot.delete_message(group_id, message.message_id)
            print(f"ℹ️ Deleted low-severity message from user {user_id}: {reason}")
            return
        except Exception as e:
            print(f"Error deleting message: {e}")
            return
    
    # Handle AI escalation
    if severity == 'AI' and ai_enabled and can_use_ai(user_id):
        if check_message_with_ai(message.text):
            try:
                bot.delete_message(group_id, message.message_id)
                
                strikes_left = deduct_strike(group_id, user_id)
                
                if strikes_left <= 0:
                    # Out of strikes - kick
                    bot.ban_chat_member(group_id, user_id)
                    bot.unban_chat_member(group_id, user_id)
                    
                    # Warn in GROUP
                    bot.send_message(group_id, 
                        f"⚠️ @{username} has been removed after {MAX_STRIKES} AI-flagged violations.")
                else:
                    # Still has strikes - warn in GROUP
                    bot.send_message(group_id, 
                        f"⚠️ @{username}, AI flagged your message as inappropriate.\n"
                        f"Strikes remaining: {strikes_left}/{MAX_STRIKES}")
                
                print(f"🤖 AI moderation - user {user_id} - {strikes_left} strikes left")
                return
            except Exception as e:
                print(f"Error in AI moderation: {e}")
                
                print(f"🤖 AI moderation - user {user_id} - {strikes_left} strikes left")
                return
            except Exception as e:
                print(f"Error in AI moderation: {e}")
    
    # Message is SAFE - track engagement
    cursor.execute("""
        INSERT INTO engagement (group_id, user_id, message_count)
        VALUES (?, ?, 1)
        ON CONFLICT(group_id, user_id) DO UPDATE SET message_count = message_count + 1
    """, (group_id, user_id))
    conn.commit()

print("Bot is running...")
bot.infinity_polling()
