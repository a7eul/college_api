from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import date
from typing import List, Optional
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import shutil
from pathlib import Path
import time

load_dotenv()

app = FastAPI(title="College Messenger API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserLogin(BaseModel):
    login: str
    password: str

class User(BaseModel):
    id: int
    login: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    group_id: Optional[int] = None
    avatar_url: Optional[str] = None

class UserCreate(BaseModel):
    first_name: str
    last_name: str
    login: str
    password: str

class UserUpdate(BaseModel):
    first_name: str
    last_name: str

class ScheduleItem(BaseModel):
    id: int
    lesson_date: str
    start_time: str
    end_time: str
    subject: str
    teacher: Optional[str] = None
    room: Optional[str] = None
    group_id: int

def get_db_connection():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

UPLOAD_DIR = Path("avatars")
FILES_DIR = Path("files")
FILES_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/avatars", StaticFiles(directory="avatars"), name="avatars")
app.mount("/files", StaticFiles(directory="files"), name="files")

@app.get("/")
def read_root():
    return {"message": "API работает!"}

@app.post("/auth/login")
def login(user: UserLogin):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, login, first_name, last_name, group_id, avatar_url FROM users WHERE login = %s AND password_hash = %s",
        (user.login, user.password)
    )
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    if result:
        return dict(result)
    raise HTTPException(status_code=401, detail="Неверный логин или пароль")

@app.get("/users/{user_id}", response_model=User)
def get_user(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, login, first_name, last_name, group_id, avatar_url FROM users WHERE id = %s",
        (user_id,)
    )
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    if result:
        return dict(result)
    raise HTTPException(status_code=404, detail="Пользователь не найден")

@app.put("/users/{user_id}")
def update_user(user_id: int, user_data: UserUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET first_name = %s, last_name = %s WHERE id = %s",
            (user_data.first_name, user_data.last_name, user_id)
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.post("/users/{user_id}/avatar")
async def upload_avatar(user_id: int, file: UploadFile = File(...)):
    allowed_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    file_extension = Path(file.filename).suffix.lower() if file.filename else ""
    
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Только: {', '.join(allowed_extensions)}")
    
    filename = f"{user_id}{file_extension}"
    filepath = UPLOAD_DIR / filename
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    avatar_url = f"http://127.0.0.1:8000/avatars/{filename}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (avatar_url, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"success": True, "avatar_url": avatar_url}

@app.get("/schedule")
def get_schedule(group_id: int, start_date: date, end_date: date):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, lesson_date, start_time, end_time, subject, teacher, room, group_id
        FROM schedules
        WHERE group_id = %s AND lesson_date BETWEEN %s AND %s
        ORDER BY lesson_date, start_time
        """,
        (group_id, start_date, end_date)
    )
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [
        {
            **dict(row),
            'lesson_date': row['lesson_date'].isoformat() if row['lesson_date'] else None,
            'start_time': row['start_time'].isoformat() if row['start_time'] else None,
            'end_time': row['end_time'].isoformat() if row['end_time'] else None,
        }
        for row in results
    ]

@app.get("/chats/{chat_id}/messages")
def get_messages(chat_id: int, limit: int = 50):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT m.id, m.content, m.created_at, 
                   m.image_url, m.file_url, m.file_name, m.file_size,
                   u.id as sender_id, u.first_name, u.last_name, u.avatar_url
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.chat_id = %s
            ORDER BY m.created_at ASC
            LIMIT %s
            """,
            (chat_id, limit)
        )
        results = cursor.fetchall()
        
        messages = []
        for row in results:
            msg = dict(row)
            if msg.get('created_at'):
                msg['created_at'] = msg['created_at'].isoformat()
            msg['image_url'] = msg.get('image_url') or ''
            msg['file_url'] = msg.get('file_url') or ''
            msg['file_name'] = msg.get('file_name') or ''
            msg['file_size'] = msg.get('file_size') or 0
            messages.append(msg)
        
        return messages
    except Exception as e:
        return []
    finally:
        cursor.close()
        conn.close()

@app.post("/chats/{chat_id}/messages")
def send_message(chat_id: int, sender_id: int = Form(...), content: str = Form(...)):
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO messages (chat_id, sender_id, content, created_at) 
            VALUES (%s, %s, %s, NOW()) 
            RETURNING id, created_at
            """,
            (chat_id, sender_id, content.strip())
        )
        result = cursor.fetchone()
        conn.commit()
        
        return {
            "id": result['id'],
            "created_at": result['created_at'].isoformat(),
            "success": True
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@app.get("/chats/{chat_id}/info")
def get_chat_info(chat_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, type, image_url, group_id, created_at FROM chats WHERE id = %s", (chat_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    if result:
        return dict(result)
    raise HTTPException(status_code=404, detail="Чат не найден")

@app.get("/chats/{chat_id}/members")
def get_chat_members(chat_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT u.id, u.first_name, u.last_name, u.avatar_url, u.login
        FROM users u
        JOIN chat_members cm ON u.id = cm.user_id
        WHERE cm.chat_id = %s
        ORDER BY u.first_name, u.last_name
        """,
        (chat_id,)
    )
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(row) for row in results]

@app.put("/chats/{chat_id}/avatar")
async def update_chat_avatar(chat_id: int, file: UploadFile = File(...)):
    allowed_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    file_extension = Path(file.filename).suffix.lower() if file.filename else ""
    
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Только изображения")
    
    filename = f"chat_{chat_id}{file_extension}"
    filepath = UPLOAD_DIR / filename
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    avatar_url = f"http://127.0.0.1:8000/avatars/{filename}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE chats SET image_url = %s WHERE id = %s", (avatar_url, chat_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"success": True, "avatar_url": avatar_url}

@app.put("/chats/{chat_id}/notifications")
def toggle_notifications(chat_id: int, user_id: int = Query(...), enabled: bool = Query(...)):
    return {"success": True, "enabled": enabled}

@app.get("/chats/{chat_id}/unread")
def get_unread_count(chat_id: int, user_id: int = Query(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT COUNT(*) as count
        FROM messages m
        WHERE m.chat_id = %s 
        AND m.sender_id != %s
        AND m.created_at > COALESCE(
            (SELECT cm.last_read_at FROM chat_members cm WHERE cm.chat_id = %s AND cm.user_id = %s),
            '1970-01-01'::timestamp
        )
        """,
        (chat_id, user_id, chat_id, user_id)
    )
    
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    
    count = result['count'] if result else 0
    return {"unread_count": count}

@app.post("/chats/{chat_id}/mark-read")
def mark_as_read(chat_id: int, user_id: int = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM chat_members WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO chat_members (chat_id, user_id, last_read_at) VALUES (%s, %s, NOW())", (chat_id, user_id))
        else:
            cursor.execute("UPDATE chat_members SET last_read_at = NOW() WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
        
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/groups/{group_id}/users")
def get_group_users(group_id: int, current_user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT id, login, first_name, last_name, avatar_url
        FROM users
        WHERE group_id = %s AND id != %s
        ORDER BY first_name, last_name
        """,
        (group_id, current_user_id)
    )
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [dict(row) for row in results]

@app.post("/chats/private")
def create_private_chat(user1_id: int, user2_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            SELECT c.id FROM chats c
            JOIN chat_members cm1 ON c.id = cm1.chat_id AND cm1.user_id = %s
            JOIN chat_members cm2 ON c.id = cm2.chat_id AND cm2.user_id = %s
            WHERE c.type = 'private'
            """,
            (user1_id, user2_id)
        )
        existing_chat = cursor.fetchone()
        
        if existing_chat:
            return {"chat_id": existing_chat['id'], "created": False}
        
        cursor.execute(
            "SELECT first_name, last_name, avatar_url FROM users WHERE id = %s",
            (user2_id,)
        )
        user2_data = cursor.fetchone()
        
        full_name = f"{user2_data['first_name']} {user2_data['last_name']}".strip()
        if not full_name:
            full_name = "Личный чат"
        
        cursor.execute(
            """
            INSERT INTO chats (name, type, image_url, group_id) 
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (full_name, 'private', user2_data['avatar_url'], None)
        )
        chat_id = cursor.fetchone()['id']
        
        cursor.execute("INSERT INTO chat_members (chat_id, user_id) VALUES (%s, %s)", (chat_id, user1_id))
        cursor.execute("INSERT INTO chat_members (chat_id, user_id) VALUES (%s, %s)", (chat_id, user2_id))
        
        conn.commit()
        return {"chat_id": chat_id, "created": True}
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/chats/{user_id}")
def get_user_chats(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT c.id, c.name, c.type, c.image_url, c.group_id 
        FROM chats c 
        JOIN chat_members cm ON c.id = cm.chat_id 
        WHERE cm.user_id = %s
        ORDER BY c.created_at DESC
        """,
        (user_id,)
    )
    results = cursor.fetchall()
    
    chats = []
    for chat in results:
        chat_dict = dict(chat)
        
        if chat_dict['type'] == 'private':
            cursor.execute(
                """
                SELECT u.id, u.first_name, u.last_name, u.avatar_url
                FROM users u
                JOIN chat_members cm ON u.id = cm.user_id
                WHERE cm.chat_id = %s AND u.id != %s
                LIMIT 1
                """,
                (chat_dict['id'], user_id)
            )
            other_user = cursor.fetchone()
            
            if other_user:
                first = other_user['first_name'] or ''
                last = other_user['last_name'] or ''
                full_name = f"{first} {last}".strip()
                chat_dict['name'] = full_name if full_name else (other_user.get('login') or 'Личный чат')
                chat_dict['image_url'] = other_user['avatar_url']
        
        chats.append(chat_dict)
    
    cursor.close()
    conn.close()
    return chats

@app.get("/users/shared-chats")
def get_shared_chats(user1_id: int, user2_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id, c.name, c.type, c.image_url
        FROM chats c
        JOIN chat_members cm1 ON c.id = cm1.chat_id AND cm1.user_id = %s
        JOIN chat_members cm2 ON c.id = cm2.chat_id AND cm2.user_id = %s
        WHERE c.type = 'group'
        ORDER BY c.name
        """,
        (user1_id, user2_id)
    )
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(row) for row in results]

@app.post("/chats/{chat_id}/messages/image")
async def send_image_message(
    chat_id: int,
    sender_id: int = Form(...),
    image: UploadFile = File(...)
):
    allowed_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    file_extension = Path(image.filename).suffix.lower() if image.filename else ""
    
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Только изображения")
    
    filename = f"msg_{chat_id}_{sender_id}_{int(time.time())}{file_extension}"
    filepath = UPLOAD_DIR / filename
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(image.file, buffer)
    
    image_url = f"http://127.0.0.1:8000/avatars/{filename}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO messages (chat_id, sender_id, content, image_url) 
            VALUES (%s, %s, %s, %s) 
            RETURNING id, created_at
            """,
            (chat_id, sender_id, "", image_url)
        )
        result = cursor.fetchone()
        conn.commit()
        
        return {
            "id": result['id'],
            "created_at": result['created_at'].isoformat() if result['created_at'] else None,
            "image_url": image_url,
            "success": True
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.post("/chats/{chat_id}/messages/file")
async def send_file_message(
    chat_id: int,
    sender_id: int = Form(...),
    file: UploadFile = File(...),
    file_name: str = Form(...)
):
    timestamp = int(time.time())
    file_extension = Path(file.filename).suffix.lower() if file.filename else ""
    safe_filename = f"file_{chat_id}_{sender_id}_{timestamp}{file_extension}"
    filepath = FILES_DIR / safe_filename
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    file_url = f"http://127.0.0.1:8000/files/{safe_filename}"
    file_size = filepath.stat().st_size
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO messages (chat_id, sender_id, content, file_url, file_name, file_size) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            RETURNING id, created_at
            """,
            (chat_id, sender_id, "", file_url, file_name, file_size)
        )
        result = cursor.fetchone()
        conn.commit()
        
        return {
            "id": result['id'],
            "created_at": result['created_at'].isoformat() if result['created_at'] else None,
            "file_url": file_url,
            "file_name": file_name,
            "file_size": file_size,
            "success": True
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()