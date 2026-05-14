import os, json, requests, gspread, time
from google.oauth2.service_account import Credentials
from datetime import datetime

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

def get_next_pending_row(sheet):
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        if row.get("Статус") == "Ожидает":
            return i + 2, row
    return None, None

def update_row_status(sheet, row_index, status, post_url=""):
    today = datetime.now().strftime("%d.%m.%Y")
    sheet.update_cell(row_index, 5, status)
    sheet.update_cell(row_index, 6, today)
    if post_url:
        sheet.update_cell(row_index, 7, post_url)

def post_to_buffer(text):
    api_key = os.environ["BUFFER_API_KEY"]
    channel_id = "6a0554b0090476fb991a3a82"
    from datetime import timezone, timedelta
    due = (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    query = """
    mutation CreatePost($input: CreatePostInput!) {
        createPost(input: $input) {
            ... on PostActionSuccess { post { id text dueAt } }
            ... on MutationError { message }
        }
    }
    """
    variables = {
        "input": {
            "channelId": channel_id,
            "text": text,
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": due
        }
    }
    resp = requests.post(
        "https://api.buffer.com",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"query": query, "variables": variables},
        timeout=120
    )
    data = resp.json()
    print(f"Buffer create response: {data}")
    post_data = data.get("data", {}).get("createPost", {})
    if "post" not in post_data:
        print(f"Buffer FULL response: {resp.text}")
        error = post_data.get("message", str(data))
        raise Exception(f"Buffer error: {error}")
    buffer_post_id = post_data["post"]["id"]
    print(f"Buffer post created: {buffer_post_id}, waiting 3 min...")
    time.sleep(180)
    get_query = """
    query GetPost($id: String!) {
        post(id: $id) {
            id
            status
            serviceLinks { url }
        }
    }
    """
    resp2 = requests.post(
        "https://api.buffer.com",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"query": get_query, "variables": {"id": buffer_post_id}},
        timeout=30
    )
    data2 = resp2.json()
    print(f"Buffer post status: {data2}")
    post2 = data2.get("data", {}).get("post", {})
    links = post2.get("serviceLinks", [])
    if links:
        return links[0].get("url", f"https://buffer.com/post/{buffer_post_id}")
    return f"https://buffer.com/post/{buffer_post_id}"

def post_to_ayrshare(text):
    api_key = os.environ["AYRSHARE_API_KEY"]
    resp = requests.post(
        "https://api.ayrshare.com/api/post",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"post": text, "platforms": ["threads"]},
        timeout=120
    )
    print(f"Ayrshare {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    result = resp.json()
    post_data = result.get("postIds", [{}])[0]
    post_url = post_data.get("postUrl", "") or post_data.get("url", "")
    if not post_url:
        post_id = post_data.get("id", "")
        post_url = f"https://www.threads.net/post/{post_id}" if post_id else "posted"
    print(f"Post URL: {post_url}")
    return post_url

def post_to_social(text):
    service = os.environ.get("POSTING_SERVICE", "buffer")
    if service == "buffer":
        return post_to_buffer(text)
    else:
        return post_to_ayrshare(text)


def send_telegram_notification(day_name, text, post_url):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    msg = (
        f"✅ *Новая публикация — Threads @esimsData*\n\n"
        f"📅 {day_name}\n"
        f"📝 {text[:120]}...\n"
        f"🔗 [Открыть пост]({post_url})"
    )
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
        timeout=15
    )
    print("Telegram sent")

def main():
    day_env = os.environ.get("DAY", "monday").lower()
    sheet_name = SHEET_NAME_MAP.get(day_env, "Понедельник")
    print(f"=== eSIMsData Threads Bot | {sheet_name} ===")
    client = get_sheets_client()
    sheet = client.open_by_key(os.environ["SPREADSHEET_ID"]).worksheet(sheet_name)
    row_index, row_data = get_next_pending_row(sheet)
    if not row_data:
        print("No pending rows. Exiting.")
        return
    text = row_data.get("Текст поста", "")
    print(f"Post #{row_data.get('#')}: {text[:80]}...")
    update_row_status(sheet, row_index, "В обработке")
    post_url = post_to_social(text)
    update_row_status(sheet, row_index, "Опубликовано", post_url)
    send_telegram_notification(sheet_name, text, post_url)
    print("Done!")

if __name__ == "__main__":
    main()
