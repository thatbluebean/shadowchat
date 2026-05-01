import curses
import socket
import struct
import json
import textwrap
import time
import sys
import asyncio
import os
import random

# -#- Network Configuration -#-
MCAST_GRP = '224.1.1.1'
MCAST_PORT = 5007

COLOR_MAP = {
    'cyan': 1, 'green': 2, 'yellow': 3,
    'red': 4, 'magenta': 5, 'white': 6,
    'blue': 7
}

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

json_path = get_resource_path(os.path.join("assets", "ai.json"))
with open(json_path, "r", encoding="utf-8") as f:
    aijson = json.load(f)



# Thread-safety lock for curses operations
screen_lock = asyncio.Lock()

class MulticastProtocol(asyncio.DatagramProtocol):
    def __init__(self, msg_queue: asyncio.Queue):
        self._queue = msg_queue
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode('utf-8'))
            self._queue.put_nowait(msg)
        except Exception:
            pass

    def send(self, msg: dict):
        if self.transport:
            try:
                data = json.dumps(msg).encode('utf-8')
                self.transport.sendto(data, (MCAST_GRP, MCAST_PORT))
            except Exception:
                pass

def create_multicast_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except AttributeError:
        pass
    sock.bind(('', MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    sock.setblocking(False)
    return sock

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    for i, color in enumerate([curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW, 
                               curses.COLOR_RED, curses.COLOR_MAGENTA, curses.COLOR_WHITE, 
                               curses.COLOR_BLUE], 1):
        curses.init_pair(i, color, -1)

async def draw_screen(stdscr, username: str, chat_history: list, input_buffer: str):
    async with screen_lock:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.erase()

        # Header
        header_text = f' SHADOW-CHAT | User: {username} | /quit to exit '
        try:
            stdscr.addstr(0, 0, header_text.ljust(max_x)[:max_x], curses.color_pair(6) | curses.A_REVERSE)
            stdscr.hline(max_y - 2, 0, curses.ACS_HLINE, max_x)
        except curses.error: pass

        # Chat window
        chat_win_lines = max_y - 3
        if chat_win_lines > 0:
            render_lines = []
            for m in chat_history:
                prefix = f"[{m.get('time', '00:00')}] {m.get('user', 'Unknown')}: "
                safe_width = max(10, max_x - len(prefix) - 1)
                wrapped = textwrap.wrap(m.get('text', ''), width=safe_width)
                if not wrapped:
                    render_lines.append((prefix, '', m.get('color', 'white'), True))
                for i, line in enumerate(wrapped):
                    render_lines.append((prefix if i == 0 else ' ' * len(prefix), line, m.get('color', 'white'), i == 0))

            for idx, (pref, text, c_name, is_first) in enumerate(render_lines[-chat_win_lines:]):
                c_pair = COLOR_MAP.get(c_name, 6)
                try:
                    stdscr.addstr(1 + idx, 0, pref, curses.color_pair(c_pair) | (curses.A_BOLD if is_first else 0))
                    stdscr.addstr(1 + idx, len(pref), text, curses.color_pair(6))
                except curses.error: pass

        # Input
        try:
            prompt = '> '
            display = (prompt + input_buffer)[-(max_x-1):] if len(prompt + input_buffer) >= max_x else (prompt + input_buffer)
            stdscr.addstr(max_y - 1, 0, display)
        except curses.error: pass

        stdscr.refresh()

# --- COMMANDS ---
def cmd_quit(args, ctx): 
    ctx['stop_event'].set()

async def cmd_users_async(ctx):
    ctx['chat_history'].append({'user': '## SYSTEM ##', 'color': 'blue', 'text': 'Scanning network...', 'time': time.strftime('%H:%M')})
    ctx['seen_users'].clear()
    ctx['protocol'].send({'type': 'ping_users', 'user': ctx['user_profile']['name']})
    await asyncio.sleep(1.5)
    others = [u for u in ctx['seen_users'] if u != ctx['user_profile']['name']]
    msg = f"Online users: {', '.join(others)}" if others else "No one else is here."
    ctx['chat_history'].append({'user': '## SYSTEM ##', 'color': 'blue', 'text': msg, 'time': time.strftime('%H:%M')})

def cmd_rename(args: str, context: dict):
    new_name = args.strip()
    if not new_name: return 
    old_name = context['user_profile']['name']
    context['user_profile']['name'] = new_name
    if old_name in context['seen_users']: context['seen_users'].remove(old_name)
    context['seen_users'].add(new_name)
    context['chat_history'].append({'user': '## SYSTEM ##', 'color': 'yellow', 'text': f'{old_name} is now {new_name}', 'time': time.strftime('%H:%M')})
    context['protocol'].send({'type': 'rename', 'user': new_name, 'old_name': old_name, 'new_name': new_name})

def cmd_help(args: str, context: dict):
    context['chat_history'].append({'user': '## SYSTEM ##', 'color': 'yellow', 'text': 'Commands: /users, /rename [$name], /quit, /help, /askai [$question]', 'time': time.strftime('%H:%M')})

def cmd_askai(args: str, context: dict,):
    if not args.strip():
        context['chat_history'].append({'user': '## SYSTEM ##', 'color': 'red', 'text': 'You must ask a question! Usage: /askai <question>', 'time': time.strftime('%H:%M')})
        return
    
    protocol = context['protocol']
    current_time = time.strftime('%H:%M')

    protocol.send({'type': 'chat', 'user': context['user_profile']['name'], 'color': context['user_profile']['color'], 'text': f"{args}", 'time': current_time})

    protocol.send({'type': 'chat', 'user': 'SuperAI', 'color': 'magenta','text': random.choice(aijson),'time': current_time})

COMMAND_REGISTRY = {
    '/quit': cmd_quit, 
    '/users': lambda a, c: asyncio.create_task(cmd_users_async(c)),
    '/rename': cmd_rename,
    '/help': cmd_help,
    '/askai': cmd_askai
}

async def input_handler(stdscr, protocol, user_profile, chat_history, input_buf_ref, stop_event, seen_users):
    while not stop_event.is_set():
        async with screen_lock:
            ch = stdscr.getch()

        if ch == -1:
            await asyncio.sleep(0.02)
            continue
        
        if ch in (10, 13, curses.KEY_ENTER):
            cmd_text = input_buf_ref[0].strip()
            if cmd_text.startswith('/'):
                parts = cmd_text.split(' ', 1)
                cmd = parts[0].lower()
                if cmd in COMMAND_REGISTRY:
                    context = {'stop_event': stop_event, 'chat_history': chat_history, 'seen_users': seen_users, 'user_profile': user_profile, 'protocol': protocol}
                    COMMAND_REGISTRY[cmd](parts[1] if len(parts)>1 else '', context)
                else:
                    chat_history.append({'user': '## SYSTEM ##', 'color': 'red', 'text': f'Unknown command: {cmd}', 'time': time.strftime('%H:%M')})
            elif cmd_text:
                protocol.send({'type': 'chat', 'user': user_profile['name'], 'color': user_profile['color'], 'text': cmd_text, 'time': time.strftime('%H:%M')})
            input_buf_ref[0] = ''
        
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            input_buf_ref[0] = input_buf_ref[0][:-1]
        elif ch == curses.KEY_RESIZE:
            async with screen_lock:
                curses.update_lines_cols()
        elif 32 <= ch <= 126:
            input_buf_ref[0] += chr(ch)

async def ui_loop(stdscr, user_profile, chat_history, input_buf_ref, msg_queue, stop_event, protocol, seen_users):
    while not stop_event.is_set():
        while not msg_queue.empty():
            msg = msg_queue.get_nowait()
            m_type, sender = msg.get('type', 'chat'), msg.get('user', 'Unknown')
            
            if sender == user_profile['name'] and m_type != 'chat':
                continue

            if m_type == 'chat':
                chat_history.append(msg)
            
            elif m_type == 'join':
                seen_users.add(sender)
                protocol.send({'type': 'presence', 'user': user_profile['name']})
                chat_history.append({'user': '-- SHADOW --', 'color': 'blue', 'text': f'{sender} joined.', 'time': time.strftime('%H:%M')})
            
            elif m_type in ('presence', 'ping_users'):
                seen_users.add(sender)
                if m_type == 'ping_users':
                    protocol.send({'type': 'presence', 'user': user_profile['name']})
            
            elif m_type == 'rename':
                old, new = msg.get('old_name'), msg.get('new_name')
                if old in seen_users: seen_users.remove(old)
                seen_users.add(new)
                chat_history.append({'user': '## SYSTEM ##', 'color': 'yellow', 'text': f'{old} is now {new}', 'time': time.strftime('%H:%M')})

        await draw_screen(stdscr, user_profile['name'], chat_history, input_buf_ref[0])
        await asyncio.sleep(0.05)

async def welcome_sequence(username, protocol, chat_history, seen_users):
    protocol.send({'type': 'join', 'user': username})
    await asyncio.sleep(1.5)
    others = [u for u in seen_users if u != username]
    users_str = ', '.join(others) if others else 'No one else is here yet.'
    chat_history.append({'user': '-- SHADOW --', 'color': 'blue', 'text': f'Welcome! Online: {users_str}, try /help!', 'time': time.strftime('%H:%M')})

async def run_chat_async(stdscr, username, color):
    init_colors()
    stdscr.nodelay(True)
    curses.curs_set(0)
    
    msg_queue = asyncio.Queue()
    chat_history, input_buf_ref, seen_users = [], [''], set()
    stop_event = asyncio.Event()
    user_profile = {'name': username, 'color': color}

    raw_sock = create_multicast_socket()
    loop = asyncio.get_running_loop()
    _, protocol = await loop.create_datagram_endpoint(lambda: MulticastProtocol(msg_queue), sock=raw_sock)

    asyncio.create_task(welcome_sequence(username, protocol, chat_history, seen_users))

    try:
        await asyncio.gather(
            ui_loop(stdscr, user_profile, chat_history, input_buf_ref, msg_queue, stop_event, protocol, seen_users),
            input_handler(stdscr, protocol, user_profile, chat_history, input_buf_ref, stop_event, seen_users)
        )
    finally:
        if protocol.transport:
            protocol.transport.close()

def run_chat(stdscr, username, color):
    asyncio.run(run_chat_async(stdscr, username, color))

def main():
    if sys.platform == 'win32': os.system('')
    print('=' * 40 + '\n      Welcome to SHADOW-CHAT\n' + '=' * 40)
    
    username = input('Enter your Username: ').strip() or 'Anonymous'

    print('\nAvailable colors:')
    print('[1] \033[36mcyan\033[0m')
    print('[2] \033[32mgreen\033[0m')
    print('[3] \033[33myellow\033[0m')
    print('[4] \033[31mred\033[0m')
    print('[5] \033[35mmagenta\033[0m')
    print('[6] \033[37mwhite\033[0m')
    
    color_input = input('\nChoose a color: ').strip().lower()
    number_map = {'1': 'cyan', '2': 'green', '3': 'yellow', '4': 'red', '5': 'magenta', '6': 'white'}
    color = number_map.get(color_input, color_input if color_input in COLOR_MAP else 'white')

    if sys.platform == 'darwin':
        try:
            from rubicon.objc.eventloop import EventLoopPolicy
            asyncio.set_event_loop_policy(EventLoopPolicy())
        except ImportError: pass  

    curses.wrapper(run_chat, username, color)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
