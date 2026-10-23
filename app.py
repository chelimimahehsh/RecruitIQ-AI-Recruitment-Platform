from flask import Flask, request, jsonify
from flask_cors import CORS
import docx
import zipfile
import io
import os
import json
import uuid
from datetime import datetime
from pdfminer.high_level import extract_text

app = Flask(__name__)
CORS(app)

# ─── STORAGE ─────────────────────────────────────────────────────────────────────
# Tracker data is stored in a local JSON file so it survives server restarts.

TRACKER_FILE = os.path.join(os.path.dirname(__file__), "tracker_data.json")

def load_tracker():
    if not os.path.exists(TRACKER_FILE):
        return {}
    try:
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_tracker(data):
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── PROVIDER HELPERS ────────────────────────────────────────────────────────────

def get_anthropic_client(api_key):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)

def get_openai_client(api_key, base_url=None):
    from openai import OpenAI
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


# ─── TEXT EXTRACTION HELPERS ─────────────────────────────────────────────────────

def extract_text_from_bytes(file_bytes, filename):
    filename_lower = filename.lower()
    try:
        if filename_lower.endswith('.pdf'):
            text = extract_text(io.BytesIO(file_bytes))
        elif filename_lower.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([para.text for para in doc.paragraphs])
        elif filename_lower.endswith('.txt'):
            text = file_bytes.decode('utf-8', errors='replace')
        else:
            text = file_bytes.decode('utf-8', errors='replace')
        return text.strip()
    except Exception as e:
        raise ValueError(f"Failed to extract {filename}: {e}")


# ─── TEXT EXTRACTION ─────────────────────────────────────────────────────────────

@app.route('/extract-text', methods=['POST'])
def extract_resume_text():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    try:
        file_bytes = file.read()
        text = extract_text_from_bytes(file_bytes, file.filename)
        return jsonify({"text": text})
    except Exception as e:
        print(f"Extraction Error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── ZIP EXTRACTION ───────────────────────────────────────────────────────────────

@app.route('/extract-zip', methods=['POST'])
def extract_zip():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    if not file.filename.lower().endswith('.zip'):
        return jsonify({"error": "File must be a .zip"}), 400

    results = []
    errors  = []
    supported_exts = {'.pdf', '.docx', '.txt'}

    try:
        zip_bytes = file.read()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for entry in zf.infolist():
                name     = entry.filename
                basename = os.path.basename(name)
                if entry.is_dir() or basename.startswith('.') or '__MACOSX' in name or not basename:
                    continue
                ext = os.path.splitext(basename)[1].lower()
                if ext not in supported_exts:
                    continue
                try:
                    file_bytes = zf.read(entry.filename)
                    text = extract_text_from_bytes(file_bytes, basename)
                    if text:
                        results.append({"name": basename, "text": text})
                    else:
                        errors.append(f"{basename}: empty content")
                except Exception as e:
                    errors.append(f"{basename}: {str(e)}")
        return jsonify({"files": results, "errors": errors, "count": len(results)})
    except zipfile.BadZipFile:
        return jsonify({"error": "Invalid or corrupted ZIP file"}), 400
    except Exception as e:
        print(f"ZIP Extraction Error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── AI ANALYSIS ─────────────────────────────────────────────────────────────────

@app.route('/analyze', methods=['POST'])
def analyze_resumes():
    data = request.json
    if not data or 'prompt' not in data:
        return jsonify({"error": "No prompt provided"}), 400

    provider = data.get('provider', 'claude').lower()
    api_key  = data.get('api_key', '').strip()

    if not api_key:
        return jsonify({"error": "No API key provided. Enter your key in Settings."}), 400

    try:
        if provider == 'claude':
            client  = get_anthropic_client(api_key)
            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                messages=[{"role": "user", "content": data['prompt']}]
            )
            text = message.content[0].text

        elif provider == 'openai':
            client = get_openai_client(api_key)
            resp   = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": data['prompt']}],
                temperature=0
            )
            text = resp.choices[0].message.content

        elif provider == 'gemini':
            client = get_openai_client(api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
            resp   = client.chat.completions.create(
                model="gemini-2.0-flash",
                messages=[{"role": "user", "content": data['prompt']}],
                temperature=0
            )
            text = resp.choices[0].message.content

        elif provider == 'grok':
            client = get_openai_client(api_key, base_url="https://api.x.ai/v1")
            resp   = client.chat.completions.create(
                model="grok-3-mini",
                messages=[{"role": "user", "content": data['prompt']}],
                temperature=0
            )
            text = resp.choices[0].message.content

        elif provider == 'groq':
            client = get_openai_client(api_key, base_url="https://api.groq.com/openai/v1")
            resp   = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": data['prompt']}],
                temperature=0
            )
            text = resp.choices[0].message.content

        else:
            return jsonify({"error": f"Unknown provider: {provider}"}), 400

        return jsonify({"content": [{"text": text}]})

    except Exception as e:
        print(f"API Error [{provider}]: {e}")
        err = str(e)
        if any(w in err.lower() for w in ['auth', '401', 'invalid_api_key', 'incorrect']):
            return jsonify({"error": f"Invalid API key for {provider.title()}. Please check and try again."}), 401
        return jsonify({"error": err}), 500


# ─── CANDIDATE TRACKER ───────────────────────────────────────────────────────────
#
#  Each tracked candidate record looks like this:
#
#  {
#    "id":                "uuid-string",
#    "name":              "Jane Smith",
#    "role":              "Senior Backend Engineer",
#    "score":             87,
#    "screeningDecision": "Shortlisted",
#    "strengths":         ["Python", "AWS"],
#    "gaps":              ["Kubernetes"],
#    "reason":            "Strong match on core skills...",
#    "addedAt":           "2025-01-15T10:30:00",
#    "stage":             "interviewed",   # pending|called|interviewed|offered|hired|rejected
#    "callLog": [
#      {
#        "id":      "log-uuid",
#        "date":    "2025-01-16",
#        "note":    "Called — answered all technical questions well",
#        "outcome": "positive"            # positive|neutral|negative
#      }
#    ],
#    "scores": {
#      "technical":       8.5,
#      "communication":   7.0,
#      "problemSolving":  9.0,
#      "cultural":        8.0
#    },
#    "finalDecision":     "hire",         # hire|hold|reject|""
#    "generalNotes":      "Follow up re: salary"
#  }
#
# ─────────────────────────────────────────────────────────────────────────────────

@app.route('/tracker', methods=['GET'])
def get_all_tracked():
    """Return all tracked candidates."""
    tracker = load_tracker()
    return jsonify({"candidates": list(tracker.values()), "count": len(tracker)})


@app.route('/tracker', methods=['POST'])
def add_tracked():
    """Add a new candidate to the tracker. Returns 409 if already tracked."""
    body = request.json or {}
    name = body.get('name', '').strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    tracker = load_tracker()
    role    = body.get('role', '').strip()

    # Prevent duplicates by name + role
    duplicate = next(
        (c for c in tracker.values() if c['name'] == name and c.get('role') == role), None
    )
    if duplicate:
        return jsonify({"error": "already_tracked", "candidate": duplicate}), 409

    cid    = str(uuid.uuid4())
    record = {
        "id":                cid,
        "name":              name,
        "role":              role,
        "score":             body.get('score', 0),
        "screeningDecision": body.get('screeningDecision', ''),
        "strengths":         body.get('strengths', []),
        "gaps":              body.get('gaps', []),
        "reason":            body.get('reason', ''),
        "addedAt":           datetime.utcnow().isoformat(),
        "stage":             "pending",
        "callLog":           [],
        "scores": {
            "technical":      "",
            "communication":  "",
            "problemSolving": "",
            "cultural":       ""
        },
        "finalDecision":     "",
        "generalNotes":      ""
    }
    tracker[cid] = record
    save_tracker(tracker)
    print(f"[Tracker] Added   : {name}  id={cid}")
    return jsonify({"candidate": record}), 201


@app.route('/tracker/<cid>', methods=['GET'])
def get_tracked(cid):
    """Return a single tracked candidate by ID."""
    tracker = load_tracker()
    candidate = tracker.get(cid)
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404
    return jsonify({"candidate": candidate})


@app.route('/tracker/<cid>', methods=['PATCH'])
def update_tracked(cid):
    """
    Partially update a candidate.
    Accepted fields: stage, finalDecision, generalNotes, scores (dict).
    """
    tracker = load_tracker()
    if cid not in tracker:
        return jsonify({"error": "Candidate not found"}), 404

    body    = request.json or {}
    record  = tracker[cid]
    allowed = {'stage', 'finalDecision', 'generalNotes', 'scores'}

    for key in allowed:
        if key in body:
            if key == 'scores' and isinstance(body[key], dict):
                record['scores'].update(body[key])   # merge, not overwrite
            else:
                record[key] = body[key]

    record['updatedAt'] = datetime.utcnow().isoformat()
    tracker[cid] = record
    save_tracker(tracker)
    print(f"[Tracker] Updated : {record['name']}  fields={list(body.keys())}")
    return jsonify({"candidate": record})


@app.route('/tracker/<cid>', methods=['DELETE'])
def delete_tracked(cid):
    """Remove a candidate from the tracker permanently."""
    tracker = load_tracker()
    if cid not in tracker:
        return jsonify({"error": "Candidate not found"}), 404
    name = tracker[cid]['name']
    del tracker[cid]
    save_tracker(tracker)
    print(f"[Tracker] Removed : {name}  id={cid}")
    return jsonify({"deleted": True, "id": cid})


# ─── CALL / INTERVIEW LOG ────────────────────────────────────────────────────────

@app.route('/tracker/<cid>/log', methods=['POST'])
def add_log(cid):
    """
    Append a call or interview log entry to a candidate.
    Body: { date, note, outcome }
    """
    tracker = load_tracker()
    if cid not in tracker:
        return jsonify({"error": "Candidate not found"}), 404

    body = request.json or {}
    note = body.get('note', '').strip()
    if not note:
        return jsonify({"error": "note is required"}), 400

    entry = {
        "id":      str(uuid.uuid4()),
        "date":    body.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
        "note":    note,
        "outcome": body.get('outcome', 'neutral'),   # positive | neutral | negative
        "addedAt": datetime.utcnow().isoformat()
    }

    tracker[cid]['callLog'].append(entry)
    tracker[cid]['updatedAt'] = datetime.utcnow().isoformat()
    save_tracker(tracker)
    print(f"[Tracker] Log added: {tracker[cid]['name']}  outcome={entry['outcome']}")
    return jsonify({"entry": entry, "callLog": tracker[cid]['callLog']}), 201


@app.route('/tracker/<cid>/log/<log_id>', methods=['DELETE'])
def delete_log_entry(cid, log_id):
    """Delete one log entry from a candidate's call log."""
    tracker = load_tracker()
    if cid not in tracker:
        return jsonify({"error": "Candidate not found"}), 404

    before = len(tracker[cid]['callLog'])
    tracker[cid]['callLog'] = [e for e in tracker[cid]['callLog'] if e['id'] != log_id]

    if len(tracker[cid]['callLog']) == before:
        return jsonify({"error": "Log entry not found"}), 404

    tracker[cid]['updatedAt'] = datetime.utcnow().isoformat()
    save_tracker(tracker)
    return jsonify({"deleted": True, "log_id": log_id})


# ─── TRACKER STATS / DASHBOARD ───────────────────────────────────────────────────

@app.route('/tracker/stats', methods=['GET'])
def tracker_stats():
    """
    Aggregate stats for a dashboard view.
    Returns pipeline counts, decision counts, and average interview scores.
    """
    tracker    = load_tracker()
    candidates = list(tracker.values())
    total      = len(candidates)

    stages = {
        s: sum(1 for c in candidates if c.get('stage') == s)
        for s in ['pending', 'called', 'interviewed', 'offered', 'hired', 'rejected']
    }

    decisions = {
        d: sum(1 for c in candidates if c.get('finalDecision') == d)
        for d in ['hire', 'hold', 'reject']
    }

    # Average interview scores across candidates who have any score entered
    score_keys = ['technical', 'communication', 'problemSolving', 'cultural']
    avg_scores = {}
    for key in score_keys:
        vals = [
            float(c['scores'][key])
            for c in candidates
            if c.get('scores', {}).get(key) not in ('', None)
            and str(c['scores'][key]).strip() != ''
        ]
        avg_scores[key] = round(sum(vals) / len(vals), 2) if vals else None

    # Top 5 candidates by final_score for quick reference
    top = sorted(candidates, key=lambda c: float(c.get('score', 0)), reverse=True)[:5]
    top_summary = [{"name": c['name'], "role": c['role'], "score": c['score'], "stage": c['stage']} for c in top]

    return jsonify({
        "total":      total,
        "stages":     stages,
        "decisions":  decisions,
        "avgScores":  avg_scores,
        "topCandidates": top_summary
    })



# ─── SHARED CANDIDATES (RECRUITER → TL) ─────────────────────────────────────

SHARED_FILE = os.path.join(os.path.dirname(__file__), "shared_candidates.json")

def load_shared():
    if not os.path.exists(SHARED_FILE):
        return []
    try:
        with open(SHARED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_shared(data):
    with open(SHARED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@app.route('/shared', methods=['GET'])
def get_shared_candidates():
    """Return all shared candidates. Optionally filter by ?tl=name or ?pending=true"""
    shared = load_shared()
    tl = request.args.get('tl')
    pending = request.args.get('pending')
    if tl:
        shared = [s for s in shared if s.get('sharedTo') == tl]
    if pending == 'true':
        shared = [s for s in shared if not s.get('tlDecision')]
    return jsonify({"shared": shared, "count": len(shared)})


@app.route('/shared', methods=['POST'])
def share_candidate():
    """Share a candidate to a Team Leader."""
    body = request.json or {}
    required = ['candidateName', 'role', 'sharedTo']
    for field in required:
        if not body.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    shared = load_shared()
    record = {
        "id":            "share-" + str(uuid.uuid4())[:8],
        "candidateName": body['candidateName'],
        "role":          body['role'],
        "score":         body.get('score', 0),
        "decision":      body.get('decision', ''),
        "reason":        body.get('reason', ''),
        "strengths":     body.get('strengths', []),
        "gaps":          body.get('gaps', []),
        "screeningData": body.get('screeningData'),
        "recruiterNotes":body.get('recruiterNotes', ''),
        "sharedItems":   body.get('sharedItems', {}),
        "sharedTo":      body['sharedTo'],
        "sharedAt":      datetime.utcnow().isoformat(),
        "tlDecision":    "",
        "tlComments":    [],
        "tlDecidedAt":   None,
        "trackerCandId": body.get('trackerCandId')
    }
    shared.append(record)
    save_shared(shared)
    print(f"[Shared] {record['candidateName']} → {record['sharedTo']}")
    return jsonify({"record": record}), 201


@app.route('/shared/<share_id>/decision', methods=['PATCH'])
def set_tl_decision(share_id):
    """TL sets or updates their decision on a shared candidate."""
    shared = load_shared()
    record = next((s for s in shared if s['id'] == share_id), None)
    if not record:
        return jsonify({"error": "Shared record not found"}), 404

    body = request.json or {}
    valid_decisions = {'track', 'proceed', 'hold', 'moreinfo', 'drop', 'reject', ''}
    decision = body.get('decision', '')
    if decision not in valid_decisions:
        return jsonify({"error": f"Invalid decision. Must be one of: {valid_decisions}"}), 400

    record['tlDecision'] = decision
    record['tlDecidedAt'] = datetime.utcnow().isoformat()
    save_shared(shared)
    print(f"[TL Decision] {record['candidateName']}: {decision}")
    return jsonify({"record": record})


@app.route('/shared/<share_id>/comment', methods=['POST'])
def add_tl_comment(share_id):
    """Add a recruiter or TL comment to a shared candidate thread."""
    shared = load_shared()
    record = next((s for s in shared if s['id'] == share_id), None)
    if not record:
        return jsonify({"error": "Shared record not found"}), 404

    body = request.json or {}
    text = body.get('text', '').strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    comment = {
        "id":     str(uuid.uuid4()),
        "author": body.get('author', 'Recruiter'),
        "role":   body.get('role', 'recruiter'),
        "text":   text,
        "time":   datetime.utcnow().isoformat()
    }
    if 'tlComments' not in record:
        record['tlComments'] = []
    record['tlComments'].append(comment)
    save_shared(shared)
    return jsonify({"comment": comment, "thread": record['tlComments']}), 201


# ─── SCREENING DATA ───────────────────────────────────────────────────────────

@app.route('/tracker/<cid>/screening', methods=['GET'])
def get_screening(cid):
    """Return screening call data for a candidate."""
    tracker = load_tracker()
    if cid not in tracker:
        return jsonify({"error": "Candidate not found"}), 404
    return jsonify({"screeningData": tracker[cid].get('screeningData', {})})


@app.route('/tracker/<cid>/screening', methods=['POST'])
def save_screening(cid):
    """Save screening call data for a candidate."""
    tracker = load_tracker()
    if cid not in tracker:
        return jsonify({"error": "Candidate not found"}), 404

    body = request.json or {}
    tracker[cid]['screeningData'] = {
        "location":      body.get('location', ''),
        "workmode":      body.get('workmode', ''),
        "availability":  body.get('availability', ''),
        "startdate":     body.get('startdate', ''),
        "company":       body.get('company', ''),
        "experience":    body.get('experience', ''),
        "currentSalary": body.get('currentSalary', ''),
        "expectedSalary":body.get('expectedSalary', ''),
        "notice":        body.get('notice', ''),
        "reasonChange":  body.get('reasonChange', ''),
        "q1":            body.get('q1', ''),
        "q2":            body.get('q2', ''),
        "q3":            body.get('q3', ''),
        "ratings":       body.get('ratings', {}),
        "recruiterNotes":body.get('recruiterNotes', ''),
        "interest":      body.get('interest', ''),
        "decision":      body.get('decision', ''),
        "savedAt":       datetime.utcnow().isoformat()
    }
    # Update stage based on decision
    sc_decision = body.get('decision', '')
    if sc_decision == 'shortlist':
        tracker[cid]['stage'] = 'interviewed'
    elif sc_decision == 'reject':
        tracker[cid]['stage'] = 'rejected'

    tracker[cid]['updatedAt'] = datetime.utcnow().isoformat()
    save_tracker(tracker)
    print(f"[Screening] Saved for {tracker[cid]['name']}")
    return jsonify({"screeningData": tracker[cid]['screeningData']})


# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────

NOTIF_FILE = os.path.join(os.path.dirname(__file__), "notifications.json")

def load_notifs():
    if not os.path.exists(NOTIF_FILE):
        return []
    try:
        with open(NOTIF_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_notifs(data):
    with open(NOTIF_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@app.route('/notifications', methods=['GET'])
def get_notifications():
    """Return notifications. ?role=recruiter|tl to filter."""
    notifs = load_notifs()
    role = request.args.get('role')
    if role:
        notifs = [n for n in notifs if n.get('role') == role or n.get('role') == 'all']
    return jsonify({"notifications": notifs[:50]})


@app.route('/notifications', methods=['POST'])
def add_notification():
    """Add a new notification."""
    body = request.json or {}
    notifs = load_notifs()
    notif = {
        "id":      str(uuid.uuid4()),
        "icon":    body.get('icon', 'ℹ'),
        "msg":     body.get('msg', ''),
        "role":    body.get('role', 'all'),  # recruiter | tl | all
        "read":    False,
        "time":    datetime.utcnow().isoformat()
    }
    notifs.insert(0, notif)
    notifs = notifs[:100]  # Keep last 100
    save_notifs(notifs)
    return jsonify({"notification": notif}), 201


@app.route('/notifications/read', methods=['PATCH'])
def mark_notifs_read():
    """Mark all notifications as read for a role."""
    notifs = load_notifs()
    role = (request.json or {}).get('role', 'all')
    for n in notifs:
        if n.get('role') == role or n.get('role') == 'all' or role == 'all':
            n['read'] = True
    save_notifs(notifs)
    return jsonify({"updated": True})


# ─── PIPELINE STATUS ──────────────────────────────────────────────────────────

PIPELINE_STAGES_ORDER = [
    'uploaded','analyzed','ranked','pending','called','messaged',
    'replied','interviewed','screened','notes_added','shortlisted',
    'shared_tl','tl_review','track','confirmed','interview_scheduled',
    'interview_done','selected','offer_sent','hired'
]

@app.route('/tracker/<cid>/pipeline', methods=['GET'])
def get_pipeline(cid):
    """Return full pipeline stage info for a candidate."""
    tracker = load_tracker()
    if cid not in tracker:
        return jsonify({"error": "Candidate not found"}), 404

    c = tracker[cid]
    current_stage = c.get('stage', 'pending')

    # Map tracker stage to pipeline index
    stage_map = {
        'pending': 3, 'called': 4, 'interviewed': 7,
        'offered': 18, 'hired': 19, 'rejected': 19
    }
    current_idx = stage_map.get(current_stage, 3)

    pipeline = []
    for i, stage_key in enumerate(PIPELINE_STAGES_ORDER):
        state = 'done' if i < current_idx else ('active' if i == current_idx else 'pending')
        pipeline.append({"key": stage_key, "state": state, "index": i})

    return jsonify({"pipeline": pipeline, "currentStage": current_stage, "currentIndex": current_idx})


# ─── HEALTH CHECK ────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    tracker = load_tracker()
    shared  = load_shared()
    notifs  = load_notifs()
    return jsonify({
        "status":             "ok",
        "trackerCount":       len(tracker),
        "sharedCount":        len(shared),
        "notificationCount":  len(notifs),
        "pendingTLReview":    len([s for s in shared if not s.get('tlDecision')]),
        "trackerFile":        TRACKER_FILE,
        "sharedFile":         SHARED_FILE,
        "notifFile":          NOTIF_FILE,
    })


# ─── RUN ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 64)
    print("  RecruitIQ Backend — Full Recruitment Platform")
    print("  AI Providers  : Claude · OpenAI · Gemini · Grok · Groq")
    print("  Features      : Resume extract · ZIP bulk · Candidate Tracker")
    print("                  Screening Calls · Share to TL · TL Dashboard")
    print("                  Notifications · Pipeline Status · Offer Flow")
    print("  Storage       : tracker_data.json · shared_candidates.json")
    print("                  notifications.json")
    print("  Running at    : http://127.0.0.1:5000")
    print("=" * 64)
    existing = len(load_tracker())
    shared   = len(load_shared())
    if existing:
        print(f"  Tracker       : {existing} candidate(s) on file")
    if shared:
        print(f"  Shared Queue  : {shared} candidate(s) shared to TL")
    print("=" * 64)
    app.run(host='127.0.0.1', port=5000, debug=False)