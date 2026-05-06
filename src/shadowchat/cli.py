import asyncio
import curses
import os
import sys

from shadowchat.app import run_chat
from shadowchat.constants import COLOR_MAP
from shadowchat.resources import load_ai_responses


def main():
    if sys.platform == "win32":
        os.system("")
    print("=" * 40 + "\n      Welcome to SHADOW-CHAT\n" + "=" * 40)

    username = input("Enter your Username: ").strip() or "Anonymous"

    print("\nAvailable colors:")
    print("[1] \033[36mcyan\033[0m")
    print("[2] \033[32mgreen\033[0m")
    print("[3] \033[33myellow\033[0m")
    print("[4] \033[31mred\033[0m")
    print("[5] \033[35mmagenta\033[0m")
    print("[6] \033[37mwhite\033[0m")

    color_input = input("\nChoose a color: ").strip().lower()
    number_map = {
        "1": "cyan",
        "2": "green",
        "3": "yellow",
        "4": "red",
        "5": "magenta",
        "6": "white",
    }
    color = number_map.get(
        color_input, color_input if color_input in COLOR_MAP else "white"
    )

    ai_responses = load_ai_responses()

    if sys.platform == "darwin":
        try:
            from rubicon.objc.eventloop import EventLoopPolicy

            asyncio.set_event_loop_policy(EventLoopPolicy())
        except ImportError:
            pass

    curses.wrapper(run_chat, username, color, ai_responses)
