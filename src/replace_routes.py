import re
import os

file_path = r'c:\laragon\www\Rondan\Chatbot\src\main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

replacements = [
    (r'@app\.get\(\"/admin\", response_class=HTMLResponse\)\nasync def admin_dashboard\(request: Request, user: dict = Depends\(verify_admin\)\):', 
     r'@app.get("/admin", response_class=HTMLResponse)\nasync def admin_dashboard(request: Request, user: dict = Depends(require_permission("dashboard"))):'),
     
    (r'@app\.get\(\"/admin/channels\", response_class=HTMLResponse\)\nasync def view_channels\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/channels", response_class=HTMLResponse)\nasync def view_channels(request: Request, user: dict = Depends(require_permission("channels"))):'),
     
    (r'@app\.post\(\"/admin/whatsapp/logout\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/whatsapp/logout", dependencies=[Depends(require_permission("channels"))])'),
     
    (r'@app\.get\(\"/admin/whatsapp/status\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/whatsapp/status", dependencies=[Depends(require_permission("channels"))])'),
     
    (r'@app\.get\(\"/admin/whatsapp/qr\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/whatsapp/qr", dependencies=[Depends(require_permission("channels"))])'),
     
    (r'@app\.post\(\"/admin/channels/save\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/channels/save", dependencies=[Depends(require_permission("channels"))])'),
     
    (r'@app\.get\(\"/admin/connectivity\", response_class=HTMLResponse\)\nasync def connectivity_panel\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/connectivity", response_class=HTMLResponse)\nasync def connectivity_panel(request: Request, user: dict = Depends(require_permission("channels"))):'),
     
    (r'@app\.get\(\"/admin/history\", response_class=HTMLResponse\)\nasync def view_all_history\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/history", response_class=HTMLResponse)\nasync def view_all_history(request: Request, user: dict = Depends(require_permission("history"))):'),
     
    (r'@app\.get\(\"/admin/chat/\{thread_id\}\", response_class=HTMLResponse, dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/chat/{thread_id}", response_class=HTMLResponse, dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.post\(\"/admin/chat/\{thread_id\}/send\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/chat/{thread_id}/send", dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.post\(\"/admin/chat/\{thread_id\}/send-file\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/chat/{thread_id}/send-file", dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.get\(\"/admin/chat/resume/\{thread_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/chat/resume/{thread_id}", dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.get\(\"/admin/chat/pause/\{thread_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/chat/pause/{thread_id}", dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.get\(\"/admin/chat/\{thread_id\}/delete\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/chat/{thread_id}/delete", dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.post\(\"/admin/chat/\{thread_id\}/notes\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/chat/{thread_id}/notes", dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.post\(\"/admin/chat/\{thread_id\}/send-knowledge\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/chat/{thread_id}/send-knowledge", dependencies=[Depends(require_permission("history"))])'),
     
    (r'@app\.get\(\"/admin/api/knowledge\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/api/knowledge", dependencies=[Depends(require_permission("config"))])'),

    (r'@app\.get\(\"/admin/kanban\", response_class=HTMLResponse\)\nasync def view_kanban\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/kanban", response_class=HTMLResponse)\nasync def view_kanban(request: Request, user: dict = Depends(require_permission("kanban"))):'),
     
    (r'@app\.get\(\"/admin/kanban/move/\{item_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/kanban/move/{item_id}", dependencies=[Depends(require_permission("kanban"))])'),
     
    (r'@app\.get\(\"/admin/appointments\", response_class=HTMLResponse\)\nasync def appointments_panel\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/appointments", response_class=HTMLResponse)\nasync def appointments_panel(request: Request, user: dict = Depends(require_permission("appointments"))):'),
     
    (r'@app\.get\(\"/admin/playground\", response_class=HTMLResponse\)\nasync def view_playground\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/playground", response_class=HTMLResponse)\nasync def view_playground(request: Request, user: dict = Depends(require_permission("playground"))):'),
     
    (r'@app\.post\(\"/admin/playground/chat\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/playground/chat", dependencies=[Depends(require_permission("playground"))])'),
     
    (r'@app\.get\(\"/admin/analytics\", response_class=HTMLResponse\)\nasync def view_analytics\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/analytics", response_class=HTMLResponse)\nasync def view_analytics(request: Request, user: dict = Depends(require_permission("analytics"))):'),
     
    (r'@app\.get\(\"/admin/proceedings\", response_class=HTMLResponse\)\nasync def view_proceedings\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/proceedings", response_class=HTMLResponse)\nasync def view_proceedings(request: Request, user: dict = Depends(require_permission("proceedings"))):'),
     
    (r'@app\.get\(\"/admin/submissions\", response_class=HTMLResponse\)\nasync def view_submissions\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/submissions", response_class=HTMLResponse)\nasync def view_submissions(request: Request, user: dict = Depends(require_permission("submissions"))):'),
     
    (r'@app\.get\(\"/admin/config\", response_class=HTMLResponse\)\nasync def config_panel\(request: Request, user: dict = Depends\(verify_admin\)',
     r'@app.get("/admin/config", response_class=HTMLResponse)\nasync def config_panel(request: Request, user: dict = Depends(require_permission("config")'),
     
    (r'@app\.get\(\"/admin/knowledge\", response_class=HTMLResponse\)\nasync def knowledge_panel\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/knowledge", response_class=HTMLResponse)\nasync def knowledge_panel(request: Request, user: dict = Depends(require_permission("config"))):'),
     
    (r'@app\.get\(\"/admin/company\", response_class=HTMLResponse\)\nasync def company_panel\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/company", response_class=HTMLResponse)\nasync def company_panel(request: Request, user: dict = Depends(require_permission("config"))):'),
     
    (r'@app\.get\(\"/admin/appointments/config\", response_class=HTMLResponse\)\nasync def appointments_config_panel\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/appointments/config", response_class=HTMLResponse)\nasync def appointments_config_panel(request: Request, user: dict = Depends(require_permission("config"))):'),
     
    (r'@app\.post\(\"/admin/knowledge/add\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/knowledge/add", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.get\(\"/admin/knowledge/remove-media/\{item_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/knowledge/remove-media/{item_id}", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.get\(\"/admin/knowledge/get/\{item_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/knowledge/get/{item_id}", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.post\(\"/admin/knowledge/update\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/knowledge/update", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.post\(\"/admin/whatsapp/sync-webhooks\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/whatsapp/sync-webhooks", dependencies=[Depends(require_permission("channels"))])'),
     
    (r'@app\.get\(\"/admin/playground\", response_class=HTMLResponse, dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/playground", response_class=HTMLResponse, dependencies=[Depends(require_permission("playground"))])'),
     
    (r'@app\.post\(\"/admin/playground/send\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/playground/send", dependencies=[Depends(require_permission("playground"))])'),
     
    (r'@app\.post\(\"/admin/config/save-all\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/config/save-all", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.get\(\"/admin/config/remove-welcome-media\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/config/remove-welcome-media", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.post\(\"/admin/config/upload-service-account\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/config/upload-service-account", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.get\(\"/admin/knowledge/delete/\{item_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/knowledge/delete/{item_id}", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.post\(\"/admin/proceedings/add\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/proceedings/add", dependencies=[Depends(require_permission("proceedings"))])'),
     
    (r'@app\.get\(\"/admin/submissions/delete/\{sub_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/submissions/delete/{sub_id}", dependencies=[Depends(require_permission("submissions"))])'),
     
    (r'@app\.get\(\"/admin/proceedings/delete/\{proc_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/proceedings/delete/{proc_id}", dependencies=[Depends(require_permission("proceedings"))])'),
     
    (r'@app\.post\(\"/admin/system/reset-total\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/system/reset-total", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.post\(\"/admin/files/upload\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/files/upload", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.get\(\"/admin/files/delete/\{filename\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/files/delete/{filename}", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.post\(\"/admin/config/sync\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.post("/admin/config/sync", dependencies=[Depends(require_permission("config"))])'),
     
    (r'@app\.get\(\"/admin/gaps\", response_class=HTMLResponse\)\nasync def view_gaps\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/gaps", response_class=HTMLResponse)\nasync def view_gaps(request: Request, user: dict = Depends(require_permission("gaps"))):'),
     
    (r'@app\.get\(\"/admin/gaps/resolve/\{gap_id\}\", dependencies=\[Depends\(verify_admin\)\]\)',
     r'@app.get("/admin/gaps/resolve/{gap_id}", dependencies=[Depends(require_permission("gaps"))])'),
     
    (r'@app\.get\(\"/admin/audit\", response_class=HTMLResponse\)\nasync def view_audit\(request: Request, user: dict = Depends\(verify_admin\)\):',
     r'@app.get("/admin/audit", response_class=HTMLResponse)\nasync def view_audit(request: Request, user: dict = Depends(require_permission("audit"))):')
]

for pat, repl in replacements:
    content = re.sub(pat, repl, content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Reemplazo finalizado.")
