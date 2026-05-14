import os
log_file = r"c:\laragon\www\Rondan\Chatbot\bot_final.log"
if os.path.exists(log_file):
    with open(log_file, "rb") as f:
        content = f.read()
    try:
        text = content.decode("utf-16-le")
        print(text[-2000:]) # Last 2000 chars
    except:
        print(content[-500:]) # Fallback
else:
    print("LOG NOT FOUND")
