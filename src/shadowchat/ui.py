import asyncio
import curses
import textwrap

from shadowchat.constants import COLOR_MAP


screen_lock = asyncio.Lock()


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    for i, color in enumerate(
        [
            curses.COLOR_CYAN,
            curses.COLOR_GREEN,
            curses.COLOR_YELLOW,
            curses.COLOR_RED,
            curses.COLOR_MAGENTA,
            curses.COLOR_WHITE,
            curses.COLOR_BLUE,
        ],
        1,
    ):
        curses.init_pair(i, color, -1)


async def draw_screen(stdscr, username: str, chat_history: list, input_buffer: str):
    async with screen_lock:
        max_y, max_x = stdscr.getmaxyx()
        stdscr.erase()

        # Header
        header_text = f" SHADOW-CHAT | User: {username} | /quit or /q to exit "
        try:
            stdscr.addstr(
                0,
                0,
                header_text.ljust(max_x)[:max_x],
                curses.color_pair(6) | curses.A_REVERSE,
            )
            stdscr.hline(max_y - 2, 0, curses.ACS_HLINE, max_x)
        except curses.error:
            pass

        # Chat window
        chat_win_lines = max_y - 3
        if chat_win_lines > 0:
            render_lines = []
            for m in chat_history:
                prefix = f"[{m.get('time', '00:00')}] {m.get('user', 'Unknown')}: "
                safe_width = max(10, max_x - len(prefix) - 1)
                wrapped = textwrap.wrap(m.get("text", ""), width=safe_width)
                if not wrapped:
                    render_lines.append(
                        (prefix, "", m.get("color", "white"), True)
                    )
                for i, line in enumerate(wrapped):
                    render_lines.append(
                        (
                            prefix if i == 0 else " " * len(prefix),
                            line,
                            m.get("color", "white"),
                            i == 0,
                        )
                    )

            for idx, (pref, text, c_name, is_first) in enumerate(
                render_lines[-chat_win_lines:]
            ):
                c_pair = COLOR_MAP.get(c_name, 6)
                try:
                    stdscr.addstr(
                        1 + idx,
                        0,
                        pref,
                        curses.color_pair(c_pair)
                        | (curses.A_BOLD if is_first else 0),
                    )
                    stdscr.addstr(1 + idx, len(pref), text, curses.color_pair(6))
                except curses.error:
                    pass

        # Input
        try:
            prompt = "> "
            display = (
                (prompt + input_buffer)[-(max_x - 1) :]
                if len(prompt + input_buffer) >= max_x
                else (prompt + input_buffer)
            )
            stdscr.addstr(max_y - 1, 0, display)
        except curses.error:
            pass

        stdscr.refresh()
