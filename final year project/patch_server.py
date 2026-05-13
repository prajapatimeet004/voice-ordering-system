def patch():
    with open("server.py", "r") as f:
        content = f.read()
    
    content = content.replace(
        'data = json.loads(message["text"])',
        'print("Received WS TEXT:", message["text"])\n                    data = json.loads(message["text"])'
    )
    content = content.replace(
        'elif "bytes" in message:',
        'elif "bytes" in message:\n                print(f"Received WS BYTES size: {len(message[\'bytes\'])}")'
    )
    
    with open("server.py", "w") as f:
        f.write(content)

patch()
