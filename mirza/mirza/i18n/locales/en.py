"""English catalog."""
MESSAGES = {
    "users": {
        "menu": {
            "services": "🔧 My services",
            "buy": "🛒 Buy service",
            "test": "🎁 Free trial",
            "wallet": "💳 Wallet",
            "topup": "Top up",
            "referral": "👥 Referrals",
            "gift": "🎁 Gift code",
            "rules": "♨️ Rules",
            "help": "📚 Help",
            "faq": "💡 FAQ",
            "support": "☎️ Support",
            "account": "👤 Account",
            "back": "🔙 Back",
        },
        "channel": {
            "link_unset": "Not set",
            "text_join": "🔗 Join the channel",
            "confirm_join": "✅ Check membership",
            "confirmed": "Your membership is confirmed. Thanks ❤️",
            "not_confirmed": "❌ You have not joined the channel yet.",
        },
        "rules_ok": "✅ Rules accepted. Enjoy our services!",
        "start": "Hi {name}, welcome to {shop} 🌹",
        "phone": {
            "ask": "Please share your phone number 📱",
            "invalid": "Invalid phone number ❌",
            "iran_only": "Only Iranian numbers are accepted ❌",
        },
        "balance": {
            "show": "💰 Your balance: {balance}",
            "insufficient": "Insufficient balance. Please top up first ❗",
        },
        "buy": {
            "choose_category": "Pick a category:",
            "choose_product": "Pick a product:",
            "choose_location": "Choose server location:",
            "invoice": (
                "🧾 Invoice:\n\n"
                "📦 Product: {product}\n"
                "🌐 Location: {location}\n"
                "📊 Volume: {volume}\n"
                "⏳ Duration: {duration}\n"
                "💵 Price: {price}"
            ),
            "success": "✅ Service created!\n\n🔗 Subscription:\n{sub_url}",
            "failed": "❌ Failed to create service: {reason}",
        },
        "test": {"ok": "🎉 Your trial service is ready:\n{sub_url}", "no_more": "You have used your free trials."},
        "renew": {"ask_days": "How many days to extend?", "done": "✅ Renewed until {date}"},
        "extra_volume": {"ask_gb": "Extra volume in GB:", "price_note": "{price} per GB", "done": "✅ Added {gb} GB."},
        "config": {
            "show": "⚙️ Service {username}\n\n📊 Used: {used} of {total}\n⏳ Expires: {expires}",
            "qr_caption": "Scan the QR to connect",
            "not_found": "Service not found.",
        },
        "referral": {
            "menu": ("👥 Referrals\n\nYour link:\n{link}\n\nInvited: {count}\nReward each: {reward}"),
            "self": "You cannot use your own link ❌",
        },
        "gift": {"ask_code": "Enter gift code:", "result_ok": "✅ {amount} added to your wallet."},
        "money": {"invalid_price": "Invalid price."},
        "cancel": "Cancelled.",
    },
    "admin": {
        "login": "👋 Welcome, admin; version {version}",
        "panel_btns": {
            "users": "👥 Users",
            "products": "📦 Products",
            "panels": "🔌 Panels",
            "settings": "⚙️ Settings",
            "broadcast": "📨 Broadcast",
            "reports": "📊 Reports",
            "payments": "💳 Payments",
        },
        "user": {
            "found": "👤 User {id}\nbalance: {balance}\nstatus: {status}\nreferrals: {refs}",
            "not_found": "User not found ❌",
            "blocked": "🚫 Blocked. Reason: {reason}",
            "unblocked": "✅ Unblocked.",
        },
        "panel_mgmt": {
            "added": "✅ Panel saved.",
            "tested_ok": "✅ Connection OK: {info}",
            "tested_fail": "❌ Connection failed: {reason}",
        },
        "broadcast": {
            "ask_text": "Send the broadcast text:",
            "started": "Broadcast started; {count} users queued.",
            "progress": "Progress: {sent}/{total}",
            "done": "✅ Done: {sent} sent, {failed} failed",
        },
        "receipt": {
            "new": "🧾 Card payment receipt\nUser: {user}\nAmount: {amount}\nOrder: {order}",
            "approved": "✅ Approved; credited {amount}.",
            "rejected": "❌ Rejected and user notified.",
        },
    },
    "common": {"error": "⚠️ Something went wrong. Try again.", "yes": "Yes", "no": "No"},
}
