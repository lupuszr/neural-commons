use crate::*;
use anyhow::{Result, ensure};
use safetensors::{Dtype, SafeTensors};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub const TENSOR_SCHEMA: &str = "nc/checkpoint/v1";
pub const PATCH_SCHEMA: &str = "nc/replace-flat-f32/v1";
pub(crate) const MAX_TENSORS: usize = 100_000;
pub(crate) const MAX_OPERATIONS: usize = 100_000;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct TensorDescriptor {
    pub name: String,
    pub dtype: String,
    pub shape: Vec<usize>,
    pub bytes: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shard: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Checkpoint {
    pub schema: String,
    pub artifact: ContentId,
    pub format: String,
    pub tensors: Vec<TensorDescriptor>,
    pub inference_artifacts: BTreeMap<String, ContentId>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub shards: BTreeMap<String, ContentId>,
}
pub fn inspect(bytes: &[u8]) -> Result<Checkpoint> {
    let tensors = SafeTensors::deserialize(bytes)?;
    ensure!(tensors.len() <= MAX_TENSORS, "too many tensors");
    let mut inventory = Vec::new();
    for (name, t) in tensors.tensors() {
        ensure!(
            name.len() <= 1024 && t.shape().len() <= 32,
            "tensor name or rank exceeds limit"
        );
        inventory.push(TensorDescriptor {
            name,
            dtype: format!("{:?}", t.dtype()),
            shape: t.shape().to_vec(),
            bytes: t.data().len(),
            shard: None,
        });
    }
    inventory.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(Checkpoint {
        schema: TENSOR_SCHEMA.into(),
        artifact: digest(bytes),
        format: "safetensors".into(),
        tensors: inventory,
        inference_artifacts: BTreeMap::new(),
        shards: BTreeMap::new(),
    })
}
pub fn register(store: &ArtifactStore, bytes: &[u8]) -> Result<ContentId> {
    let manifest = inspect(bytes)?;
    store.put(bytes)?;
    store.put_json(&manifest)
}
pub fn load_checkpoint(store: &ArtifactStore, id: &ContentId) -> Result<(Checkpoint, Vec<u8>)> {
    let m: Checkpoint = store.get_json(id)?;
    ensure!(
        m.schema == TENSOR_SCHEMA && m.format == "safetensors",
        "unsupported checkpoint schema/format"
    );
    let bytes = store.get(&m.artifact)?;
    ensure!(
        inspect(&bytes)?.tensors == m.tensors,
        "checkpoint inventory mismatch"
    );
    for artifact in m.inference_artifacts.values() {
        store.get(artifact)?;
    }
    Ok((m, bytes))
}

/// Contiguous region in row-major element coordinates. Shape binds its interpretation.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Replacement {
    pub tensor: String,
    pub dtype: String,
    pub shape: Vec<usize>,
    pub offset: usize,
    pub count: usize,
    pub payload: ContentId,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Patch {
    pub schema: String,
    pub author: String,
    pub parent: ContentId,
    pub operations: Vec<Replacement>,
    pub result_artifact: ContentId,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub result_shards: BTreeMap<String, ContentId>,
    pub hypothesis: Option<String>,
}

pub fn f32_tensor(bytes: &[u8], name: &str) -> Result<(Vec<usize>, Vec<f32>)> {
    let ts = SafeTensors::deserialize(bytes)?;
    let t = ts.tensor(name)?;
    ensure!(t.dtype() == Dtype::F32, "evaluator requires F32");
    let data: Vec<_> = t
        .data()
        .chunks_exact(4)
        .map(|v| f32::from_le_bytes(v.try_into().unwrap()))
        .collect();
    ensure!(data.iter().all(|v| v.is_finite()), "non-finite model value");
    Ok((t.shape().to_vec(), data))
}

/// Fixture helper, not part of model-specific execution.
pub fn encode_f32(tensors: BTreeMap<String, (Vec<usize>, Vec<f32>)>) -> Result<Vec<u8>> {
    let raw: Vec<_> = tensors
        .iter()
        .map(|(n, (s, v))| {
            (
                n,
                s,
                v.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>(),
            )
        })
        .collect();
    let views = raw
        .iter()
        .map(|(n, s, b)| {
            Ok((
                n.as_str(),
                safetensors::tensor::TensorView::new(Dtype::F32, (*s).clone(), b)?,
            ))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(safetensors::serialize(views, None)?)
}
