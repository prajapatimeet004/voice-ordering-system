import os
import sys

def patch():
    with open("server.py", "r") as f:
        content = f.read()
    
    if "import logging" not in content:
        content = "import logging\nlogging.basicConfig(filename='ws_debug.log', level=logging.DEBUG)\n" + content
        content = content.replace('print("Received WS TEXT:"', 'logging.debug("Received WS TEXT: " + str(message["text"]))\n                    print("Received WS TEXT:"')
        content = content.replace('print(f"Received WS BYTES size:', 'logging.debug(f"Received WS BYTES size: {len(message[\'bytes\'])}")\n                print(f"Received WS BYTES size:')
        content = content.replace('print(f"Processing error in WS: {e}")', 'logging.error(f"Processing error in WS: {e}")\n                                print(f"Processing error in WS: {e}")')
        content = content.replace('print(f"WS text error: {e}")', 'logging.error(f"WS text error: {e}")\n                    print(f"WS text error: {e}")')
        content = content.replace('print("WS Client disconnected.")', 'logging.debug("WS Client disconnected.")\n                print("WS Client disconnected.")')
        
        with open("server.py", "w") as f:
            f.write(content)

patch()
