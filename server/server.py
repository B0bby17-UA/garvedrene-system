import asyncio
import copy
import json
import os
import random
import re
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from database import init_db, get_db
from models import User, Character, Campaign, CampaignCharacter, ChatMessage, generate_uuid
from auth import hash_password, verify_password, create_access_token, get_current_user, get_optional_user

app = FastAPI(title="Garvedrene System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ── Init DB ────────────────────────────────────────────────────────
init_db()

# ── Dice Engine ────────────────────────────────────────────────────
def rolar_formula(formula: str) -> tuple[int, str]:
    try:
        f = formula.lower().replace(" ", "")
        partes = re.findall(r'([+-]?\d*d\d+|[+-]?\d+)', f)
        total, detalhes = 0, []
        for p in partes:
            if 'd' in p:
                m = re.match(r'([+-]?)(\d*)d(\d+)', p)
                if not m: continue
                sinal = -1 if m.group(1) == '-' else 1
                qtd = int(m.group(2)) if m.group(2) else 1
                rolls = [random.randint(1, int(m.group(3))) for _ in range(qtd)]
                total += sum(rolls) * sinal
                detalhes.append(f"[{'+'.join(map(str, rolls))}]")
            else:
                total += int(p)
                detalhes.append(p)
        return total, " + ".join(detalhes)
    except Exception:
        return 0, "Erro"


# ── Auth Schemas ───────────────────────────────────────────────────
class RegisterBody(BaseModel):
    email: str
    username: str
    password: str

class LoginBody(BaseModel):
    email: str
    password: str

# ── Auth Routes ────────────────────────────────────────────────────
@app.post("/api/auth/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email já cadastrado")
    user = User(
        email=body.email,
        username=body.username,
        password_hash=hash_password(body.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.id})
    return {"token": token, "user": {"id": user.id, "email": user.email, "username": user.username}}


@app.post("/api/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email ou senha inválidos")
    token = create_access_token({"sub": user.id})
    return {"token": token, "user": {"id": user.id, "email": user.email, "username": user.username}}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "username": user.username}


# ── Character Routes ───────────────────────────────────────────────
class CharCreate(BaseModel):
    name: str
    level: int = 1
    classe: str = "Bruxo"
    data: dict = {}

class CharUpdate(BaseModel):
    name: str = None
    level: int = None
    classe: str = None
    data: dict = None


@app.get("/api/characters")
def list_characters(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chars = db.query(Character).filter(Character.user_id == user.id).all()
    return {"characters": [{
        "id": c.id, "name": c.name, "level": c.level,
        "classe": c.classe, "data": c.data,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat()
    } for c in chars]}


@app.post("/api/characters")
def create_character(body: CharCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    default_data = {
        "atributos": {a: 8 for a in ["Força", "Agilidade", "Vigor", "Inteligência", "Espírito"]},
        "status": {"hp_at": 20, "hp_mx": 20, "mp_at": 20, "mp_mx": 20},
        "pericias": {}, "salvaguardas": {},
        "inventario": [], "habilidades": [], "magias": [],
        "elemento": "IGNIS", "caminho": "Fogo", "origem": "", "ca": "10",
        "espaco_atual": "0", "espaco_max": "10"
    }
    merged = {**default_data, **(body.data or {})}
    merged["icone"] = body.name[0].upper() if body.name else "?"
    char = Character(
        user_id=user.id, name=body.name,
        level=body.level, classe=body.classe, data=merged
    )
    db.add(char)
    db.commit()
    db.refresh(char)
    return {"id": char.id, "name": char.name, "level": char.level, "classe": char.classe, "data": char.data}


@app.put("/api/characters/{char_id}")
def update_character(char_id: str, body: CharUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    char = db.query(Character).filter(Character.id == char_id, Character.user_id == user.id).first()
    if not char:
        raise HTTPException(404, "Personagem não encontrado")
    if body.name is not None: char.name = body.name
    if body.level is not None: char.level = body.level
    if body.classe is not None: char.classe = body.classe
    if body.data is not None:
        existing = dict(char.data or {})
        existing.update(body.data)
        existing["icone"] = char.name[0].upper() if char.name else "?"
        char.data = existing
        flag_modified(char, "data")
    db.commit()
    db.refresh(char)
    return {"id": char.id, "name": char.name, "level": char.level, "classe": char.classe, "data": char.data}


@app.delete("/api/characters/{char_id}")
def delete_character(char_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    char = db.query(Character).filter(Character.id == char_id, Character.user_id == user.id).first()
    if not char:
        raise HTTPException(404, "Personagem não encontrado")
    db.delete(char)
    db.commit()
    return {"status": "ok"}


# ── Campaign Routes ────────────────────────────────────────────────
class CampaignCreate(BaseModel):
    name: str


@app.get("/api/campaigns")
def list_campaigns(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    as_master = db.query(Campaign).filter(Campaign.master_id == user.id).all()
    as_player_links = db.query(CampaignCharacter).filter(
        CampaignCharacter.character_id.in_(
            db.query(Character.id).filter(Character.user_id == user.id)
        )
    ).all()
    player_campaign_ids = [link.campaign_id for link in as_player_links]
    as_player = db.query(Campaign).filter(Campaign.id.in_(player_campaign_ids)).all() if player_campaign_ids else []

    def fmt(c):
        return {
            "id": c.id, "name": c.name, "invite_code": c.invite_code,
            "master_id": c.master_id, "created_at": c.created_at.isoformat(),
            "character_count": db.query(CampaignCharacter).filter(CampaignCharacter.campaign_id == c.id).count()
        }

    return {
        "as_master": [fmt(c) for c in as_master],
        "as_player": [fmt(c) for c in as_player]
    }


@app.post("/api/campaigns")
def create_campaign(body: CampaignCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = Campaign(name=body.name, master_id=user.id)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return {
        "id": campaign.id, "name": campaign.name,
        "invite_code": campaign.invite_code,
        "master_id": campaign.master_id
    }


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campanha não encontrada")
    is_master = campaign.master_id == user.id
    if not is_master:
        has_char = db.query(CampaignCharacter).join(Character).filter(
            CampaignCharacter.campaign_id == campaign_id,
            Character.user_id == user.id
        ).first()
        if not has_char:
            raise HTTPException(403, "Você não faz parte desta campanha")
    chars = db.query(CampaignCharacter).filter(CampaignCharacter.campaign_id == campaign_id).all()
    if not is_master:
        # Players only see their own character
        chars = [link for link in chars if link.character.user_id == user.id]
    character_list = []
    for link in chars:
        c = link.character
        owner = db.query(User).filter(User.id == c.user_id).first()
        character_list.append({
            "id": c.id, "name": c.name, "level": c.level,
            "classe": c.classe, "data": c.data,
            "campaign_data": link.campaign_data or {},
            "user_id": c.user_id, "owner_name": owner.username if owner else "?"
        })
    recent_msgs = db.query(ChatMessage).filter(
        ChatMessage.campaign_id == campaign_id
    ).order_by(ChatMessage.created_at.desc()).limit(50).all()
    recent_msgs.reverse()
    # Filter tell messages: only master sees them
    filtered_msgs = [m for m in recent_msgs if not (
        m.message_type == "tell" and m.target_user_id != user.id
    )]
    return {
        "id": campaign.id, "name": campaign.name, "invite_code": campaign.invite_code,
        "master_id": campaign.master_id, "is_master": is_master,
        "characters": character_list, "npcs": campaign.npcs or {},
        "messages": [{
            "id": m.id, "author_name": m.author_name, "content": m.content,
            "message_type": m.message_type,
            "created_at": m.created_at.isoformat()
        } for m in filtered_msgs]
    }


@app.delete("/api/campaigns/{campaign_id}")
def delete_campaign(campaign_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.master_id == user.id).first()
    if not campaign:
        raise HTTPException(404, "Campanha não encontrada")
    db.delete(campaign)
    db.commit()
    return {"status": "ok"}


# ── NPC Routes ──────────────────────────────────────────────────────
@app.post("/api/campaigns/{campaign_id}/npcs")
def create_npc(campaign_id: str, body: dict = Body(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign or campaign.master_id != user.id:
        raise HTTPException(403, "Apenas o mestre pode gerenciar NPCs")
    npcs = dict(campaign.npcs or {})
    npc_id = generate_uuid()
    npcs[npc_id] = {
        "id": npc_id,
        "name": body.get("name", "NPC"),
        "icone": body.get("icone", "N"),
        "data": body.get("data", {
            "status": {"hp_at": 10, "hp_mx": 10, "mp_at": 5, "mp_mx": 5},
            "atributos": {"Força": 10, "Agilidade": 10, "Vigor": 10, "Inteligência": 10, "Espírito": 10},
            "pericias": {}, "inventario": [], "habilidades": [], "magias": []
        })
    }
    campaign.npcs = npcs
    flag_modified(campaign, "npcs")
    db.commit()
    return npcs[npc_id]


@app.put("/api/campaigns/{campaign_id}/npcs/{npc_id}")
def update_npc(campaign_id: str, npc_id: str, body: dict = Body(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign or campaign.master_id != user.id:
        raise HTTPException(403, "Apenas o mestre pode gerenciar NPCs")
    npcs_data = dict(campaign.npcs or {})
    if npc_id not in npcs_data:
        raise HTTPException(404, "NPC não encontrado")
    # body is the full dados object from the sheet editor
    # Save everything into npcs[npc_id].data, extract name/icone for top-level
    npcs_data[npc_id]["data"] = body
    npcs_data[npc_id]["name"] = body.get("nome", npcs_data[npc_id].get("name", "NPC"))
    npcs_data[npc_id]["icone"] = body.get("icone", npcs_data[npc_id].get("icone", "N"))
    campaign.npcs = npcs_data
    flag_modified(campaign, "npcs")
    db.commit()
    return npcs_data[npc_id]


@app.delete("/api/campaigns/{campaign_id}/npcs/{npc_id}")
def delete_npc(campaign_id: str, npc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign or campaign.master_id != user.id:
        raise HTTPException(403, "Apenas o mestre pode gerenciar NPCs")
    npcs = dict(campaign.npcs or {})
    if npc_id not in npcs:
        raise HTTPException(404, "NPC não encontrado")
    del npcs[npc_id]
    campaign.npcs = npcs
    flag_modified(campaign, "npcs")
    db.commit()
    return {"status": "ok"}


# ── Invite Routes ──────────────────────────────────────────────────
@app.get("/api/invite/{invite_code}")
def get_invite(invite_code: str, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.invite_code == invite_code).first()
    if not campaign:
        raise HTTPException(404, "Convite inválido")
    master = db.query(User).filter(User.id == campaign.master_id).first()
    char_count = db.query(CampaignCharacter).filter(CampaignCharacter.campaign_id == campaign.id).count()
    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "master_name": master.username if master else "?",
        "character_count": char_count
    }


class JoinCampaignBody(BaseModel):
    character_id: str


@app.post("/api/invite/{invite_code}/join")
def join_campaign(invite_code: str, body: JoinCampaignBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.invite_code == invite_code).first()
    if not campaign:
        raise HTTPException(404, "Convite inválido")
    char = db.query(Character).filter(Character.id == body.character_id, Character.user_id == user.id).first()
    if not char:
        raise HTTPException(404, "Personagem não encontrado")
    existing = db.query(CampaignCharacter).filter(
        CampaignCharacter.campaign_id == campaign.id,
        CampaignCharacter.character_id == char.id
    ).first()
    if existing:
        raise HTTPException(400, "Este personagem já está na campanha")
    link = CampaignCharacter(campaign_id=campaign.id, character_id=char.id, campaign_data=copy.deepcopy(char.data or {}))
    db.add(link)
    db.commit()
    return {"status": "ok", "campaign_id": campaign.id}


# ── REST: Master updates campaign character data ──────────────
@app.put("/api/campaigns/{campaign_id}/characters/{character_id}")
def update_campaign_character(campaign_id: str, character_id: str, body: dict = Body(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campanha não encontrada")
    if campaign.master_id != user.id:
        raise HTTPException(403, "Apenas o mestre pode editar fichas na campanha")
    link = db.query(CampaignCharacter).filter(
        CampaignCharacter.campaign_id == campaign_id,
        CampaignCharacter.character_id == character_id
    ).first()
    if not link:
        raise HTTPException(404, "Personagem não encontrado nesta campanha")
    existing = dict(link.campaign_data or {})
    for key, val in body.items():
        if isinstance(val, dict):
            sub = existing.get(key, {})
            if isinstance(sub, dict):
                sub.update(val)
                existing[key] = sub
            else:
                existing[key] = val
        else:
            existing[key] = val
    link.campaign_data = existing
    flag_modified(link, "campaign_data")
    db.commit()
    return {"status": "ok"}


# ── Campaign WebSocket ─────────────────────────────────────────────
class CampaignManager:
    def __init__(self):
        self.connections: dict[str, dict] = {}  # campaign_id -> {user_id: {"ws": WebSocket, "user": User, "character": Character, "campaign_data": dict}}

    def add(self, campaign_id: str, user_id: str, ws: WebSocket, user, character, campaign_data: dict = None):
        if campaign_id not in self.connections:
            self.connections[campaign_id] = {}
        self.connections[campaign_id][user_id] = {"ws": ws, "user": user, "character": character, "campaign_data": campaign_data or {}}

    def remove(self, campaign_id: str, user_id: str):
        if campaign_id in self.connections and user_id in self.connections[campaign_id]:
            del self.connections[campaign_id][user_id]
            if not self.connections[campaign_id]:
                del self.connections[campaign_id]

    async def broadcast(self, campaign_id: str, message: dict, exclude: str = None):
        if campaign_id not in self.connections:
            return
        dead = []
        for uid, info in self.connections[campaign_id].items():
            if uid == exclude:
                continue
            try:
                await info["ws"].send_json(message)
            except:
                dead.append(uid)
        for uid in dead:
            self.remove(campaign_id, uid)

    async def send_to(self, campaign_id: str, user_id: str, message: dict):
        if campaign_id in self.connections and user_id in self.connections[campaign_id]:
            try:
                await self.connections[campaign_id][user_id]["ws"].send_json(message)
            except:
                self.remove(campaign_id, user_id)

    def get_participants(self, campaign_id: str):
        if campaign_id not in self.connections:
            return []
        return [
            {"user_id": uid, "username": info["user"].username,
             "character": {
                 "id": info["character"].id, "name": info["character"].name,
                 "level": info["character"].level, "classe": info["character"].classe,
                 "data": info["character"].data
             } if info["character"] is not None else None,
             "campaign_data": info.get("campaign_data", {})}
            for uid, info in self.connections[campaign_id].items()
        ]


campaign_manager = CampaignManager()


@app.websocket("/ws/campaign/{campaign_id}")
async def campaign_websocket(websocket: WebSocket, campaign_id: str, token: str = Query(""), db: Session = Depends(get_db)):
    # Validate token
    from auth import decode_token, JWTError
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    # Check campaign membership
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        await websocket.close(code=4004)
        return

    is_master = campaign.master_id == user.id
    char_link = None
    character = None

    if not is_master:
        char_link = db.query(CampaignCharacter).join(Character).filter(
            CampaignCharacter.campaign_id == campaign_id,
            Character.user_id == user.id
        ).first()
        if not char_link:
            await websocket.close(code=4003)
            return
        character = char_link.character
    else:
        # Master might not have a character in campaign
        char_link = db.query(CampaignCharacter).join(Character).filter(
            CampaignCharacter.campaign_id == campaign_id,
            Character.user_id == user.id
        ).first()
        character = char_link.character if char_link else None

    await websocket.accept()

    # Resolve campaign_data from CampaignCharacter link
    campaign_data = char_link.campaign_data if char_link else {}

    campaign_manager.add(campaign_id, user.id, websocket, user, character, campaign_data)

    # Send participants to THIS client (not just others — fixes missing data bug)
    try:
        await websocket.send_json({
            "tipo": "participants",
            "participants": campaign_manager.get_participants(campaign_id)
        })
    except:
        pass

    # Notify others
    await campaign_manager.broadcast(campaign_id, {
        "tipo": "participants",
        "participants": campaign_manager.get_participants(campaign_id)
    }, exclude=user.id)

    # Send join message — only to participants list, NOT chat
    await campaign_manager.broadcast(campaign_id, {
        "tipo": "participants",
        "participants": campaign_manager.get_participants(campaign_id)
    }, exclude=user.id)

    # Heartbeat / message loop
    last_heartbeat = datetime.now(timezone.utc)
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send heartbeat ping
                try:
                    await websocket.send_json({"tipo": "ping"})
                    continue
                except:
                    break

            if raw == "__ping__":
                last_heartbeat = datetime.now(timezone.utc)
                continue

            msg = json.loads(raw)
            msg_type = msg.get("tipo", "")

            if msg_type == "chat":
                content = msg.get("conteudo", "")
                author = character.name if character else f"Mestre {user.username}"

                # /tell Mestre — private message only master sees
                tl = content.strip().lower()
                if tl.startswith("/tell mestre"):
                    tell_content = content.split(None, 2)
                    if len(tell_content) >= 3:
                        actual_msg = tell_content[2]
                        tell_author = f"📩 {author} → Mestre"
                        tell_entry = ChatMessage(
                            campaign_id=campaign_id, user_id=user.id,
                            character_id=character.id if character else None,
                            author_name=tell_author, content=actual_msg,
                            message_type="tell", target_user_id=campaign.master_id
                        )
                        db.add(tell_entry)
                        db.commit()
                        await campaign_manager.send_to(campaign_id, campaign.master_id, {
                            "tipo": "chat",
                            "author_name": tell_author,
                            "content": actual_msg,
                            "message_type": "tell",
                            "created_at": tell_entry.created_at.isoformat()
                        })
                        continue

                chat_msg = ChatMessage(
                    campaign_id=campaign_id, user_id=user.id,
                    character_id=character.id if character else None,
                    author_name=author, content=content, message_type="chat"
                )
                db.add(chat_msg)
                db.commit()
                await campaign_manager.broadcast(campaign_id, {
                    "tipo": "chat",
                    "author_name": author,
                    "content": content,
                    "message_type": "chat",
                    "created_at": chat_msg.created_at.isoformat()
                })

            elif msg_type == "roll":
                formula = msg.get("formula", "1d20")
                res, det = rolar_formula(formula)
                author = character.name if character else f"Mestre {user.username}"
                roll_msg = ChatMessage(
                    campaign_id=campaign_id, user_id=user.id,
                    character_id=character.id if character else None,
                    author_name=author, content=f"🎲 {formula} = {res} ({det})",
                    message_type="roll"
                )
                db.add(roll_msg)
                db.commit()
                await campaign_manager.broadcast(campaign_id, {
                    "tipo": "roll",
                    "author_name": author,
                    "formula": formula,
                    "resultado": res,
                    "detalhes": det,
                    "created_at": roll_msg.created_at.isoformat()
                })

            elif msg_type == "npc_roll":
                if is_master:
                    formula = msg.get("formula", "1d20")
                    npc_name = msg.get("npc_name", "NPC")
                    res, det = rolar_formula(formula)
                    roll_msg = ChatMessage(
                        campaign_id=campaign_id, user_id=user.id,
                        character_id=None, author_name=f"🗿 {npc_name}",
                        content=f"🎲 {formula} = {res} ({det})",
                        message_type="roll"
                    )
                    db.add(roll_msg)
                    db.commit()
                    await campaign_manager.broadcast(campaign_id, {
                        "tipo": "roll",
                        "author_name": f"🗿 {npc_name}",
                        "formula": formula,
                        "resultado": res,
                        "detalhes": det,
                        "created_at": roll_msg.created_at.isoformat()
                    })

            elif msg_type == "ficha_update":
                # Player updates their own sheet — save to both base data AND campaign_data
                if character and char_link:
                    new_data = msg.get("dados", {})
                    # Update base character
                    character.data = new_data
                    flag_modified(character, "data")
                    character.name = new_data.get("nome", character.name)
                    # Update campaign instance data (deep copy)
                    char_link.campaign_data = copy.deepcopy(new_data)
                    flag_modified(char_link, "campaign_data")
                    db.commit()
                    await campaign_manager.broadcast(campaign_id, {
                        "tipo": "ficha_atualizada",
                        "character_id": character.id,
                        "name": character.name,
                        "data": character.data,
                        "campaign_data": char_link.campaign_data
                    })

            elif msg_type == "mestre_ficha_update":
                if is_master:
                    target_char_id = msg.get("character_id")
                    updates = msg.get("dados", {})
                    target_char = db.query(Character).filter(Character.id == target_char_id).first()
                    if target_char:
                        # Find the campaign-specific link
                        link = db.query(CampaignCharacter).filter(
                            CampaignCharacter.campaign_id == campaign_id,
                            CampaignCharacter.character_id == target_char_id
                        ).first()
                        if link:
                            # Update ONLY campaign_data, NOT base character data
                            cdata = copy.deepcopy(link.campaign_data or {})
                            # Deep merge updates into campaign_data
                            for key, val in updates.items():
                                if isinstance(val, dict):
                                    existing_sub = cdata.get(key, {})
                                    if isinstance(existing_sub, dict):
                                        existing_sub.update(val)
                                        cdata[key] = existing_sub
                                    else:
                                        cdata[key] = val
                                else:
                                    cdata[key] = val
                            link.campaign_data = cdata
                            flag_modified(link, "campaign_data")
                            db.commit()
                            # Also update in-memory connection cache
                            if campaign_id in campaign_manager.connections and target_char.user_id in campaign_manager.connections[campaign_id]:
                                campaign_manager.connections[campaign_id][target_char.user_id]["campaign_data"] = cdata
                            # Notify the player
                            owner_id = target_char.user_id
                            await campaign_manager.send_to(campaign_id, owner_id, {
                                "tipo": "ficha_mestre_alterou",
                                "character_id": target_char_id,
                                "dados": updates
                            })
                            await campaign_manager.broadcast(campaign_id, {
                                "tipo": "ficha_atualizada",
                                "character_id": target_char.id,
                                "name": target_char.name,
                                "data": target_char.data,
                                "campaign_data": cdata
                            })

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        campaign_manager.remove(campaign_id, user.id)
        await campaign_manager.broadcast(campaign_id, {
            "tipo": "participants",
            "participants": campaign_manager.get_participants(campaign_id)
        })


# ── Dynamic Routes ────────────────────────────────────────────
@app.get("/campanha/{campaign_id}")
async def serve_campaign(campaign_id: str):
    fp = os.path.join(STATIC_DIR, "campaign.html")
    if os.path.exists(fp):
        return HTMLResponse(open(fp, encoding="utf-8").read())
    return {"error": "not found"}


@app.get("/agente/{character_id}")
async def serve_character(character_id: str):
    fp = os.path.join(STATIC_DIR, "character.html")
    if os.path.exists(fp):
        return HTMLResponse(open(fp, encoding="utf-8").read())
    return {"error": "not found"}


@app.get("/campanha/{campaign_id}/agente/{character_id}")
async def serve_campaign_agent(campaign_id: str, character_id: str):
    fp = os.path.join(STATIC_DIR, "campanha_agente.html")
    if os.path.exists(fp):
        return HTMLResponse(open(fp, encoding="utf-8").read())
    return {"error": "not found"}


@app.get("/campanha/{campaign_id}/npc/{npc_id}")
async def serve_campaign_npc(campaign_id: str, npc_id: str):
    fp = os.path.join(STATIC_DIR, "campanha_agente.html")
    if os.path.exists(fp):
        return HTMLResponse(open(fp, encoding="utf-8").read())
    return {"error": "not found"}


# ── Static Files & Catch-all ──────────────────────────────────
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

HTML_FILES = {
    "/": "index.html",
    "/dashboard": "dashboard.html",
    "/entrar": "join.html",
}


@app.get("/{path:path}")
async def serve_frontend(path: str):
    for route, file in HTML_FILES.items():
        if route == f"/{path}" or (route == "/" and path == ""):
            fp = os.path.join(STATIC_DIR, file.lstrip("/"))
            if os.path.exists(fp):
                return HTMLResponse(open(fp, encoding="utf-8").read())
    fp = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(fp):
        return HTMLResponse(open(fp, encoding="utf-8").read())
    return {"error": "not found"}


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5555"))
    print("--- Garvedrene System Server ---")
    print(f"http://localhost:{port}")
    uvicorn.run(app, host=host, port=port)
