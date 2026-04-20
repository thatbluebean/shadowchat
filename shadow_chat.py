import curses
import socket
import struct
import json
import textwrap
import time
import sys
import asyncio
from pathlib import Path

from desktop_notifier import DesktopNotifier, ReplyField, Sound

# --- Network Configuration ---
MCAST_GRP = '224.1.1.1'
MCAST_PORT = 5007

# Map user color choices to curses color pairs
COLOR_MAP = {
    'cyan': 1, 'green': 2, 'yellow': 3,
    'red': 4, 'magenta': 5, 'white': 6
}

PING_SOUND = Sound(path=Path("ping.mp3").resolve())


# ---------------------------------------------------------------------------
# Asyncio UDP Protocol
# ---------------------------------------------------------------------------

class MulticastProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP datagram protocol for multicast send/receive."""

    def __init__(self, msg_queue: asyncio.Queue):
        self._queue = msg_queue
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode('utf-8'))
            self._queue.put_nowait(msg)
        except Exception:
            pass  # Silently drop malformed packets

    def error_received(self, exc: Exception):
        pass  # Keep running on transient socket errors

    def send(self, msg: dict):
        if self.transport:
            try:
                data = json.dumps(msg).encode('utf-8')
                self.transport.sendto(data, (MCAST_GRP, MCAST_PORT))
            except Exception:
                pass


def create_multicast_socket() -> socket.socket:
    """Creates and configures the raw UDP multicast socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except AttributeError:
        pass

    sock.bind(('', MCAST_PORT))

    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

    sock.setblocking(False)
    return sock


# ---------------------------------------------------------------------------
# Curses helpers
# ---------------------------------------------------------------------------

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_WHITE, -1)


def draw_screen(stdscr, username: str, chat_history: list, input_buffer: str):
    """Renders the full TUI frame."""
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()

    # Header
    header_text = f" SHADOW-CHAT | User: {username} | Type /quit or press Ctrl+C to exit "
    try:
        stdscr.addstr(0, 0, header_text.ljust(max_x)[:max_x],
                      curses.color_pair(6) | curses.A_REVERSE)
    except curses.error:
        pass

    # Separator
    try:
        stdscr.hline(max_y - 2, 0, curses.ACS_HLINE, max_x)
    except curses.error:
        pass

    # Chat window
    chat_win_lines = max_y - 3
    if chat_win_lines > 0:
        render_lines = []
        for m in chat_history:
            time_str = m.get("time", "00:00")
            u_str = m.get("user", "Unknown")
            c_str = m.get("color", "white")
            text = m.get("text", "")

            prefix = f"[{time_str}] {u_str}: "
            indent = " " * len(prefix)
            safe_width = max(10, max_x - 1 - len(prefix))
            wrapped = textwrap.wrap(text, width=safe_width)

            if not wrapped:
                render_lines.append((prefix, "", c_str, True))
            else:
                for i, line in enumerate(wrapped):
                    render_lines.append((prefix if i == 0 else indent, line, c_str, i == 0))

        for idx, (pref, line_text, c_name, is_first) in enumerate(render_lines[-chat_win_lines:]):
            c_pair = COLOR_MAP.get(c_name, 6)
            try:
                if is_first:
                    stdscr.addstr(1 + idx, 0, pref, curses.color_pair(c_pair) | curses.A_BOLD)
                    stdscr.addstr(1 + idx, len(pref), line_text, curses.color_pair(6))
                else:
                    stdscr.addstr(1 + idx, 0, pref, curses.color_pair(6))
                    stdscr.addstr(1 + idx, len(pref), line_text, curses.color_pair(6))
            except curses.error:
                pass

    # Input area
    prompt = "> "
    display_input = (input_buffer[-(max_x - 3):]
                     if len(input_buffer) > max_x - 3
                     else input_buffer)
    try:
        stdscr.addstr(max_y - 1, 0, prompt + display_input)
    except curses.error:
        pass

    stdscr.refresh()


# ---------------------------------------------------------------------------
# Async TUI coroutines
# ---------------------------------------------------------------------------

async def input_handler(
    stdscr,
    loop: asyncio.AbstractEventLoop,
    protocol: MulticastProtocol,
    username: str,
    user_color: str,
    chat_history: list,
    input_buffer_ref: list,   # single-element list used as a mutable reference
    stop_event: asyncio.Event,
):
    """Reads keystrokes in a thread-pool executor so getch() never blocks the loop."""
    executor = None  # Use the default ThreadPoolExecutor

    while not stop_event.is_set():
        ch = await loop.run_in_executor(executor, stdscr.getch)

        if ch == -1:
            # nodelay returned immediately with no key — yield briefly
            await asyncio.sleep(0.01)
            continue

        if ch in (curses.KEY_ENTER, 10, 13):
            clean_input = input_buffer_ref[0].strip()
            if clean_input == "/quit":
                stop_event.set()
                break
            if clean_input:
                out_msg = {
                    "user": username,
                    "color": user_color,
                    "text": clean_input,
                    "time": time.strftime("%H:%M"),
                }
                protocol.send(out_msg)
            input_buffer_ref[0] = ""

        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            input_buffer_ref[0] = input_buffer_ref[0][:-1]

        elif ch == curses.KEY_RESIZE:
            pass  # Next redraw cycle handles the new size automatically

        elif 32 <= ch <= 126:
            input_buffer_ref[0] += chr(ch)


async def ui_loop(
    stdscr,
    username: str,
    chat_history: list,
    input_buffer_ref: list,
    msg_queue: asyncio.Queue,
    notify_queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    """Polls for new network messages and redraws the screen every 50 ms."""
    while not stop_event.is_set():
        # Drain all pending messages
        while not msg_queue.empty():
            try:
                msg_data = msg_queue.get_nowait()
                chat_history.append(msg_data)
                # Only notify for messages from other users
                if msg_data.get("user") == username:
                    notify_queue.put_nowait(msg_data)
            except asyncio.QueueEmpty:
                break

        draw_screen(stdscr, username, chat_history, input_buffer_ref[0])
        await asyncio.sleep(0.05)  # ~20 FPS redraw rate


async def notifier_task(
    username: str,
    notifier: DesktopNotifier,
    notify_queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    """Waits for incoming messages and fires a desktop notification for each one.

    Uses a dedicated asyncio.Queue (notify_queue) that the ui_loop populates,
    keeping notification logic fully decoupled from rendering.
    """
    while not stop_event.is_set():
        try:
            msg = await asyncio.wait_for(notify_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue  # Re-check stop_event regularly

        sender = msg.get("user", "Unknown")
        text = msg.get("text", "")

        await notifier.send(
            title=f"New message from {sender}",
            message=text,
            reply_field=ReplyField(
                title="Reply",
                button_title="Send",
                on_replied=lambda reply_text: None,  # To-do: wire up to protocol.send
            ),
            on_clicked=lambda: None,  # To-do: focus app when clicked
            sound=PING_SOUND,
        )


async def run_chat_async(stdscr, username: str, user_color: str):
    """Sets up asyncio networking and runs the UI + input coroutines concurrently."""
    init_colors()

    stdscr.nodelay(True)
    curses.curs_set(0)

    loop = asyncio.get_running_loop()
    msg_queue: asyncio.Queue = asyncio.Queue()
    notify_queue: asyncio.Queue = asyncio.Queue()
    chat_history: list = []
    input_buffer_ref: list = [""]   # Mutable container so both coroutines share state
    stop_event = asyncio.Event()

    notifier = DesktopNotifier(app_name="Shadow Chat")

    # Register the multicast socket with the event loop
    raw_sock = create_multicast_socket()
    _, protocol = await loop.create_datagram_endpoint(
        lambda: MulticastProtocol(msg_queue),
        sock=raw_sock,
    )

    try:
        await asyncio.gather(
            ui_loop(stdscr, username, chat_history, input_buffer_ref, msg_queue, notify_queue, stop_event),
            input_handler(stdscr, loop, protocol, username, user_color,
                          chat_history, input_buffer_ref, stop_event),
            notifier_task(username, notifier, notify_queue, stop_event),
        )
    finally:
        if protocol.transport:
            protocol.transport.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_chat(stdscr, username: str, user_color: str):
    """Curses wrapper entry — bridges the synchronous curses.wrapper into asyncio."""
    asyncio.run(run_chat_async(stdscr, username, user_color))


def main():
    print("=" * 40)
    print("      Welcome to SHADOW-CHAT")
    print("=" * 40)

    username = input("Enter your Username: ").strip() or "Anonymous"

    print("\nAvailable colors: cyan, green, yellow, red, magenta, white")
    color = input("Choose a color: ").strip().lower()
    if color not in COLOR_MAP:
        color = 'white'

    # macOS requires the Rubicon event loop to support notification callbacks.
    # This must be set before asyncio.run() is called inside curses.wrapper.
    if sys.platform == "darwin":
        try:
            from rubicon.objc.eventloop import EventLoopPolicy
            asyncio.set_event_loop_policy(EventLoopPolicy())
        except ImportError:
            pass  # rubicon-objc not installed — notifications may lack callbacks

    curses.wrapper(run_chat, username, color)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
