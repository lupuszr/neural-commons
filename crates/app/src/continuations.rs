//! Durable, single-flight controller jobs. The lease is inherited by the worker,
//! so an HTTP timeout or server restart cannot launch a duplicate controller.
use anyhow::{Context, Result, ensure};
use fs2::FileExt;
use nc_core::{ArtifactStore, ContentId, hash_file, read_bounded};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
pub enum WeightScope {
    All,
    Selected { tensors: Vec<String> },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub id: String,
    pub checkpoint: ContentId,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub proposal: Option<ContentId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub report: Option<ContentId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub objective: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instructions: Option<String>,
    // Missing only for older saved requests. New submissions must choose a scope.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub weight_scope: Option<WeightScope>,
    pub task_directory: PathBuf,
    pub backend: String,
    pub controller_model: String,
    pub max_rounds: u32,
    pub max_probes: u32,
    pub min_probes: u32,
    pub max_edit_elements: Option<u64>,
    pub timeout_seconds: u32,
}
pub const INPUTS: [&str; 7] = [
    "config.json",
    "development.json",
    "selection.json",
    "heldout.json",
    "policy.json",
    "source.json",
    "guard-config.json",
];
pub fn root(home: &Path) -> PathBuf {
    home.join("continuations")
}
fn file_lock(path: &Path) -> Result<File> {
    Ok(OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)?)
}
pub fn lease(home: &Path) -> Result<File> {
    fs::create_dir_all(root(home))?;
    let f = file_lock(&root(home).join("execution.lock"))?;
    f.try_lock_exclusive()
        .context("A controller or participant operation is still active")?;
    Ok(f)
}
fn admission(home: &Path) -> Result<File> {
    fs::create_dir_all(root(home))?;
    let f = file_lock(&root(home).join("admission.lock"))?;
    f.try_lock_exclusive()
        .context("Another controller request is being processed")?;
    Ok(f)
}
pub fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut tmp = tempfile::NamedTempFile::new_in(path.parent().context("missing parent")?)?;
    tmp.write_all(&serde_json::to_vec_pretty(value)?)?;
    tmp.as_file().sync_all()?;
    tmp.persist(path)?;
    File::open(path.parent().unwrap())?.sync_all()?;
    Ok(())
}
fn read_json(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&read_bounded(
        path,
        2 * 1024 * 1024,
    )?)?)
}
fn valid_id(id: &str) -> Result<()> {
    ensure!(
        uuid::Uuid::parse_str(id)?.to_string() == id,
        "Run ID must be a canonical UUID"
    );
    Ok(())
}
fn run_dir(home: &Path, id: &str) -> Result<PathBuf> {
    valid_id(id)?;
    Ok(root(home).join(id))
}
fn validate_request(r: &Request) -> Result<()> {
    valid_id(&r.id)?;
    ensure!(
        r.proposal.is_some() == r.report.is_some(),
        "Both parent proposal and report are required for continuation"
    );
    ensure!(
        r.name
            .as_ref()
            .is_none_or(|v| !v.trim().is_empty() && v.len() <= 120),
        "Experiment name must contain 1–120 bytes"
    );
    ensure!(
        r.objective
            .as_ref()
            .is_none_or(|v| !v.trim().is_empty() && v.len() <= 4000),
        "Objective must contain 1–4000 bytes"
    );
    ensure!(
        r.proposal.is_none() || r.name.is_none(),
        "Continuation does not accept an experiment name"
    );
    ensure!(
        r.instructions
            .as_ref()
            .is_none_or(|v| !v.trim().is_empty() && v.len() <= 4000),
        "Instructions must contain 1–4000 bytes"
    );
    match &r.weight_scope {
        Some(WeightScope::All) => (),
        Some(WeightScope::Selected { tensors }) => {
            ensure!(
                !tensors.is_empty() && tensors.len() <= 10000,
                "Choose at least one tensor"
            );
            let unique: std::collections::BTreeSet<_> = tensors.iter().collect();
            ensure!(
                unique.len() == tensors.len()
                    && tensors.iter().all(|s| !s.is_empty() && s.len() <= 1024),
                "Invalid or duplicate selected tensors"
            );
        }
        None => anyhow::bail!("Choose the editable weights: all or selected tensors"),
    }
    ensure!(
        ["codex", "openai"].contains(&r.backend.as_str()),
        "Unsupported controller backend"
    );
    ensure!(
        !r.controller_model.is_empty()
            && r.controller_model.len() <= 120
            && r.controller_model.as_bytes()[0].is_ascii_alphanumeric()
            && r.controller_model
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._/-".contains(&b)),
        "Invalid controller model"
    );
    ensure!(
        (1..=64).contains(&r.max_rounds)
            && (1..=32).contains(&r.max_probes)
            && r.min_probes <= r.max_probes
            && r.max_edit_elements
                .is_none_or(|n| (1..=9_007_199_254_740_991).contains(&n))
            && (60..=21600).contains(&r.timeout_seconds),
        "Controller budget outside supported limits"
    );
    ensure!(
        r.task_directory.is_absolute(),
        "Task directory must be absolute"
    );
    Ok(())
}
fn parent(home: &Path, r: &Request) -> Result<Value> {
    let store = ArtifactStore::open(home.join("artifacts"))?;
    let state = crate::journal::snapshot(home)?;
    if r.proposal.is_none() {
        ensure!(
            state["checkpoints"]
                .as_array()
                .unwrap()
                .iter()
                .any(|row| row["id"] == r.checkpoint.to_string()),
            "Import the starting checkpoint into this participant first"
        );
        let checkpoint = nc_core::verify_checkpoint(&store, &r.checkpoint)?;
        ensure!(
            checkpoint.shards.is_empty(),
            "New experiments currently require a single-file Safetensors model"
        );
        for name in [
            "model_config",
            "tokenizer",
            "tokenizer_config",
            "special_tokens",
        ] {
            ensure!(
                checkpoint.inference_artifacts.contains_key(name),
                "Starting model is missing inference artifact: {name}"
            );
        }
        return Ok(Value::Null);
    }
    let proposal = r.proposal.as_ref().unwrap();
    let report_id = r.report.as_ref().context("missing parent report")?;
    let record: Value = store.get_json(proposal)?;
    ensure!(
        record["kind"] == "PatchProposal",
        "Parent must be a patch proposal"
    );
    ensure!(
        state["records"]
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["id"] == proposal.to_string()
                && ["remote-dkg-readback", "local-shared"]
                    .contains(&row["provenance"].as_str().unwrap_or(""))
                && row["record"]
                    .as_str()
                    .and_then(|s| serde_json::from_str::<Value>(s).ok())
                    .as_ref()
                    == Some(&record)),
        "Parent proposal is not authenticated in this participant journal"
    );
    let spec_id = ContentId::try_from(
        record["artifact"]
            .as_str()
            .context("missing proposal spec")?
            .to_string(),
    )?;
    let spec: Value = store.get_json(&spec_id)?;
    let report: Value = store.get_json(report_id)?;
    ensure!(
        spec["candidate"] == r.checkpoint.to_string(),
        "Selected checkpoint differs from parent candidate"
    );
    ensure!(
        report["spec"] == spec_id.to_string() && report["status"] == "passed",
        "Parent requires a passing report for this exact proposal"
    );
    let known_report = state["jobs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|j| j["report"] == report_id.to_string())
        || state["records"].as_array().unwrap().iter().any(|row| {
            let rec = row["record"]
                .as_str()
                .and_then(|s| serde_json::from_str::<Value>(s).ok())
                .unwrap_or(Value::Null);
            rec["kind"] == "Evaluation"
                && rec["artifact"] == report_id.to_string()
                && ["remote-dkg-readback", "local-shared"]
                    .contains(&row["provenance"].as_str().unwrap_or(""))
        });
    ensure!(
        known_report,
        "Parent report is not recorded by this participant"
    );
    Ok(spec)
}
fn input_hashes(r: &Request) -> Result<Value> {
    ensure!(r.task_directory.is_dir(), "Task directory does not exist");
    let mut hashes = serde_json::Map::new();
    for name in INPUTS.into_iter().chain(["guard.json"]) {
        let path = r.task_directory.join(name);
        if name.starts_with("guard") && !path.exists() {
            continue;
        }
        ensure!(
            path.is_file() && path.metadata()?.len() <= 32 * 1024 * 1024,
            "Missing or oversized task input: {name}"
        );
        hashes.insert(name.into(), json!(hash_file(&path)?));
    }
    Ok(Value::Object(hashes))
}
fn active(status: &str) -> bool {
    [
        "queued",
        "preparing",
        "searching",
        "registering",
        "cancelling",
    ]
    .contains(&status)
}
fn states(home: &Path) -> Result<Vec<Value>> {
    let mut runs = Vec::new();
    if !root(home).exists() {
        return Ok(runs);
    }
    for item in fs::read_dir(root(home))? {
        let path = item?.path();
        if path.is_dir() && path.join("state.json").exists() {
            runs.push(read_json(&path.join("state.json"))?);
        }
    }
    runs.sort_by_key(|v| std::cmp::Reverse(v["created_at"].as_u64().unwrap_or(0)));
    Ok(runs)
}
fn recover(home: &Path) -> Result<()> {
    // Caller holds the execution lease: no worker can still own this run.
    for mut run in states(home)? {
        if active(run["status"].as_str().unwrap_or("")) {
            let dir = run_dir(home, run["id"].as_str().context("missing run ID")?)?;
            if dir.join("result.json").is_file() {
                run["status"] = json!("completed");
                run["result"] = read_json(&dir.join("result.json"))?;
                run["message"] = json!("Recovered frozen candidate; ready for final evaluation");
            } else {
                run["status"] = json!("interrupted");
                run["message"] = json!(
                    "Worker stopped before recording a terminal result. Evidence is retained."
                );
            }
            write_json(&dir.join("state.json"), &run)?;
        }
    }
    Ok(())
}
pub fn list(home: &Path) -> Result<Value> {
    let _admission = admission(home)?;
    if let Ok(_lease) = lease(home) {
        recover(home)?;
    }
    let mut runs = states(home)?;
    for run in &mut runs {
        let dir = run_dir(home, run["id"].as_str().context("missing run ID")?)?;
        run["importable"] = json!(
            ["interrupted", "failed", "cancelled", "timed_out"]
                .contains(&run["status"].as_str().unwrap_or(""))
                && dir.join("search/selected/session.json").is_file()
        );
        run["resumable"] = json!(
            ["interrupted", "failed", "cancelled", "timed_out"]
                .contains(&run["status"].as_str().unwrap_or(""))
                && dir.join("search/proposals/transcript.jsonl").is_file()
                && !dir.join("search/proposals/session.json").exists()
                && !dir.join("search/selected").exists()
        );
    }
    runs.truncate(100);
    Ok(json!({"runs": runs}))
}
fn spawn(home: &Path, python: &Path, dir: &Path, lock: File, resume: bool) -> Result<()> {
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("worker.log"))?;
    let mut cmd = Command::new(python);
    cmd.arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts/continuation_job.py"))
        .arg("--run")
        .arg(dir)
        .arg("--home")
        .arg(home)
        .arg("--nc")
        .arg(std::env::current_exe()?)
        .stdin(Stdio::from(lock))
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log));
    if resume {
        cmd.arg("--resume");
    }
    // Separate from the server's terminal process group; jobs survive UI/server closure.
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    let mut child = cmd
        .spawn()
        .context("Could not start the configured controller Python runtime")?;
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(())
}
pub fn start(home: &Path, python: &Path, request: Request) -> Result<Value> {
    validate_request(&request)?;
    let _admission = admission(home)?;
    let dir = run_dir(home, &request.id)?;
    if dir.exists() {
        let stored = read_json(&dir.join("request.json"))?;
        ensure!(
            stored["request"] == serde_json::to_value(&request)?,
            "Run ID is already bound to a different request"
        );
        return read_json(&dir.join("state.json"));
    }
    let lock = lease(home)?;
    recover(home)?;
    ensure!(states(home)?.len() < 1000, "Controller run limit reached");
    let spec = parent(home, &request)?;
    let hashes = input_hashes(&request)?;
    fs::create_dir(&dir)?;
    write_json(
        &dir.join("request.json"),
        &json!({"request":request, "input_hashes":hashes, "parent_spec":spec}),
    )?;
    let mut state = json!({"id":request.id,"status":"queued","checkpoint":request.checkpoint,"controller_model":request.controller_model,
        "backend":request.backend,"kind":if request.proposal.is_some() {"continuation"} else {"experiment"},"name":request.name,"created_at":std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_secs(),"attempt":1,"stage":"preparing","message":"Preparing model and freezing task inputs"});
    write_json(&dir.join("state.json"), &state)?;
    if let Err(e) = spawn(home, python, &dir, lock, false) {
        state["status"] = json!("failed");
        state["message"] = json!(e.to_string());
        write_json(&dir.join("state.json"), &state)?;
    }
    Ok(state)
}
pub fn control(home: &Path, python: &Path, id: &str, operation: &str) -> Result<Value> {
    let _admission = admission(home)?;
    let dir = run_dir(home, id)?;
    let mut state = read_json(&dir.join("state.json"))?;
    if operation == "cancel" {
        if active(state["status"].as_str().unwrap_or("")) {
            // Durable request; never signal a remembered PID which may have been reused.
            write_json(&dir.join("cancel.json"), &json!({"cancel":true}))?;
        }
        return Ok(state);
    }
    ensure!(operation == "resume", "Unsupported run operation");
    let lock = lease(home)?;
    recover(home)?;
    state = read_json(&dir.join("state.json"))?;
    ensure!(
        ["interrupted", "failed", "cancelled", "timed_out"]
            .contains(&state["status"].as_str().unwrap_or("")),
        "Only stopped runs can resume"
    );
    let importable = dir.join("search/selected/session.json").is_file();
    ensure!(
        importable
            || (dir.join("search/proposals/transcript.jsonl").is_file()
                && !dir.join("search/proposals/session.json").exists()
                && !dir.join("search/selected").exists()),
        "Requires an unfinished search transcript or a frozen selected candidate"
    );
    let request: Request =
        serde_json::from_value(read_json(&dir.join("request.json"))?["request"].clone())?;
    parent(home, &request)?;
    if dir.join("cancel.json").exists() {
        fs::remove_file(dir.join("cancel.json"))?;
    }
    state["status"] = json!("queued");
    state["stage"] = json!(if importable {
        "registering"
    } else {
        "searching"
    });
    state["attempt"] = json!(state["attempt"].as_u64().unwrap_or(1) + 1);
    write_json(&dir.join("state.json"), &state)?;
    if let Err(e) = spawn(home, python, &dir, lock, true) {
        state["status"] = json!("failed");
        state["message"] = json!(e.to_string());
        write_json(&dir.join("state.json"), &state)?;
    }
    Ok(state)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (tempfile::TempDir, PathBuf, Request) {
        let temp = tempfile::tempdir().unwrap();
        let home = temp.path().join("participant");
        fs::create_dir(&home).unwrap();
        let task = temp.path().join("task");
        fs::create_dir(&task).unwrap();
        for name in [
            "config.json",
            "development.json",
            "selection.json",
            "heldout.json",
            "policy.json",
            "source.json",
        ] {
            write_json(&task.join(name), &json!({})).unwrap();
        }
        let store = ArtifactStore::open(home.join("artifacts")).unwrap();
        let checkpoint = store.put_json(&json!({"checkpoint":"candidate"})).unwrap();
        let spec = store.put_json(&json!({"candidate":checkpoint})).unwrap();
        let record = json!({"kind":"PatchProposal","artifact":spec});
        let proposal = store.put_json(&record).unwrap();
        let report = store
            .put_json(&json!({"spec":spec,"status":"passed"}))
            .unwrap();
        let journal = crate::journal::Journal::open(&home).unwrap();
        journal.record(&proposal, &record, "local-shared").unwrap();
        journal.job(&spec).unwrap();
        journal.complete(&spec, &report, "complete").unwrap();
        drop(journal);
        let request = Request {
            id: uuid::Uuid::new_v4().to_string(),
            checkpoint,
            proposal: Some(proposal),
            report: Some(report),
            name: None,
            objective: None,
            instructions: None,
            weight_scope: Some(WeightScope::All),
            task_directory: task,
            backend: "codex".into(),
            controller_model: "controller-test".into(),
            max_rounds: 4,
            max_probes: 2,
            min_probes: 1,
            max_edit_elements: Some(8),
            timeout_seconds: 60,
        };
        (temp, home, request)
    }
    #[test]
    fn fresh_experiment_needs_model_artifacts_but_no_parent_evaluation() {
        let (_temp, home, mut request) = fixture();
        request.proposal = None;
        request.report = None;
        request.name = Some("Fresh experiment".into());
        request.objective = Some("Improve accuracy".into());
        let store = ArtifactStore::open(home.join("artifacts")).unwrap();
        let bytes = nc_core::encode_f32(std::collections::BTreeMap::from([(
            "weight".into(),
            (vec![1], vec![1.0]),
        )]))
        .unwrap();
        store.put(&bytes).unwrap();
        let mut manifest = nc_core::inspect(&bytes).unwrap();
        let metadata = store.put_json(&json!({})).unwrap();
        let python = Path::new("/nonexistent/python");
        request.checkpoint = store.put_json(&manifest).unwrap();
        let journal = crate::journal::Journal::open(&home).unwrap();
        journal.checkpoint(&request.checkpoint).unwrap();
        assert!(
            start(&home, python, request.clone())
                .unwrap_err()
                .to_string()
                .contains("missing inference")
        );
        for key in [
            "model_config",
            "tokenizer",
            "tokenizer_config",
            "special_tokens",
        ] {
            manifest
                .inference_artifacts
                .insert(key.into(), metadata.clone());
        }
        request.checkpoint = store.put_json(&manifest).unwrap();
        assert!(
            start(&home, python, request.clone())
                .unwrap_err()
                .to_string()
                .contains("Import")
        );
        journal.checkpoint(&request.checkpoint).unwrap();
        let mut incomplete_parent = request.clone();
        incomplete_parent.report = Some(metadata);
        assert!(start(&home, python, incomplete_parent).is_err());
        let state = start(&home, python, request.clone()).unwrap();
        assert_eq!(state["kind"], "experiment");
        assert_eq!(state["name"], "Fresh experiment");
        assert_eq!(state["status"], "failed"); // Runtime is deliberately absent.
        assert_eq!(start(&home, python, request.clone()).unwrap(), state);
        request.objective = Some("Changed objective".into());
        assert!(
            start(&home, python, request)
                .unwrap_err()
                .to_string()
                .contains("already bound")
        );
    }

    #[test]
    fn idempotency_and_changed_request_conflict() {
        let (_temp, home, request) = fixture();
        let python = Path::new("/nonexistent/nc-controller-python");
        let state = start(&home, python, request.clone()).unwrap();
        assert_eq!(state["status"], "failed");
        let _lock = lease(&home).unwrap(); // Even a busy worker cannot duplicate a retried ID.
        assert_eq!(start(&home, python, request.clone()).unwrap(), state);
        let mut changed = request;
        changed.controller_model = "another-model".into();
        assert!(
            start(&home, python, changed)
                .unwrap_err()
                .to_string()
                .contains("already bound")
        );
        assert_eq!(states(&home).unwrap().len(), 1);
    }
    #[test]
    fn parent_identity_report_and_budget_are_checked_before_admission() {
        let (_temp, home, request) = fixture();
        let python = Path::new("/nonexistent/python");
        let mut unrestricted = request.clone();
        unrestricted.max_edit_elements = None;
        unrestricted.objective = Some("User goal for this continuation".into());
        assert!(validate_request(&unrestricted).is_ok());
        unrestricted.max_edit_elements = Some(134_515_008);
        assert!(validate_request(&unrestricted).is_ok());
        unrestricted.max_edit_elements = Some(0);
        assert!(validate_request(&unrestricted).is_err());
        let mut wrong = request.clone();
        wrong.checkpoint = nc_core::digest(b"wrong");
        assert!(
            start(&home, python, wrong)
                .unwrap_err()
                .to_string()
                .contains("differs")
        );
        let mut wrong = request.clone();
        wrong.max_rounds = 999;
        assert!(start(&home, python, wrong).is_err());
        let store = ArtifactStore::open(home.join("artifacts")).unwrap();
        let mut wrong = request.clone();
        wrong.report = Some(
            store
                .put_json(&json!({"spec":parent(&home,&request).unwrap(),"status":"passed"}))
                .unwrap(),
        );
        assert!(start(&home, python, wrong).is_err());
        let mut wrong = request;
        wrong.id = "../escape".into();
        assert!(start(&home, python, wrong).is_err());
        assert!(states(&home).unwrap().is_empty());
    }
    #[test]
    fn execution_lease_blocks_new_work_and_recovery_does_not_release_live_work() {
        let (_temp, home, request) = fixture();
        let lock = lease(&home).unwrap();
        assert!(start(&home, Path::new("/nonexistent/python"), request.clone()).is_err());
        let dir = run_dir(&home, &request.id).unwrap();
        fs::create_dir_all(&dir).unwrap();
        write_json(
            &dir.join("state.json"),
            &json!({"id":request.id,"status":"searching"}),
        )
        .unwrap();
        assert_eq!(list(&home).unwrap()["runs"][0]["status"], "searching");
        drop(lock);
        assert_eq!(list(&home).unwrap()["runs"][0]["status"], "interrupted");
        assert!(
            control(
                &home,
                Path::new("/nonexistent/python"),
                &request.id,
                "resume"
            )
            .is_err()
        );
    }
    #[test]
    fn cancellation_is_a_durable_intent_and_completed_result_survives_supervisor_loss() {
        let (_temp, home, request) = fixture();
        let dir = run_dir(&home, &request.id).unwrap();
        fs::create_dir_all(&dir).unwrap();
        write_json(
            &dir.join("state.json"),
            &json!({"id":request.id,"status":"registering"}),
        )
        .unwrap();
        control(
            &home,
            Path::new("/nonexistent/python"),
            &request.id,
            "cancel",
        )
        .unwrap();
        assert!(dir.join("cancel.json").exists());
        write_json(
            &dir.join("result.json"),
            &json!({"candidate":request.checkpoint}),
        )
        .unwrap();
        assert_eq!(list(&home).unwrap()["runs"][0]["status"], "completed");
    }
}
