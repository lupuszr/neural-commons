//! Versioned evaluator boundary. This small scalar CPU MLP is only a demo adapter.
use anyhow::{Result, ensure};
use nc_core::*;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    time::{Duration, Instant},
};

pub mod external;
pub use external::*;

pub const EVALUATOR: &str = "nc/scalar-mlp-cpu/v1";
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MlpConfig {
    pub input: usize,
    pub hidden: usize,
    pub output: usize,
    pub input_weights: String,
    pub hidden_bias: String,
    pub output_weights: String,
    pub output_bias: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sample {
    pub input: Vec<f32>,
    pub expected: Vec<f32>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dataset {
    pub schema: String,
    pub label: String,
    pub split: String,
    pub samples: Vec<Sample>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub schema: String,
    pub max_candidate_mse: f64,
    pub min_improvement: f64,
    pub tolerance: f64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvaluationSpec {
    pub schema: String,
    pub base: ContentId,
    pub candidate: ContentId,
    pub patch: ContentId,
    pub evaluator: String,
    pub executable: ContentId,
    pub dataset: ContentId,
    pub config: ContentId,
    pub policy: ContentId,
    pub seed: u64,
    pub backend: String,
    pub timeout_ms: u64,
    pub max_samples: usize,
    pub max_artifact_bytes: usize,
    pub metric: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Passed,
    Failed,
    Interrupted,
    Unavailable,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EvaluationReport {
    pub schema: String,
    pub spec: ContentId,
    pub evaluator: String,
    pub observed_executable: ContentId,
    pub environment: String,
    pub process_id: u32,
    pub status: Status,
    pub base_mse: Option<f64>,
    pub candidate_mse: Option<f64>,
    pub outputs: Option<ContentId>,
    pub error: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scores: Option<Scores>,
}
pub trait Evaluator {
    fn identity(&self) -> &str;
    fn predict(&self, checkpoint: &[u8], config: &MlpConfig, input: &[f32]) -> Result<Vec<f32>>;
}
pub struct ScalarMlp;
impl Evaluator for ScalarMlp {
    fn identity(&self) -> &str {
        EVALUATOR
    }
    fn predict(&self, checkpoint: &[u8], c: &MlpConfig, input: &[f32]) -> Result<Vec<f32>> {
        ensure!(
            (1..=64).contains(&c.input)
                && (1..=64).contains(&c.hidden)
                && (1..=64).contains(&c.output),
            "demo evaluator dimensions outside limits"
        );
        ensure!(
            input.len() == c.input && input.iter().all(|v| v.is_finite()),
            "invalid input"
        );
        let tensors = [
            (&c.input_weights, vec![c.hidden, c.input]),
            (&c.hidden_bias, vec![c.hidden]),
            (&c.output_weights, vec![c.output, c.hidden]),
            (&c.output_bias, vec![c.output]),
        ];
        let mut v = Vec::new();
        for (name, shape) in tensors {
            let (actual, data) = f32_tensor(checkpoint, name)?;
            ensure!(
                actual == shape,
                "evaluator tensor shape mismatch for {name}"
            );
            v.push(data);
        }
        let h: Vec<f32> = (0..c.hidden)
            .map(|j| {
                (v[1][j]
                    + input
                        .iter()
                        .enumerate()
                        .map(|(i, x)| v[0][j * c.input + i] * x)
                        .sum::<f32>())
                .max(0.)
            })
            .collect();
        let out: Vec<f32> = (0..c.output)
            .map(|k| {
                v[3][k]
                    + h.iter()
                        .enumerate()
                        .map(|(j, x)| v[2][k * c.hidden + j] * x)
                        .sum::<f32>()
            })
            .collect();
        ensure!(
            out.iter().all(|v| v.is_finite()),
            "non-finite inference output"
        );
        Ok(out)
    }
}
pub fn environment() -> String {
    format!(
        "scalar-f32-cpu/{}/{}",
        std::env::consts::OS,
        std::env::consts::ARCH
    )
}
pub fn evaluate(
    store: &ArtifactStore,
    spec_id: &ContentId,
    executable: &ContentId,
) -> EvaluationReport {
    let mut report = EvaluationReport {
        schema: "nc/evaluation/v1".into(),
        spec: spec_id.clone(),
        evaluator: EVALUATOR.into(),
        observed_executable: executable.clone(),
        environment: environment(),
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
        ensure!(
            spec.schema == "nc/evaluation-spec/v1" && spec.evaluator == EVALUATOR,
            "unsupported evaluator contract"
        );
        ensure!(
            &spec.executable == executable && spec.backend == environment(),
            "evaluator build/backend mismatch"
        );
        ensure!(
            spec.seed == 0 && spec.metric == "mean_squared_error/v1",
            "unsupported deterministic inference settings"
        );
        ensure!(
            (1..=30_000).contains(&spec.timeout_ms)
                && (1..=4096).contains(&spec.max_samples)
                && spec.max_artifact_bytes <= MAX_METADATA_BYTES,
            "unsupported resource limits"
        );
        let deadline = Instant::now() + Duration::from_millis(spec.timeout_ms);
        let (base_manifest, base) = load_checkpoint(store, &spec.base)?;
        let (candidate_manifest, candidate) = load_checkpoint(store, &spec.candidate)?;
        ensure!(
            base.len() <= spec.max_artifact_bytes && candidate.len() <= spec.max_artifact_bytes,
            "evaluation artifact limit"
        );
        ensure!(
            base_manifest.inference_artifacts.get("config") == Some(&spec.config)
                && candidate_manifest.inference_artifacts == base_manifest.inference_artifacts,
            "inference artifact identity mismatch"
        );
        ensure!(
            apply_patch(store, &spec.base, &spec.patch)? == spec.candidate,
            "candidate does not match patch lineage"
        );
        let cfg: MlpConfig = store.get_json(&spec.config)?;
        let data: Dataset = store.get_json(&spec.dataset)?;
        let policy: Policy = store.get_json(&spec.policy)?;
        ensure!(
            data.schema == "nc/dataset/v1"
                && data.split == "held-out"
                && !data.samples.is_empty()
                && data.samples.len() <= spec.max_samples,
            "invalid held-out dataset"
        );
        ensure!(
            policy.schema == "nc/policy/v1"
                && [
                    policy.max_candidate_mse,
                    policy.min_improvement,
                    policy.tolerance
                ]
                .iter()
                .all(|v| v.is_finite() && *v >= 0.),
            "invalid acceptance policy"
        );
        let mut outputs = BTreeMap::new();
        let mut scores = Vec::new();
        for (label, model) in [("base", &base), ("candidate", &candidate)] {
            let mut sum = 0.;
            let mut count = 0;
            let mut predictions = Vec::new();
            for row in &data.samples {
                if Instant::now() >= deadline {
                    report.status = Status::Interrupted;
                    anyhow::bail!("evaluation deadline exceeded");
                }
                let p = ScalarMlp.predict(model, &cfg, &row.input)?;
                ensure!(
                    row.expected.len() == p.len() && row.expected.iter().all(|v| v.is_finite()),
                    "invalid expected output"
                );
                for (a, b) in p.iter().zip(&row.expected) {
                    sum += (*a as f64 - *b as f64).powi(2);
                    count += 1;
                }
                predictions.push(p);
            }
            let mse = sum / count as f64;
            ensure!(mse.is_finite(), "invalid metric");
            scores.push(mse);
            outputs.insert(label, predictions);
        }
        report.outputs = Some(store.put_json(&outputs)?);
        report.base_mse = Some(scores[0]);
        report.candidate_mse = Some(scores[1]);
        report.status = if scores[1] <= policy.max_candidate_mse + policy.tolerance
            && scores[0] - scores[1] + policy.tolerance >= policy.min_improvement
        {
            Status::Passed
        } else {
            Status::Failed
        };
        Ok(())
    })();
    if let Err(e) = result {
        report.error = Some(e.to_string());
    }
    report
}
