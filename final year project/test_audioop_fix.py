import sys
try:
    import audioop
    print("Native audioop loaded successfully.")
except ImportError:
    try:
        import audioopy
        sys.modules['audioop'] = audioopy
        print("audioopy polyfill loaded successfully.")
    except ImportError:
        print("Neither audioop nor audioopy found.")

if 'audioop' in sys.modules:
    import audioop
    try:
        # Pydub uses audioop.max
        res = audioop.max(b'\x01\x02\x03\x04', 2)
        print(f"audioop.max test passed: {res}")
    except AttributeError:
        print("AttributeError: audioop.max not found!")
    except Exception as e:
        print(f"Error during audioop.max test: {e}")
