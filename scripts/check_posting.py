import os, json, requests, gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone

SHEET_NAME_MAP = {
    "monday":    "Понедельник",
    "wednesday": "Среда",
    "thursday":  "Четверг",
    "friday":    "Пятница"
}

def get_sheets_client():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return gspread.authorize(creds)

def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Telegram not configured")
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
        timeout=15
    )
    print("Telegram sent")

def check_today_published(sheet_name):
    client = get_sheets_client()
    sheet = client.open_by_key(os.environ["SPREADSHEET_ID"]).worksheet(sheet_name)
    records = sheet.get_all_records()

    # Bangkok = UTC+7
    from datetime import timedelta
    today_bangkok = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%d.%m.%Y")
    print(f"Checking sheet: {sheet_name} | Today (Bangkok): {today_bangkok}")

    stuck_num = None
    for row in records:
        status = row.get("Статус", "")
        pub_date = str(row.get("Дата публикации", "")).strip()
        post_num = row.get("#", "")

        if status == "Опубликовано" and pub_date == today_bangkok:
            post_url = row.get("Ссылка на пост", "")
            print(f"Found published post #{post_num} today!")
            return True, post_num, post_url

        if status == "В обработке":
            stuck_num = post_num

    if stuck_num:
        print(f"Post #{stuck_num} stuck in processing!")
        return False, stuck_num, None

    print("No post published today")
    return False, None, None

def main():
    day_env = os.environ.get("DAY", "monday").lower()
    sheet_name = SHEET_NAME_MAP.get(day_env, "Понедельник")
    attempt = int(os.environ.get("ATTEMPT", "1"))
    max_attempts = int(os.environ.get("MAX_ATTEMPTS", "2"))

    print(f"=== Monitor | {sheet_name} | Attempt {attempt}/{max_attempts} ===")

    published, post_num, post_url = check_today_published(sheet_name)

    if published:
        print(f"Post #{post_num} published OK!")
        if attempt == 1:
            send_telegram(
                f"✅ *Публикация подтверждена — Threads @esimsData*\n\n"
                f"📅 День: {sheet_name}\n"
                f"📝 Пост #{post_num}\n"
                f"🔗 {post_url or 'нет ссылки'}"
            )
        exit(0)
    else:
        if attempt >= max_attempts:
            stuck = f" (застрял в обработке, пост #{post_num})" if post_num else ""
            send_telegram(
                f"🚨 *ОШИБКА публикации — Threads @esimsData*\n\n"
                f"📅 День: {sheet_name}\n"
                f"🚫 Публикация не выполнена{stuck}\n"
                f"🔧 github.com/siamocean/esimsdata-threads/actions"
            )
            print(f"Alert sent! Not published after {max_attempts} checks.")
            exit(1)
        else:
            print(f"Not published yet. Attempt {attempt}/{max_attempts}.")
            exit(1)

if __name__ == "__main__":
    main()
