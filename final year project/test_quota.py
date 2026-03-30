from classifier_service import get_groq_client, classify_order
import json

def test_groq():
    print("Testing Groq (Llama 3.3 70B)...")
    try:
        client = get_groq_client()
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Say hello"}],
            max_tokens=10
        )
        print("✅ Groq Success:", completion.choices[0].message.content)
    except Exception as e:
        print("❌ Groq Error:", str(e))

def test_gemini():
    print("\nTesting Gemini (2.0 Flash - if used as fallback)...")
    try:
        from google import genai
        import os
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ No GEMINI_API_KEY in environment.")
            return
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Say hello"
        )
        print("✅ Gemini Success:", response.text)
    except Exception as e:
        print("❌ Gemini Error:", str(e))

if __name__ == "__main__":
    test_groq()
    test_gemini()
