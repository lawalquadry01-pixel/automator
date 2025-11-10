import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import random
import sqlite3
import time
import threading
import requests  # For potential integrations like Twitter polling

# Replace with your bot token
TOKEN = '8545496074:AAEk36BhoJC2X6Beue2YaqSA-3nEdhDrvSk'

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

# Create tables
cursor.execute('''
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    title TEXT,
    welcome_msg TEXT,
    goodbye_msg TEXT,
    banned_words TEXT,
    anti_spam_enabled INTEGER DEFAULT 1,
    buy_alerts_enabled INTEGER DEFAULT 0,
    raiding_enabled INTEGER DEFAULT 0,
    twitter_handle TEXT,
    channel_link TEXT,
    bot_link TEXT
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
    message_count INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS admins (
    group_id INTEGER,
    user_id INTEGER
)
''')

conn.commit()

# User states for stateful flows
user_states = {}

# Verification pending users in groups (for anti-spam kick)
pending_verifications = {}

# Function to generate random verification challenge
def generate_challenge():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    correct = a + b
    options = [correct, correct - 1, correct + 1, correct + 2]
    random.shuffle(options)
    return a, b, correct, options

# Polling thread for raiding (Twitter/X posts)
def poll_twitter(group_id, twitter_handle):
    last_tweet_id = None
    while True:
        try:
            # Note: In real use, use Twitter API v2 with bearer token. Here, placeholder with requests.
            # Replace with actual API call. This is simplified.
            response = requests.get(f"https://api.twitter.com/2/users/by/username/{twitter_handle}/tweets", headers={"Authorization": "Bearer YOUR_TWITTER_BEARER_TOKEN"})
            if response.status_code == 200:
                tweets = response.json()['data']
                if tweets and tweets[0]['id'] != last_tweet_id:
                    last_tweet_id = tweets[0]['id']
                    tweet_url = f"https://twitter.com/{twitter_handle}/status/{last_tweet_id}"
                    bot.send_message(group_id, f"🚨 New tweet from @{twitter_handle}! Raid it: {tweet_url}\nLike, comment, retweet! 💥")
        except Exception as e:
            print(f"Twitter polling error: {e}")
        time.sleep(300)  # Poll every 5 minutes

# Start polling for groups with raiding enabled
def start_raiding_polls():
    cursor.execute("SELECT id, twitter_handle FROM groups WHERE raiding_enabled = 1")
    for group_id, twitter_handle in cursor.fetchall():
        if twitter_handle:
            threading.Thread(target=poll_twitter, args=(group_id, twitter_handle), daemon=True).start()

# Handle bot start for users
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    # Insert or update user
    cursor.execute("INSERT OR REPLACE INTO users (id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    
    # Check if already verified
    cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
    verified = cursor.fetchone()[0]
    
    if verified:
        # Already verified, show referral info
        ref_link = f"t.me/{bot.get_me().username}?start={username}"
        cursor.execute("SELECT referred_count FROM referrals WHERE user_id = ? AND group_id = 0", (user_id,))
        result = cursor.fetchone()
        referred = result[0] if result else 0
        bot.send_message(message.chat.id, f"You're already verified! 🎉\nHere’s your referral link: {ref_link}\nUsers referred: {referred}")
        
        # Action buttons
        action_markup = InlineKeyboardMarkup(row_width=2)
        cursor.execute("SELECT channel_link, bot_link FROM groups LIMIT 1")
        links = cursor.fetchone()
        action_markup.add(InlineKeyboardButton("Join Group 👥", url="t.me/yourgroup"))
        if links and links[0]:
            action_markup.add(InlineKeyboardButton("Join Channel 📢", url=links[0]))
        if links and links[1]:
            action_markup.add(InlineKeyboardButton("Join Bot 🤖", url=links[1]))
        action_markup.add(InlineKeyboardButton("Refresh 🔄", callback_data="refresh"))
        bot.send_message(message.chat.id, "Quick actions:", reply_markup=action_markup)
        return
    
    # New user: Check for referrer
    referrer_id = None
    referrer_username = None
    if len(message.text.split()) > 1:
        referrer_username = message.text.split()[1]
        cursor.execute("SELECT id FROM users WHERE username = ?", (referrer_username,))
        referrer = cursor.fetchone()
        if referrer:
            referrer_id = referrer[0]
            cursor.execute("UPDATE users SET referrer_id = ?, referrer_username = ? WHERE id = ?", (referrer_id, referrer_username, user_id))
            conn.commit()
    
    # Send welcome and verify
    bot.send_message(message.chat.id, "Welcome to the MemeCoin Community Bot! 🎉\nPlease verify to get started.")
    send_verification_challenge(message.chat.id, user_id)

def send_verification_challenge(chat_id, user_id):
    a, b, correct, options = generate_challenge()
    markup = InlineKeyboardMarkup(row_width=2)
    for opt in options:
        markup.add(InlineKeyboardButton(f"{opt}", callback_data=f"verif_{a}_{b}_{opt}_{user_id}"))
    
    verif_msg = bot.send_message(chat_id, f"What’s {a} + {b}? 🤔", reply_markup=markup)
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
        bot.send_message(call.message.chat.id, f"You’re verified, @{username} 🎉")
        
        # Send referral link and stats
        ref_link = f"t.me/{bot.get_me().username}?start={username}"
        cursor.execute("SELECT referred_count FROM referrals WHERE user_id = ? AND group_id = 0", (user_id,))
        result = cursor.fetchone()
        referred = result[0] if result else 0
        bot.send_message(call.message.chat.id, f"Here’s your referral link to invite friends 🚀\n{ref_link}\nUsers referred: {referred}")
        
        # Send action buttons
        action_markup = InlineKeyboardMarkup(row_width=2)
        cursor.execute("SELECT channel_link, bot_link FROM groups LIMIT 1")
        links = cursor.fetchone()
        action_markup.add(InlineKeyboardButton("Join Group 👥", url="t.me/yourgroup"))
        if links and links[0]:
            action_markup.add(InlineKeyboardButton("Join Channel 📢", url=links[0]))
        if links and links[1]:
            action_markup.add(InlineKeyboardButton("Join Bot 🤖", url=links[1]))
        action_markup.add(InlineKeyboardButton("Refresh 🔄", callback_data="refresh"))
        bot.send_message(call.message.chat.id, "Quick actions:", reply_markup=action_markup)
        
        del user_states[user_id]
    else:
        bot.answer_callback_query(call.id, "Wrong! Try again. ❌", show_alert=True)
        send_verification_challenge(call.message.chat.id, user_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)

# Handle refresh
@bot.callback_query_handler(func=lambda call: call.data == 'refresh')
def refresh(call):
    user_id = call.from_user.id
    cursor.execute("SELECT referred_count FROM referrals WHERE user_id = ? AND group_id = 0", (user_id,))
    result = cursor.fetchone()
    referred = result[0] if result else 0
    new_text = f"Here’s your referral link to invite friends 🚀\n{call.message.text.split('\n')[0]}\nUsers referred: {referred}"
    try:
        bot.edit_message_text(new_text, call.message.chat.id, call.message.message_id - 1)  # Edit the referral message (assuming it's previous)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise
    bot.answer_callback_query(call.id, "Refreshed! 🔄")

# Admin dashboard
@bot.message_handler(commands=['admin'])
def admin_dashboard(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Find groups where user is admin from DB
    cursor.execute("SELECT group_id FROM admins WHERE user_id = ?", (user_id,))
    admin_groups = [g[0] for g in cursor.fetchall()]
    
    if not admin_groups:
        cursor.execute("SELECT id FROM groups")
        for group_id in [g[0] for g in cursor.fetchall()]:
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
            bot.send_message(chat_id, "You are not an admin of any group. Add me to your group as admin first! 👑")
            return
    
    markup = InlineKeyboardMarkup()
    for group_id in admin_groups:
        cursor.execute("SELECT title FROM groups WHERE id = ?", (group_id,))
        title = cursor.fetchone()[0]
        markup.add(InlineKeyboardButton(f"{title} 📊", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(chat_id, "Select a group to manage:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_group_'))
def admin_group_dashboard(call):
    group_id = int(call.data.split('_')[2])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Analytics 📈", callback_data=f"analytics_{group_id}"))
    markup.add(InlineKeyboardButton("Settings ⚙️", callback_data=f"settings_{group_id}"))
    markup.add(InlineKeyboardButton("Anti-Spam 🛡️", callback_data=f"antispam_{group_id}"))
    markup.add(InlineKeyboardButton("Welcome/Goodbye ✉️", callback_data=f"messages_{group_id}"))
    markup.add(InlineKeyboardButton("Integrations 🔗", callback_data=f"integrations_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data="back_to_main"))
    
    bot.send_message(call.message.chat.id, f"Dashboard for group {group_id} 👑", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('analytics_'))
def show_analytics(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    cursor.execute("SELECT user_id, referred_count FROM referrals WHERE group_id = ? ORDER BY referred_count DESC LIMIT 5", (group_id,))
    referrals = cursor.fetchall()
    ref_text = "Top Referrers:\n" + "\n".join([f"User {u[0]}: {u[1]}" for u in referrals]) or "None"
    
    cursor.execute("SELECT user_id, message_count FROM engagement WHERE group_id = ? ORDER BY message_count DESC LIMIT 5", (group_id,))
    eng = cursor.fetchall()
    eng_text = "Top Active Members:\n" + "\n".join([f"User {u[0]}: {u[1]} msgs" for u in eng]) or "None"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, f"Analytics:\n{ref_text}\n\n{eng_text}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('settings_'))
def settings_menu(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    markup = InlineKeyboardMarkup(row_width=2)
    cursor.execute("SELECT buy_alerts_enabled, raiding_enabled FROM groups WHERE id = ?", (group_id,))
    buy, raid = cursor.fetchone()
    markup.add(InlineKeyboardButton(f"Buy Alerts {'✅' if buy else '❌'}", callback_data=f"toggle_buy_{group_id}"))
    markup.add(InlineKeyboardButton(f"Raiding {'✅' if raid else '❌'}", callback_data=f"toggle_raid_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, "Settings:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_buy_'))
def toggle_buy(call):
    group_id = int(call.data.split('_')[2])
    cursor.execute("UPDATE groups SET buy_alerts_enabled = 1 - buy_alerts_enabled WHERE id = ?", (group_id,))
    conn.commit()
    bot.answer_callback_query(call.id, "Buy alerts toggled! ✅")
    # Refresh menu
    settings_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_raid_'))
def toggle_raid(call):
    group_id = int(call.data.split('_')[2])
    cursor.execute("UPDATE groups SET raiding_enabled = 1 - raiding_enabled WHERE id = ?", (group_id,))
    conn.commit()
    bot.answer_callback_query(call.id, "Raiding toggled! ✅")
    # Refresh menu
    settings_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('antispam_'))
def antispam_menu(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    markup = InlineKeyboardMarkup(row_width=2)
    cursor.execute("SELECT anti_spam_enabled FROM groups WHERE id = ?", (group_id,))
    enabled = cursor.fetchone()[0]
    markup.add(InlineKeyboardButton(f"Anti-Spam {'✅' if enabled else '❌'}", callback_data=f"toggle_spam_{group_id}"))
    markup.add(InlineKeyboardButton("Set Banned Words 🚫", callback_data=f"set_banned_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, "Anti-Spam Settings:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_spam_'))
def toggle_spam(call):
    group_id = int(call.data.split('_')[2])
    cursor.execute("UPDATE groups SET anti_spam_enabled = 1 - anti_spam_enabled WHERE id = ?", (group_id,))
    conn.commit()
    bot.answer_callback_query(call.id, "Anti-spam toggled! ✅")
    # Refresh
    antispam_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_banned_'))
def set_banned(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter banned words separated by commas (e.g., fuck,bitch)")
    user_states[call.from_user.id] = {'state': 'waiting_banned', 'group_id': group_id, 'prompt_msg_id': msg.message_id}

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_banned')
def handle_banned_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    banned = message.text.strip()
    cursor.execute("UPDATE groups SET banned_words = ? WHERE id = ?", (banned, group_id))
    conn.commit()
    
    # Delete input and prompt
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    bot.send_message(message.chat.id, "✅ Filter updated successfully.")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('messages_'))
def messages_menu(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Set Welcome Message ✉️", callback_data=f"set_welcome_{group_id}"))
    markup.add(InlineKeyboardButton("Set Goodbye Message 👋", callback_data=f"set_goodbye_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, "Welcome/Goodbye Settings:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_welcome_'))
def set_welcome(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter new welcome message (use {username} for placeholder):")
    user_states[call.from_user.id] = {'state': 'waiting_welcome', 'group_id': group_id, 'prompt_msg_id': msg.message_id}

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_welcome')
def handle_welcome_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    welcome = message.text.strip()
    cursor.execute("UPDATE groups SET welcome_msg = ? WHERE id = ?", (welcome, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    bot.send_message(message.chat.id, "✅ Welcome message updated.")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_goodbye_'))
def set_goodbye(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter new goodbye message (use {username} for placeholder):")
    user_states[call.from_user.id] = {'state': 'waiting_goodbye', 'group_id': group_id, 'prompt_msg_id': msg.message_id}

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_goodbye')
def handle_goodbye_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    goodbye = message.text.strip()
    cursor.execute("UPDATE groups SET goodbye_msg = ? WHERE id = ?", (goodbye, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    bot.send_message(message.chat.id, "✅ Goodbye message updated.")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('integrations_'))
def integrations_menu(call):
    group_id = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Set Channel Link 📢", callback_data=f"set_channel_{group_id}"))
    markup.add(InlineKeyboardButton("Set Bot Link 🤖", callback_data=f"set_botlink_{group_id}"))
    markup.add(InlineKeyboardButton("Set Twitter Handle 🐦", callback_data=f"set_twitter_{group_id}"))
    markup.add(InlineKeyboardButton("Back 🔙", callback_data=f"admin_group_{group_id}"))
    
    bot.send_message(call.message.chat.id, "Integrations Settings:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_channel_'))
def set_channel(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter channel link (e.g., t.me/channel):")
    user_states[call.from_user.id] = {'state': 'waiting_channel', 'group_id': group_id, 'prompt_msg_id': msg.message_id}

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_channel')
def handle_channel_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    link = message.text.strip()
    cursor.execute("UPDATE groups SET channel_link = ? WHERE id = ?", (link, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    bot.send_message(message.chat.id, "✅ Channel link updated.")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_botlink_'))
def set_botlink(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter bot link (e.g., t.me/otherbot):")
    user_states[call.from_user.id] = {'state': 'waiting_botlink', 'group_id': group_id, 'prompt_msg_id': msg.message_id}

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_botlink')
def handle_botlink_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    link = message.text.strip()
    cursor.execute("UPDATE groups SET bot_link = ? WHERE id = ?", (link, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    bot.send_message(message.chat.id, "✅ Bot link updated.")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_twitter_'))
def set_twitter(call):
    group_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id, "Enter Twitter handle (without @):")
    user_states[call.from_user.id] = {'state': 'waiting_twitter', 'group_id': group_id, 'prompt_msg_id': msg.message_id}

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id].get('state') == 'waiting_twitter')
def handle_twitter_input(message):
    group_id = user_states[message.from_user.id]['group_id']
    handle = message.text.strip()
    cursor.execute("UPDATE groups SET twitter_handle = ? WHERE id = ?", (handle, group_id))
    conn.commit()
    
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, user_states[message.from_user.id]['prompt_msg_id'])
    
    bot.send_message(message.chat.id, "✅ Twitter handle updated. If raiding is enabled, polling will start.")
    del user_states[message.from_user.id]
    # Restart polling if needed
    start_raiding_polls()

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_main')
def back_to_main(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    admin_dashboard(call.message)  # Treat call.message as message for admin_dashboard

# Group events
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_member(message):
    group_id = message.chat.id
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            cursor.execute("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", (group_id, message.chat.title))
            admins = bot.get_chat_administrators(group_id)
            for admin in admins:
                cursor.execute("INSERT OR IGNORE INTO admins (group_id, user_id) VALUES (?, ?)", (group_id, admin.user.id))
            conn.commit()
            bot.send_message(group_id, "Thanks for adding me! Admins can manage me via /admin in private chat. 👑")
        else:
            user_id = member.id
            cursor.execute("SELECT verified, referrer_id FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            if result and result[0] == 1 and result[1]:
                referrer_id = result[1]
                cursor.execute("""
                    INSERT INTO referrals (group_id, user_id, referred_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(group_id, user_id) DO UPDATE SET referred_count = referred_count + 1
                """, (group_id, referrer_id))
                conn.commit()
            
            if not result or result[0] == 0:
                bot.send_message(user_id, "Please verify to stay in the group! Start me and complete the challenge. ⏳")
                pending_verifications[user_id] = {'group_id': group_id, 'time': time.time()}
            
            cursor.execute("SELECT welcome_msg FROM groups WHERE id = ?", (group_id,))
            msg = cursor.fetchone()[0] or "Welcome, {username}! 🎉"
            bot.send_message(group_id, msg.format(username=member.username or "user"))

def check_pending():
    while True:
        now = time.time()
        to_kick = []
        for user_id, data in list(pending_verifications.items()):
            if now - data['time'] > 300:
                try:
                    bot.ban_chat_member(data['group_id'], user_id, revoke_messages=False)
                except:
                    pass
                to_kick.append(user_id)
        for u in to_kick:
            del pending_verifications[u]
        time.sleep(60)

threading.Thread(target=check_pending, daemon=True).start()

@bot.message_handler(content_types=['left_chat_member'])
def handle_left_member(message):
    cursor.execute("SELECT goodbye_msg FROM groups WHERE id = ?", (message.chat.id,))
    msg = cursor.fetchone()[0] or "Goodbye, {username}! 👋"
    bot.send_message(message.chat.id, msg.format(username=message.left_chat_member.username or "user"))

# Message handler for engagement and anti-spam
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'])
def handle_group_message(message):
    group_id = message.chat.id
    user_id = message.from_user.id
    
    cursor.execute("SELECT anti_spam_enabled, banned_words FROM groups WHERE id = ?", (group_id,))
    enabled, banned = cursor.fetchone()
    if enabled and banned:
        banned_list = [w.strip() for w in banned.split(',')]
        for word in banned_list:
            if word in message.text.lower():
                bot.delete_message(group_id, message.message_id)
                bot.send_message(user_id, "Your message contained banned words. 🚫")
                return
    
    cursor.execute("""
        INSERT INTO engagement (group_id, user_id, message_count)
        VALUES (?, ?, 1)
        ON CONFLICT(group_id, user_id) DO UPDATE SET message_count = message_count + 1
    """, (group_id, user_id))
    conn.commit()

# Start raiding polls
start_raiding_polls()

bot.infinity_polling()