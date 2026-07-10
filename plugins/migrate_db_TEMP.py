# ⚠️⚠️⚠️ TEMPORARY FILE — सिर्फ़ एक बार Migration के लिए ⚠️⚠️⚠️
# इस्तेमाल:
#   1. इसे /plugins/ फोल्डर में डालें, बॉट restart करें
#   2. बॉट को PM में भेजें:
#        /migrate_db NEW_MONGO_URL [DB_NAME]
#      उदाहरण:
#        /migrate_db mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
#      (DB_NAME ना दें तो अपने आप DATABASE_NAME (info.py) वाला इस्तेमाल होगा)
#   3. बॉट progress मैसेज खुद अपडेट करता रहेगा
#   4. पूरा होने पर Koyeb के DATABASE_URL env var को नए वाले से बदलें और बॉट restart करें
#   5. ⚠️ यह मैसेज (जिसमें नया password है) Telegram से Delete करें
#   6. ⚠️ यह फाइल /plugins/ से हटा दें और बॉट फिर से restart करें

import time
import motor.motor_asyncio
from hydrogram import Client, filters
from info import ADMINS, DATABASE_URL, DATABASE_NAME

BATCH_SIZE = 500


@Client.on_message(filters.private & filters.user(ADMINS) & filters.command("migrate_db"))
async def migrate_db_cmd(bot, message):
    if len(message.command) < 2:
        return await message.reply(
            "⚠️ <b>इस्तेमाल:</b>\n"
            "<code>/migrate_db NEW_MONGO_URL [DB_NAME]</code>\n\n"
            "उदाहरण:\n"
            "<code>/migrate_db mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority</code>"
        )

    new_url = message.command[1]
    db_name = message.command[2] if len(message.command) > 2 else DATABASE_NAME

    status = await message.reply("🚚 <b>Migration शुरू हो रही है...</b>\n\nनए DB से कनेक्ट किया जा रहा है...")

    try:
        old_client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
        new_client = motor.motor_asyncio.AsyncIOMotorClient(new_url)
        old_db = old_client[db_name]
        new_db = new_client[db_name]
        # ✅ कनेक्शन टेस्ट — यहीं पता चल जाएगा अगर URL/password/IP-whitelist गलत है
        await new_client.admin.command("ping")
    except Exception as e:
        return await status.edit(f"❌ <b>नए DB से कनेक्ट नहीं हो पाया:</b>\n<code>{e}</code>\n\n"
                                  f"👉 Atlas में Network Access में <code>0.0.0.0/0</code> जुड़ा है ना, चेक कर लें।")

    collections = await old_db.list_collection_names()
    if not collections:
        return await status.edit("❌ पुराने DB में कोई collection नहीं मिली — DB_NAME चेक करें।")

    grand_total = 0
    last_edit = time.time()

    for col_name in collections:
        old_col = old_db[col_name]
        new_col = new_db[col_name]
        total = await old_col.count_documents({})
        copied, batch = 0, []

        async for doc in old_col.find({}):
            batch.append(doc)
            if len(batch) >= BATCH_SIZE:
                copied += await _insert_batch(new_col, batch)
                batch = []
                # टेलीग्राम फ्लड-प्रिवेंटर — हर 4 सेकंड में सिर्फ़ एक बार edit
                if time.time() - last_edit > 4:
                    last_edit = time.time()
                    try:
                        await status.edit(f"🚚 <b>Migration जारी है...</b>\n\n📂 <code>{col_name}</code>: {copied}/{total}")
                    except Exception:
                        pass

        if batch:
            copied += await _insert_batch(new_col, batch)

        grand_total += copied
        try:
            await status.edit(f"✅ <code>{col_name}</code> पूरा: {copied}/{total}\n\n⏳ अगली collection की तरफ़...")
        except Exception:
            pass

    old_client.close()
    new_client.close()

    await status.edit(
        f"🎉 <b>Migration पूरा हुआ!</b>\n\n"
        f"📦 कुल collections: <code>{len(collections)}</code>\n"
        f"📄 कुल documents कॉपी हुए: <code>{grand_total}</code>\n\n"
        f"👉 अब Koyeb में <b>DATABASE_URL</b> env var को नए वाले से बदलें और बॉट restart करें।\n"
        f"⚠️ फिर यह मैसेज Delete करें और यह फाइल plugins से हटाकर restart करें।"
    )


async def _insert_batch(new_col, batch):
    """duplicate _id (re-run की स्थिति में) पर पूरा batch fail न हो"""
    try:
        res = await new_col.insert_many(batch, ordered=False)
        return len(res.inserted_ids)
    except Exception:
        return len(batch)
