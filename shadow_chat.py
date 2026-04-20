import curses
import socket
import struct
import threading
import json
import queue
import textwrap
import time
import sys
import os # For running commands on the system

# --- Network Configuration ---
MCAST_GRP = '224.1.1.1'
MCAST_PORT = 5007

# --- Set OS version ---
match sys.platform:
    case "linux": osver = "linux"
    case "darwin": osver = "macos"
    case "win32": osver = "win32"
    case _: osver = "unknown"
    
    
# Thread-safe queue for incoming messages
msg_queue = queue.Queue()

def setup_multicast_socket():
    """Sets up a UDP socket for both sending and receiving multicast packets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    
    # Allow multiple clients on the same machine to bind to the same port
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except AttributeError:
        pass
        
    # Bind to the port
    sock.bind(('', MCAST_PORT))
    
    # Join the multicast group
    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    
    # Enable loopback so the sender also receives their own messages
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    
    # Set Time-to-Live (1 is standard for local subnet/LAN)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    
    return sock

def listener_thread(sock):
    """Listens for UDP packets continuously and pushes them to the UI queue."""
    while True:
        try:
            data, _ = sock.recvfrom(10240)
            msg = json.loads(data.decode('utf-8'))
            msg_queue.put(msg)
        except Exception:
            # Silently handle JSON decode or socket errors to protect the TUI
            pass

def init_colors():
    """Initializes standard curses colors."""
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_WHITE, -1)

# Map user color choices to curses color pairs
COLOR_MAP = {
    'cyan': 1, 'green': 2, 'yellow': 3, 
    'red': 4, 'magenta': 5, 'white': 6
}

def run_chat(stdscr, username, user_color):
    """Main Curses TUI Loop."""
    init_colors()
    
    # Setup Network
    sock = setup_multicast_socket()
    
    # Start the daemon listener thread
    t = threading.Thread(target=listener_thread, args=(sock,), daemon=True)
    t.start()
    
    # Configure Curses
    stdscr.nodelay(True)  # Don't block waiting for input
    stdscr.timeout(50)    # Refresh every 50ms
    curses.curs_set(0)    # Hide cursor
    
    chat_history = []
    input_buffer = ""
    
    while True:
        max_y, max_x = stdscr.getmaxyx()
        
        # 1. Process new messages from the network
        while not msg_queue.empty():
            msg_data = msg_queue.get() # { user, color, test, time }
            
            chat_history.append(msg_data)
            if username != msg_data.get('user'): # Dont notify for own messages
                if osver == "linux":
                    os.system(f'notify-send -a "Shadow Chat" "New message from {msg_data.get('user')}: {msg_data.get('text')}"')
                
            
        stdscr.erase()
        
        # 2. Draw Header
        header_text = f" SHADOW-CHAT | User: {username} | Type /quit to exit or press Ctrl + C "
        try:
            stdscr.addstr(0, 0, header_text.ljust(max_x)[:max_x], curses.color_pair(6) | curses.A_REVERSE)
        except curses.error:
            pass

        # 3. Draw Separator
        try:
            stdscr.hline(max_y - 2, 0, curses.ACS_HLINE, max_x)
        except curses.error:
            pass

        # 4. Process and Draw Chat Window (Auto-Scrolling & Word Wrapping)
        chat_win_lines = max_y - 3
        if chat_win_lines > 0:
            render_lines = []
            
            # Format history into lines that fit the current screen width
            for m in chat_history:
                time_str = m.get("time", "00:00")
                u_str = m.get("user", "Unknown")
                c_str = m.get("color", "white")
                text = m.get("text", "")
                
                prefix = f"[{time_str}] {u_str}: "
                indent = " " * len(prefix)
                
                # Protect against tiny terminals crashing textwrap
                safe_width = max(10, max_x - 1 - len(prefix))
                wrapped = textwrap.wrap(text, width=safe_width)
                
                if not wrapped:
                    render_lines.append((prefix, "", c_str, True))
                else:
                    for i, line in enumerate(wrapped):
                        if i == 0:
                            render_lines.append((prefix, line, c_str, True))
                        else:
                            render_lines.append((indent, line, c_str, False))
            
            # Auto-scroll: Only grab the latest lines that fit vertically
            display_lines = render_lines[-chat_win_lines:]
            
            for idx, (pref, line_text, c_name, is_first) in enumerate(display_lines):
                c_pair = COLOR_MAP.get(c_name, 6)
                try:
                    if is_first:
                        # Colorize the prefix (username) but keep text white
                        stdscr.addstr(1 + idx, 0, pref, curses.color_pair(c_pair) | curses.A_BOLD)
                        stdscr.addstr(1 + idx, len(pref), line_text, curses.color_pair(6))
                    else:
                        # Draw indented wrapped text
                        stdscr.addstr(1 + idx, 0, pref, curses.color_pair(6))
                        stdscr.addstr(1 + idx, len(pref), line_text, curses.color_pair(6))
                except curses.error:
                    pass

        # 5. Draw Input Area
        prompt = "> "
        # Tail the input buffer if the user types past the screen width
        display_input = input_buffer[-(max_x - 3):] if len(input_buffer) > max_x - 3 else input_buffer
        try:
            stdscr.addstr(max_y - 1, 0, prompt + display_input)
        except curses.error:
            pass
            
        stdscr.refresh()
        
        # 6. Handle User Input
        try:
            ch = stdscr.getch()
        except curses.error:
            continue
            
        if ch == -1:
            continue
            
        if ch in (curses.KEY_ENTER, 10, 13):
            clean_input = input_buffer.strip()
            if clean_input == "/quit":
                break
            if clean_input:
                out_msg = {
                    "user": username,
                    "color": user_color,
                    "text": clean_input,
                    "time": time.strftime("%H:%M")
                }
                out_data = json.dumps(out_msg).encode('utf-8')
                try:
                    sock.sendto(out_data, (MCAST_GRP, MCAST_PORT))
                except Exception:
                    pass
            input_buffer = ""
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            input_buffer = input_buffer[:-1]
        elif ch == curses.KEY_RESIZE:
            # Curses handles SIGWINCH internally, the next loop iteration redraws safely
            pass
        elif 32 <= ch <= 126: # Printable ASCII characters
            input_buffer += chr(ch)

def main():
    """Startup dialog outside of curses."""
    print("=" * 40)
    print("      Welcome to SHADOW-CHAT")
    print("=" * 40)
    
    username = input("Enter your Username: ").strip()
    if not username:
        username = "Anonymous"
        
    print("\nAvailable colors: cyan, green, yellow, red, magenta, white")
    color = input("Choose a color: ").strip().lower()
    if color not in COLOR_MAP:
        color = 'white'
        
    # Start the TUI, wrapped safely to restore terminal state on exit or crash
    curses.wrapper(run_chat, username, color)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
