import sys
import json
import urllib.request

def send_code(code_str):
    url = "http://127.0.0.1:8080"
    data = json.dumps({"code": code_str}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if "error" in res:
                print("BLENDER ERROR:", res["error"])
            else:
                print("BLENDER OUTPUT:", res.get("output", "OK"))
    except Exception as e:
        print("HTTP ERROR:", e)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            code = f.read()
    else:
        code = sys.stdin.read()
    send_code(code)
