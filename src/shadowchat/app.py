import asyncio
import curses
import time

from shadowchat.commands import build_command_registry
from shadowchat.network import MulticastProtocol, create_multicast_socket
from shadowchat.ui import draw_screen, init_colors, screen_lock


async def input_handler(
    stdscr,
    protocol,
    user_profile,
    chat_history,
    input_buf_ref,
    stop_event,
    seen_users,
    command_registry,
    ai_responses,
):
    while not stop_event.is_set():
        async with screen_lock:
            ch = stdscr.getch()

        if ch == -1:
            await asyncio.sleep(0.02)
            continue

        if ch in (10, 13, curses.KEY_ENTER):
            cmd_text = input_buf_ref[0].strip()
            if cmd_text.startswith("/"):
                parts = cmd_text.split(" ", 1)
                cmd = parts[0].lower()
                if cmd in command_registry:
                    context = {
                        "stop_event": stop_event,
                        "chat_history": chat_history,
                        "seen_users": seen_users,
                        "user_profile": user_profile,
                        "protocol": protocol,
                        "command_registry": command_registry,
                        "ai_responses": ai_responses,
                    }
                    command_registry[cmd][0](
                        parts[1] if len(parts) > 1 else "", context
                    )
                else:
                    chat_history.append(
                        {
                            "user": "## SYSTEM ##",
                            "color": "red",
                            "text": f"Unknown command: {cmd}",
                            "time": time.strftime("%H:%M"),
                        }
                    )
            elif cmd_text:
                protocol.send(
                    {
                        "type": "chat",
                        "user": user_profile["name"],
                        "color": user_profile["color"],
                        "text": cmd_text,
                        "time": time.strftime("%H:%M"),
                    }
                )
            input_buf_ref[0] = ""

        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            input_buf_ref[0] = input_buf_ref[0][:-1]
        elif ch == curses.KEY_RESIZE:
            async with screen_lock:
                curses.update_lines_cols()
        elif 32 <= ch <= 126:
            input_buf_ref[0] += chr(ch)


async def ui_loop(
    stdscr,
    user_profile,
    chat_history,
    input_buf_ref,
    msg_queue,
    stop_event,
    protocol,
    seen_users,
):
    while not stop_event.is_set():
        while not msg_queue.empty():
            msg = msg_queue.get_nowait()
            m_type, sender = msg.get("type", "chat"), msg.get("user", "Unknown")

            if sender == user_profile["name"] and m_type != "chat":
                continue

            if m_type == "chat":
                chat_history.append(msg)

            elif m_type == "join":
                seen_users.add(sender)
                protocol.send({"type": "presence", "user": user_profile["name"]})
                chat_history.append(
                    {
                        "user": "-- SHADOW --",
                        "color": "blue",
                        "text": f"{sender} joined.",
                        "time": time.strftime("%H:%M"),
                    }
                )

            elif m_type in ("presence", "ping_users"):
                seen_users.add(sender)
                if m_type == "ping_users":
                    protocol.send({"type": "presence", "user": user_profile["name"]})

            elif m_type == "rename":
                old, new = msg.get("old_name"), msg.get("new_name")
                if old in seen_users:
                    seen_users.remove(old)
                seen_users.add(new)
                chat_history.append(
                    {
                        "user": "## SYSTEM ##",
                        "color": "yellow",
                        "text": f"{old} is now {new}",
                        "time": time.strftime("%H:%M"),
                    }
                )

        await draw_screen(stdscr, user_profile["name"], chat_history, input_buf_ref[0])
        await asyncio.sleep(0.05)


async def welcome_sequence(username, protocol, chat_history, seen_users):
    protocol.send({"type": "join", "user": username})
    await asyncio.sleep(1.5)
    others = [u for u in seen_users if u != username]
    users_str = ", ".join(others) if others else "No one else is here yet."
    chat_history.append(
        {
            "user": "-- SHADOW --",
            "color": "blue",
            "text": f"Welcome! Online: {users_str}, try /help!",
            "time": time.strftime("%H:%M"),
        }
    )


async def run_chat_async(stdscr, username, color, ai_responses):
    init_colors()
    stdscr.nodelay(True)
    curses.curs_set(0)

    msg_queue = asyncio.Queue()
    chat_history, input_buf_ref, seen_users = [], [""], set()
    stop_event = asyncio.Event()
    user_profile = {"name": username, "color": color}
    command_registry = build_command_registry()

    raw_sock = create_multicast_socket()
    loop = asyncio.get_running_loop()
    _, protocol = await loop.create_datagram_endpoint(
        lambda: MulticastProtocol(msg_queue), sock=raw_sock
    )

    asyncio.create_task(
        welcome_sequence(username, protocol, chat_history, seen_users)
    )

    try:
        await asyncio.gather(
            ui_loop(
                stdscr,
                user_profile,
                chat_history,
                input_buf_ref,
                msg_queue,
                stop_event,
                protocol,
                seen_users,
            ),
            input_handler(
                stdscr,
                protocol,
                user_profile,
                chat_history,
                input_buf_ref,
                stop_event,
                seen_users,
                command_registry,
                ai_responses,
            ),
        )
    finally:
        if protocol.transport:
            protocol.transport.close()


def run_chat(stdscr, username, color, ai_responses):
    asyncio.run(run_chat_async(stdscr, username, color, ai_responses))
