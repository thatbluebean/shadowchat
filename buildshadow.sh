rm -rf build-linux build-win dist-linux dist-win *.spec
    
pyinstaller \
    --onefile \
    --distpath dist-linux \
    --workpath build-linux \
    --add-data "assets/ai.json:assets" \
    src/shadow_chat.py &
    
wine python.exe -m PyInstaller \
    --onefile \
    --distpath dist-win \
    --workpath build-win \
    --hidden-import "_curses" \
    --add-data "assets/ai.json;assets" \
    src/shadow_chat.py &

wait
