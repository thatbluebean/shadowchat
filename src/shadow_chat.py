import curses
import socket
import struct
import json
import textwrap
import time
import sys
import asyncio
import logging
import os
from pathlib import Path

from desktop_notifier import DesktopNotifier, ReplyField, Sound

# --- Network Configuration ---
MCAST_GRP = '224.1.1.1'
MCAST_PORT = 5007

# Map user color choices to curses color pairs
COLOR_MAP = {
    'cyan': 1, 'green': 2, 'yellow': 3,
    'red': 4, 'magenta': 5, 'white': 6,
    'blue': 7
}

def get_asset_path(filename):
    '''Finds the asset whether running as a dev script or a bundled .exe'''
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller gives us a temp folder i think
        return os.path.join(sys._MEIPASS, 'assets', filename)
    else:
        base_dir = Path(__file__).resolve().parent.parent
        return str(base_dir / 'assets' / filename)

PING_SOUND = Sound(path=get_asset_path('ping.mp3'))

# ---------------------------------------------------------------------------
# Asyncio UDP Protocol
# ---------------------------------------------------------------------------

class MulticastProtocol(asyncio.DatagramProtocol):
    '''Asyncio UDP datagram protocol for multicast send/receive.'''

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
    '''Creates and configures the raw UDP multicast socket.'''
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except AttributeError:
        pass

    sock.bind(('', MCAST_PORT))

    mreq = struct.pack('4sl', socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
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
    curses.init_pair(7, curses.COLOR_BLUE, -1)


def draw_screen(stdscr, username: str, chat_history: list, input_buffer: str):
    '''Renders the full TUI frame.'''
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()

    # Header
    header_text = f' SHADOW-CHAT | User: {username} | Type /quit or press Ctrl+C to exit '
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
            time_str = m.get('time', '00:00')
            u_str = m.get('user', 'Unknown')
            c_str = m.get('color', 'white')
            text = m.get('text', '')

            prefix = f'[{time_str}] {u_str}: '
            indent = ' ' * len(prefix)
            safe_width = max(10, max_x - 1 - len(prefix))
            wrapped = textwrap.wrap(text, width=safe_width)

            if not wrapped:
                render_lines.append((prefix, '', c_str, True))
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
    prompt = '> '
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

# --- COMMAND SYSYTEM!! ---

def cmd_help(args: str, context: dict):
    commands = [c for c in COMMAND_REGISTRY]
    cmd_str = ', '.join(commands)
    context['chat_history'].append({
        'user': '## SYSTEM ##', 'color': 'blue',
        'text': f'Commands: {cmd_str}', 
        'time': time.strftime('%H:%M')
    })

def cmd_quit(args: str, context: dict):
    '''Triggers the app to shut down.'''
    context['stop_event'].set()

def cmd_users(args: str, context: dict):
    '''Pings the network to actively discover who is online.'''
    
    async def perform_ping():
        context['chat_history'].append({
            'user': '## SYSTEM ##', 'color': 'blue',
            'text': 'Scanning network for users...', 
            'time': time.strftime('%H:%M')
        })
        
        context['seen_users'].clear()
        
        ping_packet = {'type': 'ping_users'}
        context['protocol'].transport.sendto(
            json.dumps(ping_packet).encode(), 
            (MCAST_GRP, MCAST_PORT)
        )
        
        await asyncio.sleep(1.5)
        
        others = [u for u in context['seen_users'] if u != context['user_profile']['name']]
        users_str = ', '.join(others) if others else 'No one else is here.'
        
        context['chat_history'].append({
            'user': '## SYSTEM ##', 'color': 'blue',
            'text': f'Online users: {users_str}', 
            'time': time.strftime('%H:%M')
        })

    # Fire off the async task in the background so it doesn't freeze the terminal
    asyncio.create_task(perform_ping())

def cmd_rename(args: str, context: dict):
    '''Changes the user's name locally and announces it to the network.'''
    new_name = args.strip()
    if not new_name:
        return 

    old_name = context['user_profile']['name']

    # 1. Update the mutable profile state
    context['user_profile']['name'] = new_name

    # 2. Update our own local list of seen users so /users is accurate for us
    if old_name in context['seen_users']:
        context['seen_users'].remove(old_name)
    context['seen_users'].add(new_name)

    # 3. Print the announcement locally for ourselves
    context['chat_history'].append({
        'user': '## SYSTEM ##', 'color': 'yellow',
        'text': f'{old_name} has renamed themselves to {new_name}',
        'time': time.strftime('%H:%M')
    })

    # 4. Broadcast a specific 'rename' packet so OTHER clients update their lists
    rename_packet = {
        'type': 'rename',
        'user': new_name,  # We include this so our own ui_loop ignores the echo
        'old_name': old_name,
        'new_name': new_name
    }
    
    context['protocol'].transport.sendto(
        json.dumps(rename_packet).encode(), 
        (MCAST_GRP, MCAST_PORT)
    )


# map command to command backend
COMMAND_REGISTRY = {
    '/quit': cmd_quit,
    '/users': cmd_users,
    '/rename': cmd_rename,
    '/help': cmd_help
}

# --- INPUT HANDLER ---

async def input_handler(
    stdscr,
    loop: asyncio.AbstractEventLoop,
    protocol: MulticastProtocol,
    user_profile: dict,
    chat_history: list,
    input_buffer_ref: list,   
    stop_event: asyncio.Event,
    seen_users: set
):
    '''Reads keystrokes in a thread-pool executor so getch() never blocks the loop.'''
    executor = None  # Use the default ThreadPoolExecutor

    while not stop_event.is_set():
        ch = await loop.run_in_executor(executor, stdscr.getch)

        if ch == -1:
            # nodelay returned immediately with no key — yield briefly
            await asyncio.sleep(0.01)
            continue

        if ch in (curses.KEY_ENTER, 10, 13):
            clean_input = input_buffer_ref[0].strip()
            
            # --- COMMAND BRAIN ---
            if clean_input.startswith('/'):
                # Split the input into the command + arg
                parts = clean_input.split(' ', 1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ''

                context = {
                    'stop_event': stop_event,
                    'chat_history': chat_history,
                    'seen_users': seen_users,
                    'user_profile': user_profile,
                    'protocol': protocol
                }

                # the command
                if cmd in COMMAND_REGISTRY:
                    COMMAND_REGISTRY[cmd](args, context)
                else:
                    # Handles unknown commands 
                    chat_history.append({
                        'user': '## SYSTEM ##', 'color': 'red',
                        'text': f'Unknown command: {cmd}', 
                        'time': time.strftime('%H:%M')
                    })
            
            # --- NORMAL CHAT ---
            elif clean_input:
                out_msg = {
                    'type': 'chat', 
                    'user': user_profile['name'],    
                    'color': user_profile['color'],
                    'text': clean_input,
                    'time': time.strftime('%H:%M'),
                }
                protocol.transport.sendto(json.dumps(out_msg).encode(), (MCAST_GRP, MCAST_PORT))
            
            # Clear the input box whether it was a command or a chat
            input_buffer_ref[0] = ''


        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            input_buffer_ref[0] = input_buffer_ref[0][:-1]

        elif ch == curses.KEY_RESIZE:
            pass  # Next redraw cycle handles the new size automatically

        elif 32 <= ch <= 126:
            input_buffer_ref[0] += chr(ch)


async def ui_loop(
    stdscr, 
    user_profile: dict,
    chat_history: list, input_buffer_ref: list,
    msg_queue: asyncio.Queue, notify_queue: asyncio.Queue, stop_event: asyncio.Event,
    protocol, seen_users: set
):
    '''Polls for new network messages and redraws the screen.'''
    while not stop_event.is_set():
        while not msg_queue.empty():
            try:
                msg_data = msg_queue.get_nowait()
                msg_type = msg_data.get('type', 'chat')
                sender = msg_data.get('user', 'Unknown')

                # Ignore our own echoes for system messages
                if sender == user_profile['name']:
                    if msg_type == 'chat':
                        chat_history.append(msg_data)
                    continue

                # Handle the Handshakes
                if msg_type == 'join':
                    seen_users.add(sender)
                    # Silently tell the new user we are here
                    presence_msg = {'type': 'presence', 'user': user_profile['name']}

                    protocol.transport.sendto(json.dumps(presence_msg).encode(), (MCAST_GRP, MCAST_PORT))
                    
                    # Optional: Announce to YOU that someone joined
                    chat_history.append({
                        'user': '-- SHADOW --', 'color': 'blue', 
                        'text': f'{sender} joined the chat.', 
                        'time': time.strftime('%H:%M')
                    })

                elif msg_type == 'presence':
                    #  add them to the hidden list
                    seen_users.add(sender)

                elif msg_type == 'ping_users':
                    # Someone is running /users, silently reply so they know we are here
                    presence_msg = {'type': 'presence', 'user': user_profile['name']}
                    protocol.transport.sendto(json.dumps(presence_msg).encode(), (MCAST_GRP, MCAST_PORT))

                elif msg_type == 'rename':
                    old = msg_data.get('old_name')
                    new = msg_data.get('new_name')
                    
                    # Swap the names in the background list
                    if old in seen_users:
                        seen_users.remove(old)
                    seen_users.add(new)
                    
                    # Print the announcement to their screen
                    chat_history.append({
                        'user': '## SYSTEM ##', 'color': 'yellow',
                        'text': f'{old} has renamed themselves to {new}',
                        'time': time.strftime('%H:%M')
                    })

                elif msg_type == 'chat':
                    # Normal chat logic
                    chat_history.append(msg_data)
                    notify_queue.put_nowait(msg_data)

            except asyncio.QueueEmpty:
                break

        draw_screen(stdscr, user_profile['name'], chat_history, input_buffer_ref[0])
        await asyncio.sleep(0.05)

async def notifier_task(
    username: str,
    notifier: DesktopNotifier,
    notify_queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    '''Waits for incoming messages and fires a desktop notification for each one.

    Uses a dedicated asyncio.Queue (notify_queue) that the ui_loop populates,
    keeping notification logic fully decoupled from rendering.
    '''
    while not stop_event.is_set():
        try:
            msg = await asyncio.wait_for(notify_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue  # Re-check stop_event regularly

        sender = msg.get('user', 'Unknown')
        text = msg.get('text', '')

        await notifier.send(
            title=f'New message from {sender}',
            message=text,
            reply_field=ReplyField(
                title='Reply',
                button_title='Send',
                on_replied=lambda reply_text: None,  # To-do: wire up to protocol.send
            ),
            on_clicked=lambda: None,  # To-do: focus app when clicked
            sound=PING_SOUND,
        )


async def welcome_sequence(username: str, protocol, chat_history: list, seen_users: set):
    '''Broadcasts a join ping, waits for replies, and prints the welcome message.'''
    # 1. Send the join ping to the network
    join_msg = {'type': 'join', 'user': username}
    protocol.transport.sendto(json.dumps(join_msg).encode(), (MCAST_GRP, MCAST_PORT))
    
    # 2. Wait 1.5 seconds to let network presence replies arrive
    await asyncio.sleep(1.5)
    
    # 3. Format the welcome message
    others = [u for u in seen_users if u != username]
    if others:
        users_str = ', '.join(others)
    else:
        users_str = 'No one else is here yet - invite a friend!'
        
    welcome_text = f'Welcome {username}! Connected users: {users_str}'
    
    # 4. Inject it locally into the chat window
    chat_history.append({
        'user': '-- SHADOW --', 
        'color': 'blue', 
        'text': welcome_text, 
        'time': time.strftime('%H:%M')
    })

async def run_chat_async(stdscr, username: str, user_color: str):
    '''Sets up asyncio networking and runs the UI + input coroutines concurrently.'''
    init_colors()

    stdscr.nodelay(True)
    curses.curs_set(0)

    loop = asyncio.get_running_loop()
    msg_queue: asyncio.Queue = asyncio.Queue()
    notify_queue: asyncio.Queue = asyncio.Queue()
    chat_history: list = []
    input_buffer_ref: list = ['']
    seen_users: set = set() 
    stop_event = asyncio.Event()
    user_profile = {'name': username, 'color': user_color}

    notifier = DesktopNotifier(app_name='Shadow Chat')

    raw_sock = create_multicast_socket()
    _, protocol = await loop.create_datagram_endpoint(
        lambda: MulticastProtocol(msg_queue),
        sock=raw_sock,
    )

# Pass user_profile['name'] since this only runs once at startup
    asyncio.create_task(welcome_sequence(user_profile['name'], protocol, chat_history, seen_users))

    try:
        await asyncio.gather(
            # Pass user_profile instead of username
            ui_loop(stdscr, user_profile, chat_history, input_buffer_ref, msg_queue, notify_queue, stop_event, protocol, seen_users),
            # Pass user_profile instead of username and user_color
            input_handler(stdscr, loop, protocol, user_profile,
                          chat_history, input_buffer_ref, stop_event, seen_users),
            # Pass user_profile['name'] 
            notifier_task(user_profile['name'], notifier, notify_queue, stop_event),
        )

    finally:
        if protocol.transport:
            protocol.transport.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_chat(stdscr, username: str, user_color: str):
    '''Curses wrapper entry — bridges the synchronous curses.wrapper into asyncio.'''
    asyncio.run(run_chat_async(stdscr, username, user_color))

def main():
    # forces Windows to enable ANSI color codes in the terminal
    if sys.platform == 'win32':
        os.system('')

    print('=' * 40)
    print('      Welcome to SHADOW-CHAT')
    print('=' * 40)

    username = input('Enter your Username: ').strip() or 'Anonymous'

    print('\nAvailable colors:')
    print('[1] \033[36mcyan\033[0m')
    print('[2] \033[32mgreen\033[0m')
    print('[3] \033[33myellow\033[0m')
    print('[4] \033[31mred\033[0m')
    print('[5] \033[35mmagenta\033[0m')
    print('[6] \033[37mwhite\033[0m')

    color_input = input('\nChoose a color: ').strip().lower()

    # Map number choices to their string equivalents
    number_map = {
        '1': 'cyan',
        '2': 'green',
        '3': 'yellow',
        '4': 'red',
        '5': 'magenta',
        '6': 'white'
    }

    # did we get a numvber or a word
    if color_input in number_map:
        color = number_map[color_input]
    elif color_input in COLOR_MAP:
        color = color_input
    # or nothing
    else:
        color = 'white'

    if sys.platform == 'darwin':
        try:
            from rubicon.objc.eventloop import EventLoopPolicy
            asyncio.set_event_loop_policy(EventLoopPolicy())
        except ImportError:
            pass  

    # do NOT print ANY errors from that notification thing unless they are insane
    logging.getLogger('desktop_notifier').setLevel(logging.CRITICAL)
    logging.getLogger('dbus_fast').setLevel(logging.CRITICAL)

    curses.wrapper(run_chat, username, color)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
