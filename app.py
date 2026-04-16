import os
import re
import uuid
from datetime import date, timedelta
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from icalendar import Calendar, Event

app = Flask(__name__)

configuration = Configuration(access_token=os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000')

# 暫存事件（key: uuid, value: (date, name)）
event_store = {}


def parse_event(text):
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
    event_id = str(uuid.uuid4())
    event_store[event_id] = (event_date, event_name)
    return f"{BASE_URL}/event/{event_id}.ics"


@app.route("/event/<event_id>.ics")
def serve_ics(event_id):
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

    response = app.response_class(
        response=cal.to_ical(),
        mimetype='text/calendar; charset=utf-8',
    )
    response.headers['Content-Disposition'] = 'inline; filename="event.ics"'
    return response


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    event_date, event_name = parse_event(text)

    if event_date and event_name:
        ics_url = create_ics_url(event_date, event_name)
        date_str = event_date.strftime('%Y年%m月%d日')
        reply_text = (
            f"📅 {date_str}　📝 {event_name}\n\n"
            f"點下方連結加入行事曆：\n"
            f"{ics_url}"
        )
    else:
        reply_text = (
            "請用以下格式傳訊息：\n"
            "・4/15 家教\n"
            "・4月15號 補習\n"
            "・明天 家教\n"
            "・我4/15家教"
        )

    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
