use anyhow::Result;
use nc_core::*;
use nc_evaluator::*;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

pub fn generate(s: &ArtifactStore, author: &str, executable: &ContentId) -> Result<Value> {
    let cfg = MlpConfig {
        input: 1,
        hidden: 2,
        output: 1,
        input_weights: "encoder.weight".into(),
        hidden_bias: "encoder.bias".into(),
        output_weights: "readout.weight".into(),
        output_bias: "readout.bias".into(),
    };
    let config = s.put_json(&cfg)?;
    // f(x)=ReLU(x)-ReLU(-x), deliberately damaged to 0.25*x.
    let bytes = encode_f32(BTreeMap::from([
        (cfg.input_weights.clone(), (vec![2, 1], vec![1., -1.])),
        (cfg.hidden_bias.clone(), (vec![2], vec![0., 0.])),
        (cfg.output_weights.clone(), (vec![1, 2], vec![0.25, -0.25])),
        (cfg.output_bias.clone(), (vec![1], vec![0.])),
    ]))?;
    let mut manifest = inspect(&bytes)?;
    s.put(&bytes)?;
    manifest
        .inference_artifacts
        .insert("config".into(), config.clone());
    let base = s.put_json(&manifest)?;
    let policy = s.put_json(&Policy {
        schema: "nc/policy/v1".into(),
        max_candidate_mse: 1e-10,
        min_improvement: 0.1,
        tolerance: 1e-9,
    })?;
    let dataset = |split: &str, inputs: &[f32]| Dataset {
        schema: "nc/dataset/v1".into(),
        label: "Controlled identity-function repair; synthetic fixture".into(),
        split: split.into(),
        samples: inputs
            .iter()
            .map(|x| Sample {
                input: vec![*x],
                expected: vec![*x],
            })
            .collect(),
    };
    let development = s.put_json(&dataset("development", &[-1., 0., 1.]))?;
    let heldout = s.put_json(&dataset("held-out", &[-3.5, -2.25, -0.75, 0.5, 1.75, 4.25]))?;
    let mut outcomes = BTreeMap::new();
    for (name, values) in [("repair", vec![1f32, -1.]), ("regression", vec![-1f32, 1.])] {
        let payload = s.put(
            &values
                .iter()
                .flat_map(|v| v.to_le_bytes())
                .collect::<Vec<_>>(),
        )?;
        let patch = create_patch(
            s,
            &base,
            author.into(),
            vec![Replacement {
                tensor: cfg.output_weights.clone(),
                dtype: "F32".into(),
                shape: vec![1, 2],
                offset: 0,
                count: 2,
                payload,
            }],
            Some(format!(
                "Controlled {name}; weights chosen using development inputs only"
            )),
        )?;
        let candidate = apply_patch(s, &base, &patch)?;
        let spec = EvaluationSpec {
            schema: "nc/evaluation-spec/v1".into(),
            base: base.clone(),
            candidate: candidate.clone(),
            patch: patch.clone(),
            evaluator: EVALUATOR.into(),
            executable: executable.clone(),
            dataset: heldout.clone(),
            config: config.clone(),
            policy: policy.clone(),
            seed: 0,
            backend: environment(),
            timeout_ms: 10_000,
            max_samples: 4096,
            max_artifact_bytes: MAX_METADATA_BYTES,
            metric: "mean_squared_error/v1".into(),
        };
        let spec_id = s.put_json(&spec)?;
        outcomes.insert(
            name,
            json!({"patch":patch,"candidate":candidate,"spec":spec_id}),
        );
    }
    let other = encode_f32(BTreeMap::from([
        (
            "arbitrary.block".into(),
            (vec![1, 2, 2], vec![1., 2., 3., 4.]),
        ),
        ("temperature".into(), (vec![], vec![0.5])),
    ]))?;
    let unrelated = register(s, &other)?;
    Ok(
        json!({"fixture":true,"base":base,"development":development,"heldout":heldout,"policy":policy,"unrelated_checkpoint":unrelated,"candidates":outcomes}),
    )
}
pub fn spec_bundle(s: &ArtifactStore, id: &ContentId) -> Result<Vec<ContentId>> {
    let spec: EvaluationSpec = s.get_json(id)?;
    let patch: Patch = s.get_json(&spec.patch)?;
    let mut ids = BTreeSet::from([
        id.clone(),
        spec.base.clone(),
        spec.candidate.clone(),
        spec.patch,
        spec.dataset,
        spec.config,
        spec.policy,
    ]);
    for cp in [&spec.base, &spec.candidate] {
        let m = verify_checkpoint(s, cp)?;
        ids.insert(m.artifact);
        ids.extend(m.shards.values().cloned());
        ids.extend(m.inference_artifacts.values().cloned());
    }
    ids.extend(patch.operations.iter().map(|op| op.payload.clone()));
    Ok(ids.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn controlled_repair_passes_and_regression_fails_on_heldout_inputs() {
        let dir = tempfile::tempdir().unwrap();
        let s = ArtifactStore::open(dir.path()).unwrap();
        let build = digest(b"test-build");
        let fixture = generate(&s, "0x1111111111111111111111111111111111111111", &build).unwrap();
        for (name, status) in [("repair", Status::Passed), ("regression", Status::Failed)] {
            let spec: ContentId =
                serde_json::from_value(fixture["candidates"][name]["spec"].clone()).unwrap();
            let report = evaluate(&s, &spec, &build);
            assert_eq!(report.status, status, "{:?}", report.error);
            assert!(report.outputs.is_some());
            assert_eq!(
                evaluate(&s, &spec, &digest(b"different-build")).status,
                Status::Unavailable
            );
        }
        let spec: ContentId =
            serde_json::from_value(fixture["candidates"]["repair"]["spec"].clone()).unwrap();
        let mut definition: EvaluationSpec = s.get_json(&spec).unwrap();
        definition.dataset = serde_json::from_value(fixture["development"].clone()).unwrap();
        assert_eq!(
            evaluate(&s, &s.put_json(&definition).unwrap(), &build).status,
            Status::Unavailable
        );
        definition.timeout_ms = 0;
        assert_eq!(
            evaluate(&s, &s.put_json(&definition).unwrap(), &build).status,
            Status::Unavailable
        );
    }
}
