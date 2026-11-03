//! Operator-selected process adapters; proposals supply identities and data, never commands.
use super::*;
use anyhow::Context;
use serde_json::json;
use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
};
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Runner {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub identity_files: Vec<PathBuf>,
    pub backend: String,
    pub max_timeout_ms: u64,
    pub max_output_bytes: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Scores {
    pub metric: String,
    pub base: f64,
    pub candidate: f64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MetricPolicy {
    pub schema: String,
    pub metric: String,
    pub direction: String,
    pub threshold: f64,
    pub min_improvement: f64,
    pub tolerance: f64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Output {
    schema: String,
    spec: ContentId,
    metric: String,
    base: f64,
    candidate: f64,
    backend: String,
    // Optional bounded adapter detail is preserved verbatim in the output artifact.
    #[serde(default, rename = "details")]
    _details: Option<serde_json::Value>,
}
pub fn runner_identity(r: &Runner) -> Result<ContentId> {
    ensure!(
        r.program.is_absolute() && r.identity_files.len() <= 128 && r.args.len() <= 128,
        "invalid operator runner configuration"
    );
    let mut files = Vec::new();
    for p in &r.identity_files {
        ensure!(p.is_absolute(), "runner identity paths must be absolute");
        files.push(hash_file(p)?);
    }
    // File paths vary between participants. Args that are declared files bind their bytes.
    let args: Vec<_> = r
        .args
        .iter()
        .map(|arg| {
            r.identity_files
                .iter()
                .position(|p| p.to_string_lossy() == arg.as_str())
                .map(|i| format!("artifact:{}", files[i]))
                .unwrap_or_else(|| arg.clone())
        })
        .collect();
    Ok(digest(&json_bytes(
        &json!({"schema":"nc/runner-build/v1","program":hash_file(&r.program)?,"args":args,"files":files,"backend":r.backend}),
    )?))
}
pub fn configured_runners(home: &Path) -> Result<BTreeMap<String, Runner>> {
    let path = home.join("evaluators.json");
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    Ok(serde_json::from_slice(&read_bounded(&path, 1024 * 1024)?)?)
}
pub fn evaluate_external(
    store: &ArtifactStore,
    spec_id: &ContentId,
    runner: &Runner,
) -> EvaluationReport {
    let mut report = EvaluationReport {
        schema: "nc/evaluation/v1".into(),
        spec: spec_id.clone(),
        evaluator: "unavailable".into(),
        observed_executable: digest(b"unavailable"),
        environment: runner.backend.clone(),
        process_id: std::process::id(),
        status: Status::Unavailable,
        base_mse: None,
        candidate_mse: None,
        outputs: None,
        error: None,
        scores: None,
    };
    let result = (|| -> Result<()> {
        let spec: EvaluationSpec = store.get_json(spec_id)?;
        report.evaluator = spec.evaluator.clone();
        report.observed_executable = runner_identity(runner)?;
        ensure!(
            spec.schema == "nc/evaluation-spec/v1"
                && spec.executable == report.observed_executable
                && spec.backend == runner.backend,
            "evaluator identity/backend mismatch"
        );
        ensure!(
            spec.timeout_ms > 0
                && spec.timeout_ms <= runner.max_timeout_ms
                && runner.max_output_bytes > 0
                && runner.max_output_bytes <= MAX_METADATA_BYTES,
            "evaluation exceeds operator resource policy"
        );
        let base = verify_checkpoint(store, &spec.base)?;
        let candidate = verify_checkpoint(store, &spec.candidate)?;
        ensure!(
            base.inference_artifacts == candidate.inference_artifacts
                && base.inference_artifacts.get("config") == Some(&spec.config),
            "inference artifact identity mismatch"
        );
        ensure!(
            apply_patch(store, &spec.base, &spec.patch)? == spec.candidate,
            "candidate lineage mismatch"
        );
        store.verify(&spec.dataset)?;
        store.verify(&spec.config)?;
        ensure!(spec.evidence.len() <= 128, "too many evidence artifacts");
        for evidence in &spec.evidence {
            store.verify(evidence)?;
        }
        let policy: MetricPolicy = store.get_json(&spec.policy)?;
        ensure!(
            policy.schema == "nc/metric-policy/v1"
                && policy.metric == spec.metric
                && ["minimize", "maximize"].contains(&policy.direction.as_str())
                && [policy.threshold, policy.min_improvement, policy.tolerance]
                    .iter()
                    .all(|v| v.is_finite())
                && policy.min_improvement >= 0.
                && policy.tolerance >= 0.,
            "invalid metric policy"
        );
        let temp = tempfile::tempdir()?;
        let request = temp.path().join("request.json");
        let result = temp.path().join("result.json");
        let paths = |m: &Checkpoint| {
            checkpoint_files(m)
                .into_iter()
                .map(|(n, h)| (n, store.path(&h)))
                .collect::<BTreeMap<_, _>>()
        };
        std::fs::write(
            &request,
            json_bytes(
                &json!({"schema":"nc/evaluator-request/v1","spec_id":spec_id,"spec":spec,"base_files":paths(&base),"candidate_files":paths(&candidate),"inference_artifacts":base.inference_artifacts.iter().map(|(name, id)| (name, store.path(id))).collect::<BTreeMap<_,_>>(),"dataset":store.path(&spec.dataset),"config":store.path(&spec.config)}),
            )?,
        )?;
        let mut child = Command::new(&runner.program)
            .args(&runner.args)
            .arg(&request)
            .stdin(Stdio::null())
            .stdout(std::fs::File::create(&result)?)
            .stderr(Stdio::null())
            .spawn()?;
        let deadline = Instant::now() + Duration::from_millis(spec.timeout_ms);
        let status = loop {
            if Instant::now() >= deadline
                || std::fs::metadata(&result)?.len() > runner.max_output_bytes as u64
            {
                let _ = child.kill();
                let _ = child.wait();
                report.status = Status::Interrupted;
                anyhow::bail!("evaluator exceeded runtime/output budget");
            }
            if let Some(status) = child.try_wait()? {
                break status;
            }
            std::thread::sleep(Duration::from_millis(20));
        };
        ensure!(
            status.success(),
            "configured evaluator exited unsuccessfully"
        );
        let bytes = read_bounded(&result, runner.max_output_bytes)?;
        let out: Output = serde_json::from_slice(&bytes).context("invalid evaluator result")?;
        ensure!(
            out.schema == "nc/evaluator-result/v1"
                && out.spec == *spec_id
                && out.metric == spec.metric
                && out.backend == spec.backend
                && out.base.is_finite()
                && out.candidate.is_finite(),
            "evaluator result identity/metric mismatch"
        );
        let (meets, improvement) = if policy.direction == "maximize" {
            (
                out.candidate + policy.tolerance >= policy.threshold,
                out.candidate - out.base,
            )
        } else {
            (
                out.candidate <= policy.threshold + policy.tolerance,
                out.base - out.candidate,
            )
        };
        report.status = if meets && improvement + policy.tolerance >= policy.min_improvement {
            Status::Passed
        } else {
            Status::Failed
        };
        report.scores = Some(Scores {
            metric: out.metric,
            base: out.base,
            candidate: out.candidate,
        });
        report.outputs = Some(store.put(&bytes)?);
        Ok(())
    })();
    if let Err(e) = result {
        report.error = Some(format!("{e:#}"));
    }
    report
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn configured_process_binds_identity_outputs_and_timeout() {
        let dir = tempfile::tempdir().unwrap();
        let store = ArtifactStore::open(dir.path().join("store")).unwrap();
        let config = store.put_json(&json!({"adapter":"contract-test"})).unwrap();
        let mut m =
            inspect(&encode_f32(BTreeMap::from([("w".into(), (vec![1], vec![0.]))])).unwrap())
                .unwrap();
        let raw = encode_f32(BTreeMap::from([("w".into(), (vec![1], vec![0.]))])).unwrap();
        store.put(&raw).unwrap();
        m.inference_artifacts
            .insert("config".into(), config.clone());
        let base = store.put_json(&m).unwrap();
        let patch = create_patch(
            &store,
            &base,
            "author".into(),
            vec![Replacement {
                tensor: "w".into(),
                dtype: "F32".into(),
                shape: vec![1],
                offset: 0,
                count: 1,
                payload: store.put(&1f32.to_le_bytes()).unwrap(),
            }],
            None,
        )
        .unwrap();
        let candidate = apply_patch(&store, &base, &patch).unwrap();
        let python = Command::new("python3")
            .args(["-c", "import sys;print(sys.executable)"])
            .output()
            .unwrap();
        let program =
            std::fs::canonicalize(String::from_utf8(python.stdout).unwrap().trim()).unwrap();
        let script = dir.path().join("runner.py");
        std::fs::write(&script,"import json,sys\nr=json.load(open(sys.argv[1]))\nprint(json.dumps(dict(schema='nc/evaluator-result/v1',spec=r['spec_id'],metric='loss',base=1,candidate=0,backend='test')))\n").unwrap();
        let runner = Runner {
            program,
            args: vec![script.to_string_lossy().into()],
            identity_files: vec![script.clone()],
            backend: "test".into(),
            max_timeout_ms: 5000,
            max_output_bytes: 4096,
        };
        let mut spec=EvaluationSpec {schema:"nc/evaluation-spec/v1".into(),base,candidate,patch,evaluator:"contract-test".into(),executable:runner_identity(&runner).unwrap(),dataset:store.put_json(&json!({})).unwrap(),config,policy:store.put_json(&json!({"schema":"nc/metric-policy/v1","metric":"loss","direction":"minimize","threshold":0.1,"min_improvement":0.2,"tolerance":0.0})).unwrap(),seed:0,backend:"test".into(),timeout_ms:3000,max_samples:1,max_artifact_bytes:0,metric:"loss".into(),evidence:Vec::new()};
        let report = evaluate_external(&store, &store.put_json(&spec).unwrap(), &runner);
        assert_eq!(report.status, Status::Passed, "{:?}", report.error);
        // Provenance is part of the specification and must actually be available.
        let provenance = b"controller transcript";
        spec.evidence = vec![digest(provenance)];
        let missing = evaluate_external(&store, &store.put_json(&spec).unwrap(), &runner);
        assert_eq!(missing.status, Status::Unavailable);
        store.put(provenance).unwrap();
        assert_eq!(
            evaluate_external(&store, &store.put_json(&spec).unwrap(), &runner).status,
            Status::Passed
        );
        std::fs::write(&script, "import time;time.sleep(5)\n").unwrap();
        assert_eq!(
            evaluate_external(&store, &store.put_json(&spec).unwrap(), &runner).status,
            Status::Unavailable
        );
        spec.executable = runner_identity(&runner).unwrap();
        spec.timeout_ms = 30;
        assert_eq!(
            evaluate_external(&store, &store.put_json(&spec).unwrap(), &runner).status,
            Status::Interrupted
        );
        std::fs::write(&script,"import json;print(json.dumps(dict(schema='nc/evaluator-result/v1',spec='0'*64,metric='loss',base=1,candidate=0,backend='test')))\n").unwrap();
        spec.executable = runner_identity(&runner).unwrap();
        spec.timeout_ms = 3000;
        assert_eq!(
            evaluate_external(&store, &store.put_json(&spec).unwrap(), &runner).status,
            Status::Unavailable
        );
    }
}
