# app.py — น้องเพิล ผู้ช่วยตอบแชท LINE ของร้านคุณ
# โค้ดประกอบเล่ม "Automate ด้วย AI + API #01 · LINE ตอบแชทอัตโนมัติ" (Work With AI Lemon)
#
# ประกอบจากทั้งเล่ม:
#   บทที่ 8  เบื้องต้น — webhook + ตรวจลายเซ็น + ถามสมอง AI + ตอบด้วย reply (ฟรี)
#   บทที่ 9  ราวกันพลาดชั้นที่ 3 — คำถามเรื่องเงิน/เอกสาร โดนดักก่อนถึง AI
#   บทที่ 10 งานหลังบ้าน — จดบันทึกทุกบทสนทนา + แจ้งเตือนเจ้าของร้านเมื่อมีธงส่งต่อ
#           + คำสั่ง "สรุป" สำหรับเจ้าของร้าน
#   บทที่ 12 สอนให้ AI รู้เวลาปัจจุบัน (คำถามประเภท "ส่งวันนี้ได้ไหม" ตอบตรงกติกาจริง)
#   บทที่ 6  กรณีที่ 2 — สลับผู้ให้บริการสมองเป็น OpenRouter ได้จากไฟล์ .env
#
# วิธีใช้ครบทุกขั้น อ่านใน README.md ของ repo นี้ หรือตามเล่มทีละบท

import os
import re
import hmac
import hashlib
import base64
from datetime import datetime

import requests
from flask import Flask, request, abort
from dotenv import load_dotenv

load_dotenv()                                    # อ่านกุญแจจากไฟล์ .env

LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")   # รหัสตรวจแขก (บทที่ 3)
LINE_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")     # กุญแจส่งข้อความออก (บทที่ 3)
AI_KEY = os.getenv("AI_API_KEY")                 # กุญแจสมอง AI (บทที่ 6)
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")  # anthropic หรือ openrouter
AI_MODEL = os.getenv("AI_MODEL", "")             # เว้นว่าง = ใช้รุ่นเริ่มต้นด้านล่าง
BOSS_ID = os.getenv("BOSS_ID", "")               # รหัสเจ้าของร้าน (บทที่ 10)

DEFAULT_MODEL = {
    "anthropic": "claude-haiku-4-5",             # รุ่นเหมาะกับงานตอบแชท ถูกและเร็ว (บทที่ 6)
    "openrouter": "anthropic/claude-haiku-4.5",  # ชื่อรุ่นบน OpenRouter (กรณีที่ 2)
}

PERSONA = open("persona.txt", encoding="utf-8").read()          # ใบสั่งงาน (บทที่ 5)
KNOWLEDGE = open("shop-knowledge.md", encoding="utf-8").read()  # คู่มือร้าน (บทที่ 7)

app = Flask(__name__)

# บทที่ 9 · ราวชั้นที่ 3 — คำถามที่ห้าม AI ตอบเด็ดขาด ให้ตอบทางการแล้วส่งต่อทันที
FORBIDDEN = re.compile(
    r"เลขบัตร|บัญชี|โอนเงิน|รหัส(?:ผ่าน|OTP)|คำสั่งซื้อ\s*\d{4,}|ใบเสร็จ",
    re.IGNORECASE,
)
GUARDED_REPLY = ("เรื่องนี้ต้องให้ทีมร้านตรวจสอบข้อมูลให้ถูกต้องก่อนนะคะ "
                 "เดี๋ยวทีมร้านจะติดต่อกลับให้ค่ะ [ส่งต่อ: ข้อมูลการเงิน]")


def verify_signature(body: bytes, signature: str) -> bool:
    """ตรวจว่าข้อความนี้มาจาก LINE จริง ไม่ใช่คนแอบอ้าง (บทที่ 8)"""
    mac = hmac.new(LINE_SECRET.encode(), body, hashlib.sha256)
    expected = base64.b64encode(mac.digest()).decode()
    return hmac.compare_digest(expected, signature)


def ask_ai(question: str) -> str:
    """ถามสมอง AI พร้อมแนบ persona และคู่มือร้านไปด้วย (บทที่ 6 และ 8)

    กรณีที่ 1 (AI_PROVIDER=anthropic) — เช่าตรงกับผู้ให้บริการ
    กรณีที่ 2 (AI_PROVIDER=openrouter) — ผ่าน OpenRouter คนกลาง สลับรุ่นได้ทุกค่าย
    """
    system_text = PERSONA + "\n\n---\n\n# คู่มือร้าน\n" + KNOWLEDGE

    if AI_PROVIDER == "openrouter":
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": "Bearer " + AI_KEY,
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL or DEFAULT_MODEL["openrouter"],
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": question},
                ],
            },
            timeout=25,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": AI_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": AI_MODEL or DEFAULT_MODEL["anthropic"],
            "max_tokens": 300,
            "system": system_text,
            "messages": [{"role": "user", "content": question}],
        },
        timeout=25,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def reply(token: str, text: str) -> None:
    """ใช้บัตร reply ส่งคำตอบกลับเข้าแชทเดิม — ฟรี ไม่กินโควตา (บทที่ 4)"""
    requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": "Bearer " + LINE_TOKEN,
            "Content-Type": "application/json",
        },
        json={
            "replyToken": token,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=10,
    )


def push(to: str, text: str) -> None:
    """ส่งข้อความหาคนใดคนหนึ่งแบบริเริ่ม — นับโควตา ใช้เฉพาะเรื่องสำคัญ (บทที่ 10)"""
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": "Bearer " + LINE_TOKEN,
            "Content-Type": "application/json",
        },
        json={
            "to": to,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=10,
    )


def log_chat(user_id: str, question: str, answer: str) -> None:
    """จดบันทึกทุกคู่ถาม-ตอบ ลงไฟล์รายวัน — จำแค่หกตัวท้ายของรหัส (บทที่ 10)"""
    day = datetime.now().strftime("%Y-%m-%d")
    stamp = datetime.now().strftime("%H:%M:%S")
    with open(f"chatlog-{day}.txt", "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] ลูกค้า ...{user_id[-6:]}\n")
        f.write(f"  ถาม: {question}\n")
        f.write(f"  ตอบ: {answer}\n\n")


@app.route("/webhook", methods=["POST"])
def webhook():
    """ประตูที่ LINE เคาะส่งข้อความเข้ามา (บทที่ 8)"""
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        abort(400)

    for event in request.get_json().get("events", []):
        if event.get("type") != "message":
            continue
        if event["message"].get("type") != "text":
            continue

        question = event["message"]["text"]
        user_id = event["source"].get("userId", "")

        # คำสั่งพิเศษของเจ้าของร้าน — สรุปยอดวันนี้ (บทที่ 10)
        if question.strip() == "สรุป" and user_id == BOSS_ID:
            day = datetime.now().strftime("%Y-%m-%d")
            try:
                history = open(f"chatlog-{day}.txt", encoding="utf-8").read()
            except FileNotFoundError:
                history = "(วันนี้ยังไม่มีบทสนทนา)"
            answer = ask_ai(
                "สรุปบันทึกแชทร้านวันนี้เป็นรายงานสั้น ๆ หัวข้อ: "
                "จำนวนคำถาม / คำถามที่ถูกถามมากที่สุด / "
                "เรื่องส่งต่อที่รอเจ้าของร้าน และข้อสังเกตหนึ่งอย่าง "
                "ข้อมูล:\n" + history
            )
            reply(event["replyToken"], answer)
            continue

        # บทที่ 12 · แนบเวลาปัจจุบันให้ AI — คำถามเรื่องเวลาตอบตรงกติกาจริง
        now = datetime.now()
        thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
        timed_question = (
            f"(ขณะนี้เวลา {now:%H:%M} น. วัน{thai_days[now.weekday()]})\n" + question
        )

        # บทที่ 9 · ราวชั้นที่ 3 ตรวจก่อนส่งเข้าสมอง AI
        if FORBIDDEN.search(question):
            answer = GUARDED_REPLY
        else:
            try:
                answer = ask_ai(timed_question)
            except Exception:
                answer = ("ขออภัยค่ะ ระบบติดขัดชั่วคราว "
                          "เดี๋ยวทีมร้านจะติดต่อกลับนะคะ [ส่งต่อ: ระบบผิดปกติ]")

        reply(event["replyToken"], answer)
        log_chat(user_id, question, answer)

        # บทที่ 10 · มีธงส่งต่อ = แจ้งเจ้าของร้านทันที
        if "[ส่งต่อ:" in answer and BOSS_ID:
            push(BOSS_ID, f"มีเรื่องส่งต่อจากน้องเพิล\n{question}\n\n{answer}")

    return "OK"


@app.route("/health")
def health():
    """หน้าตรวจว่าโปรแกรมยังมีชีวิต — ใช้ตั้งเว็บเฝ้าคอยปลุกระบบแผนฟรี (บทที่ 11)"""
    return "น้องเพิลยังทำงานอยู่ค่ะ"


if __name__ == "__main__":
    app.run(port=8000)
