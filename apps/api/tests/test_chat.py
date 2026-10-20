"""Chat: private messages and rooms, persisted with unread state."""

from soulsick.slsk.engine import ChatEvent
from test_flow import ctx  # noqa: F401


async def test_private_messages_and_unread(ctx):  # noqa: F811
    client, core, engine, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    await engine.on_chat(ChatEvent("private", "alice", "alice", "salut, t'as le FLAC ?", 1_700_000_000))
    over = (await client.get("/api/chat")).json()
    assert over["unread_private"] == 1
    conv = over["conversations"][0]
    assert (conv["kind"], conv["target"], conv["unread"]) == ("private", "alice", 1)
    assert (await client.get("/api/status")).json()["chat_unread"] == 1

    r = await client.post("/api/chat/send", json={"kind": "private", "target": "alice", "text": "oui, je te l'envoie"})
    assert r.status_code == 200, r.text
    assert engine.sent == [("private", "alice", "oui, je te l'envoie")]
    msgs = (await client.get("/api/chat/messages", params={"kind": "private", "target": "alice"})).json()
    assert [m["outgoing"] for m in msgs] == [False, True]

    await client.post("/api/chat/read", json={"kind": "private", "target": "alice"})
    assert (await client.get("/api/chat")).json()["unread_private"] == 0

    assert (await client.post("/api/chat/forget", json={"kind": "private", "target": "alice"})).json()["removed"] == 2
    assert (await client.get("/api/chat")).json()["conversations"] == []


async def test_rooms_join_send_leave(ctx):  # noqa: F811
    client, core, engine, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    assert (await client.get("/api/chat/rooms")).json()[0]["name"] == "indie"
    assert (await client.post("/api/chat/rooms/join", json={"room": "indie"})).status_code == 200
    assert engine.joined == {"indie"}
    assert await core.chat.joined_rooms() == ["indie"]

    await client.post("/api/chat/send", json={"kind": "room", "target": "indie", "text": "hello"})
    await engine.on_chat(ChatEvent("room", "indie", "bob", "yo", 0))
    msgs = (await client.get("/api/chat/messages", params={"kind": "room", "target": "indie"})).json()
    assert [(m["username"], m["outgoing"]) for m in msgs][-2:] == [(core.engine.config.username, True), ("bob", False)]
    # Room messages don't count in the private unread badge
    assert (await client.get("/api/chat")).json()["unread_private"] == 0

    await client.post("/api/chat/rooms/leave", json={"room": "indie"})
    assert await core.chat.joined_rooms() == []
    assert all(c["kind"] != "room" for c in (await client.get("/api/chat")).json()["conversations"])
