# Optional: n8n workflow (import and test)

> **Status honesty:** `n8n/talentops_screening_workflow.json` is a *generated* workflow file. Its JSON is valid and the
> payload-validation JavaScript was checked in Node.js, but **the workflow has not been imported into a running n8n
> instance by the author of this repo's initial version**. It counts as a *tested integration* only after you complete
> the checklist below and tick every box. The Python side (payload building, timeouts, failure handling) is covered by pytest.

The main app works without n8n. Leave `N8N_WEBHOOK_URL` empty to disable it.

## 1. Install n8n (needs Node.js 18+ LTS: https://nodejs.org/)
```powershell
node --version
npx n8n
```
Open http://localhost:5678 and create the local owner account. (Docker is not required.)

## 2. Import
n8n UI -> **Workflows** -> top-right menu -> **Import from file** -> choose `n8n/talentops_screening_workflow.json`.

## 3. Test (test URL first)
1. Open the workflow, double-click **Screening Webhook**, click **Listen for test event**. It shows a *Test URL*
   like `http://localhost:5678/webhook-test/talentops-screening`.
2. In a second PowerShell window:
```powershell
$body = @{ candidate_id = 1; job_id = 1; status = "Shortlisted"; timestamp = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:5678/webhook-test/talentops-screening" -ContentType "application/json" -Body $body
```
Expected: `received: True, route: shortlisted`, and the canvas shows the path through *Prepare Shortlisted Notice*.

3. Invalid payload (extra field = personal data is rejected on purpose):
```powershell
$bad = @{ candidate_id = 1; job_id = 1; status = "Shortlisted"; timestamp = (Get-Date).ToUniversalTime().ToString("o"); email = "x@example.com" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:5678/webhook-test/talentops-screening" -ContentType "application/json" -Body $bad
```
Expected: HTTP 400 `received: False`.

## 4. Connect TalentOps AI
Toggle the workflow **Active**, then use the *Production URL* (`/webhook/...`, not `/webhook-test/...`):
```powershell
Copy-Item .env.example .env
# edit .env:  N8N_WEBHOOK_URL=http://localhost:5678/webhook/talentops-screening
```
Restart the app, change a review status in the UI and check the **Workflow event history**: delivery should read `delivered`.
Stop n8n and change a status again: it should read `failed: ...` while the status change itself is still saved.

## Verification checklist (tick before claiming "tested")
- [ ] Imported without errors
- [ ] Valid payload returned 200 and routed correctly for all three statuses
- [ ] Invalid / extra-field payload returned 400
- [ ] App showed `delivered` with n8n running
- [ ] App showed `failed` but kept the record with n8n stopped

No emails or WhatsApp messages are sent: the *Prepare ... Notice* nodes only build test text.
