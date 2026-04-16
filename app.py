import os
import re
import uuid
from datetime import date, timedelta
from flask import Flask, request, abort, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from icalendar import Calendar, Event
import io

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')

# 暫存事件（key: uuid, value: (date, name)）
event_store = {}


def parse_event(text):
    """
    解析文字中的日期與事件名稱。
    支援格式：
      4/15 家教 / 4月15日 補習 / 今天 家教 / 我4/15家教
    """
    today = date.today()
    current_year = today.year

    text = re.sub(r'^(我|要|有)\s*', '', text.strip())

    relative_map = {
        '今天': today,
        '明天': today + timedelta(days=1),
        '後天': today + timedelta(days=2),
        '大後天': today + timedelta(days=3),
    }
    for keyword, rel_date in relative_map.items():
        if text.startswith(keyword):
            event_name = re.sub(r'^(今天|明天|後天|大後天)\s*(有|要)?\s*', '', text).strip()
            if event_name:
                return rel_date, event_name

    patterns = [
        r'(\d{1,2})[/／](\d{1,2})\s*(有|要)?\s*(.+)',
        r'(\d{1,2})月(\d{1,2})[日號号]\s*(有|要)?\s*(.+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            event_name = match.group(4).strip()
            try:
                event_date = date(current_year, month, day)
                if event_date < today:
                    event_date = date(current_year + 1, month, day)
            except ValueError:
                return None, None
            if event_name:
                return event_date, event_name

    return None, None


def create_ics_url(event_date, event_name):
    """產生 .ics 下載連結並暫存事件資料"""
    event_id = str(uuid.uuid4())
    event_store[event_id] = (event_date, event_name)
    return f"{BASE_URL}/event/{event_id}.ics"


@app.route("/event/<event_id>.ics")
def serve_ics(event_id):
    """提供 .ics 檔案下載"""
    if event_id not in event_store:
        abort(404)

    event_date, event_name = event_store[event_id]

    cal = Calendar()
    cal.add('prodid', '-//LINE Calendar Bot//TW//')
    cal.add('version', '2.0')
    cal.add('method', 'PUBLISH')

    event = Event()
    event.add('summary', event_name)
    event.add('dtstart', event_date)
    event.add('dtend', event_date + timedelta(days=1))
    event.add('uid', event_id + '@line-bot')

    cal.add_component(event)

    ics_data = cal.to_ical()
    return send_file(
        io.BytesIO(ics_data),
        mimetype='text/calendar',
        as_attachment=True,
        download_name='event.ics'
    )


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    event_date, event_name = parse_event(text)

    if event_date and event_name:
        ics_url = create_ics_url(event_date, event_name)
        date_str = event_date.strftime('%Y年%m月%d日')
        reply = (
            f"📅 {date_str}　📝 {event_name}\n\n"
            f"點下方連結加入行事曆：\n"
            f"{ics_url}"
        )
    else:
        reply = (
            "請用以下格式傳訊息：\n"
            "・4/15 家教\n"
            "・4月15號 補習\n"
            "・明天 家教\n"
            "・我4/15家教"
        )

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
