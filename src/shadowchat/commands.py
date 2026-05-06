import asyncio
import random
import time


def cmd_quit(args, ctx):
    ctx["stop_event"].set()


async def cmd_users_async(ctx):
    ctx["chat_history"].append(
        {
            "user": "## SYSTEM ##",
            "color": "blue",
            "text": "Scanning network...",
            "time": time.strftime("%H:%M"),
        }
    )
    ctx["seen_users"].clear()
    ctx["protocol"].send({"type": "ping_users", "user": ctx["user_profile"]["name"]})
    await asyncio.sleep(1.5)
    others = [u for u in ctx["seen_users"] if u != ctx["user_profile"]["name"]]
    msg = f"Online users: {', '.join(others)}" if others else "No one else is here"
    ctx["chat_history"].append(
        {
            "user": "## SYSTEM ##",
            "color": "blue",
            "text": msg,
            "time": time.strftime("%H:%M"),
        }
    )


def cmd_rename(args: str, context: dict):
    new_name = args.strip()
    if not new_name:
        return
    old_name = context["user_profile"]["name"]
    context["user_profile"]["name"] = new_name
    if old_name in context["seen_users"]:
        context["seen_users"].remove(old_name)
    context["seen_users"].add(new_name)
    context["chat_history"].append(
        {
            "user": "## SYSTEM ##",
            "color": "yellow",
            "text": f"{old_name} is now {new_name}",
            "time": time.strftime("%H:%M"),
        }
    )
    context["protocol"].send(
        {
            "type": "rename",
            "user": new_name,
            "old_name": old_name,
            "new_name": new_name,
        }
    )


def cmd_help(args: str, context: dict):
    lines = []
    registry = context["command_registry"]
    for key, (_, desc) in registry.items():
        lines.append(f"{key}: {desc}")

    command_list = ", ".join(lines)

    context["chat_history"].append(
        {
            "user": "## SYSTEM ##",
            "color": "yellow",
            "text": f"Commands: {command_list}",
            "time": time.strftime("%H:%M"),
        }
    )


def cmd_askai(args: str, context: dict):
    if not args.strip():
        context["chat_history"].append(
            {
                "user": "## SYSTEM ##",
                "color": "red",
                "text": "You must ask a question! Usage: /askai <question>",
                "time": time.strftime("%H:%M"),
            }
        )
        return

    protocol = context["protocol"]
    current_time = time.strftime("%H:%M")

    protocol.send(
        {
            "type": "chat",
            "user": context["user_profile"]["name"],
            "color": context["user_profile"]["color"],
            "text": f"{args}",
            "time": current_time,
        }
    )

    protocol.send(
        {
            "type": "chat",
            "user": "SuperAI",
            "color": "magenta",
            "text": random.choice(context["ai_responses"]),
            "time": current_time,
        }
    )


def build_command_registry():
    return {
        "/q": (cmd_quit, "Quit shadowchat"),
        "/users": (
            lambda a, c: asyncio.create_task(cmd_users_async(c)),
            "List users currently online",
        ),
        "/rename": (cmd_rename, "Change your name"),
        "/help": (cmd_help, "Show this help"),
        "/askai": (cmd_askai, "/askai <question>"),
    }
