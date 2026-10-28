"""Generate the two importable n8n workflows into n8n/. Re-run after editing: python scripts/build_n8n_workflows.py"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "n8n"
OUT.mkdir(exist_ok=True)


def node(id_, name, type_, version, pos, params, **extra):
    n = {"parameters": params, "id": id_, "name": name, "type": type_, "typeVersion": version, "position": pos}
    n.update(extra)
    return n


def set_node(id_, name, pos, label, expr):
    return node(id_, name, "n8n-nodes-base.set", 3.4, pos, {"assignments": {"assignments": [
        {"id": id_ + "-a", "name": "notification_mode", "value": "TEST_ONLY until the Discord node is enabled", "type": "string"},
        {"id": id_ + "-b", "name": "notification_text", "value": expr, "type": "string"},
        {"id": id_ + "-c", "name": "event_label", "value": label, "type": "string"}]}, "options": {}})


def discord_node(id_, pos):
    return node(id_, "Send Discord Message (optional)", "n8n-nodes-base.httpRequest", 4.2, pos, {
        "method": "POST", "url": "REPLACE_WITH_YOUR_DISCORD_WEBHOOK_URL", "sendBody": True, "contentType": "json",
        "specifyBody": "json", "jsonBody": "={{ JSON.stringify({ content: $json.notification_text }) }}", "options": {"timeout": 10000}},
        disabled=True, onError="continueRegularOutput")


def sticky(id_, pos, text, w=420, h=140):
    return node(id_, "Note " + id_, "n8n-nodes-base.stickyNote", 1, pos, {"content": text, "height": h, "width": w})


def link(*names):
    return [{"node": n, "type": "main", "index": 0} for n in names]


# ------------------------------------------------------------------ 1. outbound: app -> n8n
validate_js = """const body = $input.first().json.body ?? {};
const allowed = ['Pending Review', 'Shortlisted', 'Further Review Required'];
const keys = ['candidate_id', 'job_id', 'status', 'timestamp'];
const extra = Object.keys(body).filter(k => !keys.includes(k));
const valid = Number.isInteger(body.candidate_id) && Number.isInteger(body.job_id)
  && allowed.includes(body.status) && typeof body.timestamp === 'string'
  && !isNaN(Date.parse(body.timestamp)) && extra.length === 0;
return [{ json: valid
  ? { valid: true, route: body.status, candidate_id: body.candidate_id, job_id: body.job_id, status: body.status, timestamp: body.timestamp }
  : { valid: false, route: 'invalid', error: 'Invalid payload: expected exactly candidate_id (int), job_id (int), status (known review status), timestamp (ISO string)' } }];"""
msg = lambda what: "={{ '[TEST ONLY] Candidate #' + $json.candidate_id + ' / job #' + $json.job_id + ' " + what + " at ' + $json.timestamp }}"
rule = lambda v, o: {"value2": v, "output": o}
out1 = {
    "name": "TalentOps AI - 1 Outbound screening events",
    "nodes": [
        node("o-webhook", "Screening Webhook", "n8n-nodes-base.webhook", 2, [0, 260],
             {"httpMethod": "POST", "path": "talentops-screening", "responseMode": "responseNode", "options": {}},
             webhookId="talentops-screening-demo"),
        node("o-validate", "Validate Payload", "n8n-nodes-base.code", 2, [220, 260], {"language": "javaScript", "jsCode": validate_js}),
        node("o-route", "Route by Status", "n8n-nodes-base.switch", 1, [440, 260], {
            "dataType": "string", "value1": "={{ $json.route }}",
            "rules": {"rules": [rule("Shortlisted", 0), rule("Pending Review", 1), rule("Further Review Required", 2), rule("invalid", 3)]}}),
        set_node("o-s1", "Prepare Shortlisted Notice", [700, 80], "shortlisted", msg("was SHORTLISTED by a human reviewer")),
        set_node("o-s2", "Prepare Pending Notice", [700, 260], "pending_review", msg("is awaiting recruiter review")),
        set_node("o-s3", "Prepare Further Review Notice", [700, 440], "further_review", msg("needs FURTHER REVIEW")),
        node("o-ok", "Respond 200", "n8n-nodes-base.respondToWebhook", 1.1, [980, 260], {
            "respondWith": "json", "responseBody": "={{ { \"received\": true, \"route\": $json.event_label } }}", "options": {"responseCode": 200}}),
        discord_node("o-discord", [980, 440]),
        node("o-bad", "Respond 400 Invalid", "n8n-nodes-base.respondToWebhook", 1.1, [700, 620], {
            "respondWith": "json", "responseBody": "={{ { \"received\": false, \"error\": $json.error } }}", "options": {"responseCode": 400}}),
        sticky("o-note", [0, 40], "OUTBOUND: TalentOps AI -> n8n. Receives only {candidate_id, job_id, status, timestamp}. "
               "Any extra field (e.g. an email) is rejected on purpose. The Discord node is DISABLED by default: paste your "
               "webhook URL and enable it to get a real notification."),
    ],
    "connections": {
        "Screening Webhook": {"main": [link("Validate Payload")]},
        "Validate Payload": {"main": [link("Route by Status")]},
        "Route by Status": {"main": [link("Prepare Shortlisted Notice"), link("Prepare Pending Notice"),
                                     link("Prepare Further Review Notice"), link("Respond 400 Invalid")]},
        "Prepare Shortlisted Notice": {"main": [link("Respond 200", "Send Discord Message (optional)")]},
        "Prepare Pending Notice": {"main": [link("Respond 200", "Send Discord Message (optional)")]},
        "Prepare Further Review Notice": {"main": [link("Respond 200", "Send Discord Message (optional)")]},
    },
    "settings": {"executionOrder": "v1"}, "active": False, "pinData": {},
}

# ------------------------------------------------------------------ 2. inbound: folder -> n8n -> app
intake_expr = "={{ $json.error ? 'error' : ($json.duplicate ? 'duplicate' : 'ok') }}"
out2 = {
    "name": "TalentOps AI - 2 Inbound resume intake",
    "nodes": [
        node("i-trigger", "Watch Resume Inbox Folder", "n8n-nodes-base.localFileTrigger", 1, [0, 260], {
            "triggerOn": "folder", "path": "C:\\talentops-inbox", "events": ["add"],
            "options": {"awaitWriteFinish": True, "usePolling": True}}),
        node("i-read", "Read Resume File", "n8n-nodes-base.readWriteFile", 1, [240, 260], {
            "operation": "read", "fileSelector": "={{ $json.path }}", "options": {"dataPropertyName": "data"}}),
        node("i-http", "Send To TalentOps API", "n8n-nodes-base.httpRequest", 4.2, [480, 260], {
            "method": "POST", "url": "http://127.0.0.1:8000/api/inbound/resume", "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "X-API-Key", "value": "REPLACE_WITH_TALENTOPS_INBOUND_TOKEN"}]},
            "sendBody": True, "contentType": "multipart-form-data",
            "bodyParameters": {"parameters": [
                {"parameterType": "formBinaryData", "name": "file", "inputDataFieldName": "data"},
                {"name": "job_id", "value": "1"}]},
            "options": {"timeout": 60000}}, onError="continueRegularOutput"),
        node("i-route", "Route Result", "n8n-nodes-base.switch", 1, [720, 260], {
            "dataType": "string", "value1": intake_expr,
            "rules": {"rules": [rule("ok", 0), rule("duplicate", 1), rule("error", 2)]}}),
        set_node("i-s1", "Prepare Review Notice", [980, 100], "screened",
                 "={{ '[TEST ONLY] New resume screened: candidate #' + $json.candidate_id + ' for job #' + $json.job_id + "
                 "' - coverage score ' + $json.score + ' (' + $json.counts.matched + ' matched, ' + $json.counts.partial + "
                 "' partial, ' + $json.counts.insufficient + ' insufficient evidence). Awaiting HUMAN review in TalentOps AI.' }}"),
        set_node("i-s2", "Prepare Duplicate Notice", [980, 260], "duplicate",
                 "={{ '[TEST ONLY] Duplicate resume detected. Existing candidate #' + $json.candidate_id + ' was kept unchanged.' }}"),
        set_node("i-s3", "Prepare Failure Notice", [980, 420], "intake_failed",
                 "={{ '[TEST ONLY] Resume intake failed: ' + JSON.stringify($json.error).slice(0, 300) }}"),
        discord_node("i-discord", [1240, 260]),
        sticky("i-note", [0, 20], "INBOUND: drop a PDF/DOCX into C:\\talentops-inbox. n8n sends it to TalentOps AI, which parses and "
               "screens it. Set the API key and job_id in 'Send To TalentOps API'. Results land as 'Pending Review': "
               "a human decides. No decision is automated and the notice contains no resume text.", 520, 160),
    ],
    "connections": {
        "Watch Resume Inbox Folder": {"main": [link("Read Resume File")]},
        "Read Resume File": {"main": [link("Send To TalentOps API")]},
        "Send To TalentOps API": {"main": [link("Route Result")]},
        "Route Result": {"main": [link("Prepare Review Notice"), link("Prepare Duplicate Notice"), link("Prepare Failure Notice")]},
        "Prepare Review Notice": {"main": [link("Send Discord Message (optional)")]},
        "Prepare Duplicate Notice": {"main": [link("Send Discord Message (optional)")]},
        "Prepare Failure Notice": {"main": [link("Send Discord Message (optional)")]},
    },
    "settings": {"executionOrder": "v1"}, "active": False, "pinData": {},
}

for fname, wf in [("01_outbound_screening_events.json", out1), ("02_inbound_resume_intake.json", out2)]:
    names = {n["name"] for n in wf["nodes"]}
    for src, c in wf["connections"].items():
        assert src in names, src
        for branch in c["main"]:
            for t in branch:
                assert t["node"] in names, t["node"]
    (OUT / fname).write_text(json.dumps(wf, indent=2), encoding="utf-8")
    print("wrote", fname, len(wf["nodes"]), "nodes")
