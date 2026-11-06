//! Conversation-led experiments use the same participant journal as UI jobs.
//! Events are append-only; numerical tools register a round before they execute.
use anyhow::{Context, Result, ensure};
use fs2::FileExt;
use nc_core::{ArtifactStore, ContentId, read_bounded};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::Duration,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Attachment {
    pub label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<PathBuf>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub artifact: Option<ContentId>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub id: String,
    pub experiment: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub round: Option<String>,
    pub kind: String,
    #[serde(default)]
    pub historical: bool,
    /// Original evidence time, when known. Recorded time is always assigned by SQLite.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub occurred_at: Option<f64>,
    pub data: Value,
    #[serde(default)]
    pub attachments: Vec<Attachment>,
}

fn valid_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_".contains(&b))
}
fn connection(home: &Path) -> Result<Connection> {
    fs::create_dir_all(home)?;
    let c = Connection::open(home.join("journal.sqlite"))?;
    c.busy_timeout(Duration::from_secs(5))?;
    // Never open Journal::open here: its worker recovery is unrelated to research.
    c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS research_events (
          sequence INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
          experiment TEXT NOT NULL, round_id TEXT, kind TEXT NOT NULL,
          record TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE INDEX IF NOT EXISTS research_experiment ON research_events(experiment, sequence);")?;
    Ok(c)
}
pub fn read_event(path: &Path) -> Result<Event> {
    Ok(serde_json::from_slice(&read_bounded(path, 1024 * 1024)?)?)
}
fn validate(e: &Event) -> Result<()> {
    ensure!(
        valid_id(&e.id) && valid_id(&e.experiment) && e.round.as_deref().is_none_or(valid_id),
        "Invalid research identity"
    );
    ensure!(
        [
            "experiment",
            "round",
            "result",
            "decision",
            "status",
            "note"
        ]
        .contains(&e.kind.as_str()),
        "Invalid research event kind"
    );
    ensure!(
        e.data.is_object() && serde_json::to_vec(&e.data)?.len() <= 256 * 1024,
        "Research event must contain a bounded data object"
    );
    ensure!(
        e.occurred_at.is_none_or(|v| v.is_finite() && v >= 0.0),
        "Invalid original event time"
    );
    ensure!(e.attachments.len() <= 64, "Too many evidence attachments");
    if ["experiment", "status"].contains(&e.kind.as_str()) {
        ensure!(e.round.is_none(), "Experiment event cannot name a round");
    }
    if ["round", "result", "decision"].contains(&e.kind.as_str()) {
        ensure!(e.round.is_some(), "Round identity required");
    }
    let required: &[&str] = match e.kind.as_str() {
        "experiment" => &["name", "model", "objective"],
        "round" => &["label", "hypothesis", "kind"],
        "decision" => &["verdict", "reason"],
        "result" | "status" => &["status", "summary"],
        _ => &[],
    };
    for key in required {
        ensure!(
            e.data[*key].as_str().is_some_and(|s| !s.trim().is_empty()),
            "Missing research field: {key}"
        );
    }
    if e.kind == "status" {
        ensure!(
            ["in_progress", "completed", "rejected", "archived"]
                .contains(&e.data["status"].as_str().unwrap()),
            "Invalid experiment status"
        );
    }
    if e.kind == "result" {
        ensure!(
            ["completed", "awaiting_review", "failed", "interrupted"]
                .contains(&e.data["status"].as_str().unwrap()),
            "Invalid result status"
        );
    }
    if e.kind == "decision" {
        ensure!(
            [
                "accepted",
                "rejected",
                "not_selected",
                "not_promoted",
                "inconclusive"
            ]
            .contains(&e.data["verdict"].as_str().unwrap()),
            "Invalid decision verdict"
        );
    }
    for m in e.data["measurements"].as_array().into_iter().flatten() {
        ensure!(
            m["label"].is_string()
                && [
                    "development",
                    "selection",
                    "final",
                    "regression",
                    "diagnostic"
                ]
                .contains(&m["split"].as_str().unwrap_or("")),
            "Each measurement needs a label and split role"
        );
        if m.get("total").is_some() || m.get("correct").is_some() {
            let total = m["total"]
                .as_u64()
                .context("Measurement total must be a positive integer")?;
            ensure!(
                total > 0 && m["correct"].as_u64().is_some_and(|v| v <= total),
                "Invalid correct/total measurement"
            );
            ensure!(
                m.get("parent_correct")
                    .is_none_or(|v| v.as_u64().is_some_and(|v| v <= total)),
                "Invalid parent measurement"
            );
        }
    }
    Ok(())
}

pub fn record(home: &Path, mut e: Event) -> Result<Value> {
    validate(&e)?;
    let store = ArtifactStore::open(home.join("artifacts"))?;
    for a in &mut e.attachments {
        ensure!(
            !a.label.is_empty() && a.label.len() <= 256,
            "Invalid evidence label"
        );
        ensure!(
            a.path.is_some() != a.artifact.is_some(),
            "Evidence needs either a local path or an artifact identity"
        );
        if let Some(path) = a.path.take() {
            ensure!(path.is_absolute(), "Evidence paths must be absolute");
            a.artifact = Some(store.put(&read_bounded(&path, 16 * 1024 * 1024)?)?);
        } else {
            store.get(a.artifact.as_ref().unwrap())?;
        }
    }
    let serialized = serde_json::to_string(&e)?;
    let mut c = connection(home)?;
    let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let old: Option<String> = tx
        .query_row(
            "SELECT record FROM research_events WHERE id=?1",
            [&e.id],
            |r| r.get(0),
        )
        .optional()?;
    if let Some(old) = old {
        ensure!(
            old == serialized,
            "Event ID already bound to different content"
        );
        return Ok(json!({"id":e.id, "recorded":true, "duplicate":true}));
    }
    let exists = |kind: &str, round: Option<&str>| -> Result<bool> {
        Ok(tx.query_row("SELECT EXISTS(SELECT 1 FROM research_events WHERE experiment=?1 AND kind=?2 AND round_id IS ?3)", params![e.experiment, kind, round], |r| r.get(0))?)
    };
    if e.kind == "experiment" {
        ensure!(
            !exists("experiment", None)?,
            "Experiment already exists; append a status or note instead"
        );
    } else {
        ensure!(
            exists("experiment", None)?,
            "Register the experiment before recording its work"
        );
        if let Some(round) = &e.round {
            let known = exists("round", Some(round))?;
            ensure!(
                if e.kind == "round" { !known } else { known },
                "Round must be registered once, before its results"
            );
            if e.kind == "decision" {
                ensure!(
                    exists("result", Some(round))?,
                    "Record a result before its decision"
                );
            }
        }
    }
    tx.execute(
        "INSERT INTO research_events(id,experiment,round_id,kind,record) VALUES(?1,?2,?3,?4,?5)",
        params![e.id, e.experiment, e.round, e.kind, serialized],
    )?;
    let sequence = tx.last_insert_rowid();
    tx.commit()?;
    Ok(json!({"id":e.id,"sequence":sequence,"recorded":true,"duplicate":false}))
}

fn lock_path(home: &Path, experiment: &str, round: &str) -> PathBuf {
    home.join("research")
        .join(experiment)
        .join(format!("{round}.lock"))
}
fn executing(home: &Path, experiment: &str, round: &str) -> bool {
    let Ok(f) = OpenOptions::new()
        .read(true)
        .write(true)
        .open(lock_path(home, experiment, round))
    else {
        return false;
    };
    f.try_lock_exclusive().is_err()
}

pub fn list(home: &Path) -> Result<Value> {
    let c = connection(home)?;
    let mut statement =
        c.prepare("SELECT sequence,record,created_at FROM research_events ORDER BY sequence")?;
    let rows = statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
        ))
    })?;
    let mut experiments: BTreeMap<String, Value> = BTreeMap::new();
    for row in rows {
        let (sequence, record, created_at) = row?;
        let e: Event = serde_json::from_str(&record)?;
        if e.kind == "experiment" {
            experiments.insert(e.experiment.clone(), json!({"id":e.experiment,"definition":e.data,"status":"in_progress","summary":"Research in progress","rounds":[],"events":[],"created_at":created_at}));
        }
        let x = experiments
            .get_mut(&e.experiment)
            .context("Missing experiment definition")?;
        x["updated_at"] = json!(created_at);
        x["sequence"] = json!(sequence);
        if e.kind == "status" {
            x["status"] = e.data["status"].clone();
            x["summary"] = e.data["summary"].clone();
        }
        if let Some(round) = &e.round {
            let rounds = x["rounds"].as_array_mut().unwrap();
            if e.kind == "round" {
                rounds.push(json!({"id":round,"definition":e.data,"historical":e.historical,"occurred_at":e.occurred_at,"created_at":created_at,"status":if e.data["execution"] == "managed" { "running" } else { "recorded" },"events":[]}));
            }
            let r = rounds
                .iter_mut()
                .find(|r| r["id"] == *round)
                .context("Missing round definition")?;
            if e.kind == "result" {
                r["result"] = e.data.clone();
                r["status"] = e.data["status"].clone();
                // A corrected/new result needs a new review. Keep the old
                // decision in history without applying it to different evidence.
                r["decision"] = Value::Null;
            }
            if e.kind == "decision" {
                r["decision"] = e.data.clone();
            }
            r["events"]
                .as_array_mut()
                .unwrap()
                .push(json!({"sequence":sequence,"recorded_at":created_at,"event":e}));
        }
        x["events"]
            .as_array_mut()
            .unwrap()
            .push(json!({"sequence":sequence,"recorded_at":created_at,"event":e}));
    }
    let mut values: Vec<Value> = experiments.into_values().collect();
    for x in &mut values {
        let id = x["id"].as_str().unwrap().to_owned();
        for r in x["rounds"].as_array_mut().unwrap() {
            if r["status"] == "running" && !executing(home, &id, r["id"].as_str().unwrap()) {
                r["status"] = json!("interrupted");
                r["execution_note"] = json!(
                    "No worker holds this round’s execution lease. Its outcome was not recorded; it has not been restarted."
                );
            }
        }
    }
    values.sort_by_key(|v| {
        (
            v["status"] != "in_progress",
            std::cmp::Reverse(v["sequence"].as_i64().unwrap_or(0)),
        )
    });
    Ok(json!({"experiments":values}))
}

/// Own the command lifecycle, with a durable start before any numerical work.
/// A result file may contain normalized metrics; its original bytes are evidence too.
pub fn run(
    home: &Path,
    mut event: Event,
    command: &[String],
    result: Option<&Path>,
) -> Result<Value> {
    ensure!(
        event.kind == "round" && !event.historical && !command.is_empty(),
        "run requires a new live round and command"
    );
    validate(&event)?;
    let round = event
        .round
        .as_ref()
        .context("Missing round identity")?
        .clone();
    let path = lock_path(home, &event.experiment, &round);
    fs::create_dir_all(path.parent().unwrap())?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&path)?;
    lock.try_lock_exclusive()
        .context("Round is already executing")?;
    // Retrying a completed or interrupted invocation must never silently rerun it.
    let c = connection(home)?;
    let known: bool = c.query_row(
        "SELECT EXISTS(SELECT 1 FROM research_events WHERE experiment=?1 AND round_id=?2)",
        params![event.experiment, round],
        |r| r.get(0),
    )?;
    ensure!(
        !known,
        "Round already exists; use a new round ID for an explicit retry"
    );
    if let Some(result) = result {
        ensure!(
            !result.exists(),
            "Result path already exists; use a fresh output to avoid attaching stale results"
        );
    }
    event.data["execution"] = json!("managed");
    record(home, event.clone())?;
    let stdout = path.with_extension("stdout.log");
    let stderr = path.with_extension("stderr.log");
    let outcome = (|| -> Result<std::process::ExitStatus> {
        Ok(Command::new(&command[0])
            .args(&command[1..])
            // The child inherits the lease, so a killed wrapper cannot claim it stopped.
            .stdin(Stdio::from(lock.try_clone()?))
            .stdout(Stdio::from(File::create(&stdout)?))
            .stderr(Stdio::from(File::create(&stderr)?))
            .status()?)
    })();
    let mut data =
        json!({"status":"failed", "summary":"Numerical command failed; inspect its logs."});
    let mut attachments = vec![];
    for (label, path) in [("Command stdout", stdout), ("Command stderr", stderr)] {
        if path.is_file() && path.metadata()?.len() <= 16 * 1024 * 1024 {
            attachments.push(Attachment {
                label: label.into(),
                path: Some(fs::canonicalize(path)?),
                artifact: None,
            });
        }
    }
    match &outcome {
        Ok(status) => {
            data["exit_code"] = json!(status.code());
            if status.success() {
                data["status"] = json!("awaiting_review");
                data["summary"] =
                    json!("Command completed. Review measurements before accepting this change.");
            }
        }
        Err(error) => data["summary"] = json!(error.to_string()),
    }
    // A malformed/missing result never loses the recorded command outcome.
    if outcome.as_ref().is_ok_and(|s| s.success())
        && let Some(path) = result
    {
        match read_bounded(path, 1024 * 1024)
            .and_then(|bytes| Ok(serde_json::from_slice::<Value>(&bytes)?))
        {
            Ok(value) => {
                if serde_json::to_vec(&value)?.len() <= 64 * 1024 {
                    data["feedback"] = value;
                } else {
                    data["feedback_note"] =
                        json!("Full numerical feedback is preserved in the attached artifact.");
                }
                attachments.push(Attachment {
                    label: "Numerical feedback".into(),
                    path: Some(fs::canonicalize(path)?),
                    artifact: None,
                });
            }
            Err(error) => {
                data["status"] = json!("failed");
                data["summary"] = json!(format!(
                    "Command exited successfully but feedback is unavailable: {error}"
                ));
            }
        }
    }
    let failed = data["status"] == "failed";
    let recorded = record(
        home,
        Event {
            id: format!("{}-result", uuid::Uuid::new_v4()),
            experiment: event.experiment,
            round: Some(round),
            kind: "result".into(),
            historical: false,
            occurred_at: None,
            data,
            attachments,
        },
    )?;
    ensure!(
        !failed,
        "Research command failed; outcome and available logs are recorded in the app"
    );
    Ok(recorded)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn event(id: &str, round: Option<&str>, kind: &str, data: Value) -> Event {
        Event {
            id: id.into(),
            experiment: "test".into(),
            round: round.map(str::to_owned),
            kind: kind.into(),
            historical: false,
            occurred_at: None,
            data,
            attachments: vec![],
        }
    }
    fn init(home: &Path) {
        record(
            home,
            event(
                "init",
                None,
                "experiment",
                json!({"name":"Test","model":"test-model","objective":"Check tracking"}),
            ),
        )
        .unwrap();
    }
    #[test]
    fn history_is_append_only_and_evidence_is_copied() {
        let dir = tempfile::tempdir().unwrap();
        init(dir.path());
        let mut start = event(
            "r1",
            Some("r1"),
            "round",
            json!({"label":"Probe","hypothesis":"Test a change","kind":"probe"}),
        );
        let file = dir.path().join("evidence.json");
        fs::write(&file, b"{\"value\":1}").unwrap();
        start.attachments.push(Attachment {
            label: "Evidence".into(),
            path: Some(file.clone()),
            artifact: None,
        });
        record(dir.path(), start.clone()).unwrap();
        assert_eq!(
            record(dir.path(), start.clone()).unwrap()["duplicate"],
            true
        );
        fs::write(&file, b"{\"value\":2}").unwrap();
        assert!(record(dir.path(), start).is_err());
        assert!(
            record(
                dir.path(),
                event(
                    "bad",
                    Some("unknown"),
                    "result",
                    json!({"status":"completed","summary":"No start"})
                )
            )
            .is_err()
        );
        record(
            dir.path(),
            event(
                "result",
                Some("r1"),
                "result",
                json!({"status":"completed","summary":"Measured"}),
            ),
        )
        .unwrap();
        record(
            dir.path(),
            event(
                "reject",
                Some("r1"),
                "decision",
                json!({"verdict":"rejected","reason":"Regression"}),
            ),
        )
        .unwrap();
        let data = list(dir.path()).unwrap();
        let x = &data["experiments"][0];
        assert_eq!(x["rounds"][0]["decision"]["verdict"], "rejected");
        assert_eq!(x["events"].as_array().unwrap().len(), 4);
        let id: ContentId =
            serde_json::from_value(x["events"][1]["event"]["attachments"][0]["artifact"].clone())
                .unwrap();
        assert_eq!(
            ArtifactStore::open(dir.path().join("artifacts"))
                .unwrap()
                .get(&id)
                .unwrap(),
            b"{\"value\":1}"
        );
        record(
            dir.path(),
            event(
                "corrected-result",
                Some("r1"),
                "result",
                json!({"status":"completed","summary":"Corrected measurement"}),
            ),
        )
        .unwrap();
        assert!(list(dir.path()).unwrap()["experiments"][0]["rounds"][0]["decision"].is_null());
        assert!(record(dir.path(),event("invalid-count",Some("r1"),"result",json!({"status":"completed","summary":"Invalid","measurements":[{"label":"Accuracy","split":"selection","correct":1,"total":-1}]}))).is_err());
    }
    #[test]
    fn run_records_start_failure_and_prevents_duplicate_execution() {
        let dir = tempfile::tempdir().unwrap();
        init(dir.path());
        let e = event(
            "r",
            Some("r"),
            "round",
            json!({"label":"Probe","hypothesis":"Check failure","kind":"probe"}),
        );
        assert!(
            run(
                dir.path(),
                e.clone(),
                &["/bin/sh".into(), "-c".into(), "exit 7".into()],
                None
            )
            .is_err()
        );
        let x = list(dir.path()).unwrap();
        assert_eq!(x["experiments"][0]["rounds"][0]["status"], "failed");
        assert_eq!(x["experiments"][0]["rounds"][0]["result"]["exit_code"], 7);
        assert!(run(dir.path(), e, &["/usr/bin/true".into()], None).is_err());
    }
    #[test]
    fn absent_worker_is_interrupted_not_running_or_accepted() {
        let dir = tempfile::tempdir().unwrap();
        init(dir.path());
        record(dir.path(),event("r",Some("r"),"round",json!({"label":"Probe","hypothesis":"Check recovery","kind":"probe","execution":"managed"}))).unwrap();
        assert_eq!(
            list(dir.path()).unwrap()["experiments"][0]["rounds"][0]["status"],
            "interrupted"
        );
    }
}
