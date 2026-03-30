#!/usr/bin/env python3
"""
HydraBot Status Server — lightweight HTTP status page for dev preview.
"""
import json, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).parent
PORT = int(os.environ.get("PORT", 8080))

def read_config():
    try:
        return json.loads((BASE / "config.json").read_text())
    except Exception:
        return {}

def read_version():
    try:
        return (BASE / "VERSION").read_text().strip()
    except Exception:
        return "?"

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # suppress access logs

    def do_GET(self):
        cfg = read_config()
        ver = read_version()
        models = cfg.get("models", [])
        token  = cfg.get("telegram_token", "")
        has_token = bool(token) and "YOUR_" not in token
        tool_count = len(list((BASE / "tools").glob("*.py"))) if (BASE / "tools").exists() else 0
        venv_ok = (BASE / "venv").exists()

        rows = ""
        for i, m in enumerate(models):
            key = m.get("api_key", "")
            key_ok = bool(key) and "YOUR_" not in key
            key_disp = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "未設定"
            rows += f"""
            <tr>
              <td>#{i}</td>
              <td>{m.get('name', m.get('model','?'))}</td>
              <td>{m.get('provider','?')}</td>
              <td>{m.get('model','?')}</td>
              <td class="{'ok' if key_ok else 'bad'}">{key_disp}</td>
            </tr>"""

        if not models:
            # legacy single-model config
            key = cfg.get("model_api_key","")
            key_ok = bool(key) and "YOUR_" not in key
            key_disp = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "未設定"
            rows = f"""
            <tr>
              <td>#0</td>
              <td>{cfg.get('model_name','?')}</td>
              <td>{cfg.get('model_provider','?')}</td>
              <td>{cfg.get('model_name','?')}</td>
              <td class="{'ok' if key_ok else 'bad'}">{key_disp}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🐍 HydraBot Status</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh;padding:2rem}}
  h1{{font-size:2rem;color:#58a6ff;margin-bottom:.25rem}}
  .sub{{color:#8b949e;margin-bottom:2rem}}
  .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.5rem;margin-bottom:1.5rem}}
  .card h2{{color:#e6edf3;font-size:1rem;text-transform:uppercase;letter-spacing:.1em;margin-bottom:1rem}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem}}
  .stat{{background:#0d1117;border-radius:6px;padding:1rem;text-align:center}}
  .stat .val{{font-size:1.8rem;font-weight:700;color:#58a6ff}}
  .stat .lbl{{font-size:.75rem;color:#8b949e;margin-top:.25rem}}
  .ok{{color:#3fb950}}
  .bad{{color:#f85149}}
  .warn{{color:#d29922}}
  table{{width:100%;border-collapse:collapse;font-size:.875rem}}
  th,td{{padding:.5rem .75rem;text-align:left;border-bottom:1px solid #21262d}}
  th{{color:#8b949e;font-weight:500}}
  .badge{{display:inline-block;padding:.2rem .6rem;border-radius:12px;font-size:.75rem;font-weight:600}}
  .badge.ok{{background:#1a3a1a;color:#3fb950}}
  .badge.bad{{background:#3a1a1a;color:#f85149}}
  .cmd{{background:#0d1117;border-radius:4px;padding:.75rem 1rem;font-family:monospace;font-size:.875rem;color:#79c0ff;border:1px solid #21262d;margin-top:.5rem}}
</style>
</head>
<body>
<h1>🐍 HydraBot</h1>
<p class="sub">Self-expanding AI Assistant via Telegram &nbsp;·&nbsp; v{ver}</p>

<div class="card">
  <h2>快速狀態</h2>
  <div class="grid">
    <div class="stat">
      <div class="val {'ok' if has_token else 'bad'}">{'✓' if has_token else '✗'}</div>
      <div class="lbl">Telegram Token</div>
    </div>
    <div class="stat">
      <div class="val">{len(models) or 1}</div>
      <div class="lbl">模型組數</div>
    </div>
    <div class="stat">
      <div class="val">{tool_count + 19}</div>
      <div class="lbl">工具總數</div>
    </div>
    <div class="stat">
      <div class="val {'ok' if venv_ok else 'warn'}">{'✓' if venv_ok else '!'}</div>
      <div class="lbl">虛擬環境</div>
    </div>
  </div>
</div>

<div class="card">
  <h2>模型設定</h2>
  <table>
    <tr><th>#</th><th>名稱</th><th>Provider</th><th>Model</th><th>API Key</th></tr>
    {rows}
  </table>
</div>

<div class="card">
  <h2>常用命令</h2>
  <p style="color:#8b949e;font-size:.875rem">在終端機中執行</p>
  <div class="cmd">bash &lt;(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)</div>
  <div class="cmd" style="margin-top:.5rem">hydrabot start &nbsp;·&nbsp; hydrabot update &nbsp;·&nbsp; hydrabot status &nbsp;·&nbsp; hydrabot logs</div>
</div>
</body>
</html>"""

        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    print(f"HydraBot Status Server running on http://localhost:{PORT}", flush=True)
    HTTPServer(("", PORT), Handler).serve_forever()
