//! File-backed tensor inspection and patching. Tensor bytes never become a whole-file Vec.
use crate::tensor::{MAX_OPERATIONS, MAX_TENSORS};
use crate::*;
use anyhow::{Context, Result, ensure};
use safetensors::tensor::Metadata;
use serde::Deserialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::File,
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
};

pub struct Layout {
    pub header_len: u64,
    pub metadata: Metadata,
}
pub fn layout(path: &Path) -> Result<Layout> {
    let mut f = File::open(path)?;
    let size = f.metadata()?.len();
    let mut prefix = [0u8; 8];
    f.read_exact(&mut prefix)?;
    let n = u64::from_le_bytes(prefix);
    ensure!(
        n <= MAX_METADATA_BYTES as u64 && n <= size.saturating_sub(8),
        "invalid or oversized tensor header"
    );
    let mut header = vec![0; n as usize];
    f.read_exact(&mut header)?;
    ensure!(header.first() == Some(&b'{'), "invalid tensor header");
    let metadata: Metadata = serde_json::from_slice(&header)?;
    ensure!(
        metadata.data_len() as u64 == size - 8 - n,
        "tensor data length mismatch"
    );
    ensure!(metadata.tensors().len() <= MAX_TENSORS, "too many tensors");
    for (name, t) in metadata.tensors() {
        ensure!(
            name.len() <= 1024 && t.shape.len() <= 32,
            "tensor name/rank exceeds limit"
        );
    }
    Ok(Layout {
        header_len: 8 + n,
        metadata,
    })
}
pub fn inspect_file(path: &Path) -> Result<Checkpoint> {
    let l = layout(path)?;
    let mut tensors: Vec<_> = l
        .metadata
        .tensors()
        .into_iter()
        .map(|(name, t)| TensorDescriptor {
            name,
            dtype: format!("{:?}", t.dtype),
            shape: t.shape.clone(),
            bytes: t.data_offsets.1 - t.data_offsets.0,
            shard: None,
        })
        .collect();
    tensors.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(Checkpoint {
        schema: TENSOR_SCHEMA.into(),
        artifact: hash_file(path)?,
        format: "safetensors".into(),
        tensors,
        inference_artifacts: BTreeMap::new(),
        shards: BTreeMap::new(),
    })
}
#[derive(Deserialize)]
struct Index {
    weight_map: BTreeMap<String, String>,
}
fn safe_shard(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 255
        && !name.contains(['/', '\\'])
        && name != "."
        && name != ".."
}
pub fn register_file(store: &ArtifactStore, path: &Path) -> Result<Checkpoint> {
    if path.extension().and_then(|s| s.to_str()) != Some("json") {
        let manifest = inspect_file(path)?;
        ensure!(
            store.put_file(path)? == manifest.artifact,
            "source changed during import"
        );
        return Ok(manifest);
    }
    let index_bytes = read_bounded(path, MAX_METADATA_BYTES)?;
    let index: Index = serde_json::from_slice(&index_bytes)?;
    ensure!(
        !index.weight_map.is_empty() && index.weight_map.len() <= MAX_TENSORS,
        "invalid shard index"
    );
    let names: BTreeSet<_> = index.weight_map.values().cloned().collect();
    let mut shards = BTreeMap::new();
    let mut tensors = Vec::new();
    for name in names {
        ensure!(safe_shard(&name), "unsafe shard path");
        let file = path.parent().context("index parent")?.join(&name);
        ensure!(
            std::fs::symlink_metadata(&file)?.file_type().is_file(),
            "shard must be regular file"
        );
        let m = inspect_file(&file)?;
        ensure!(
            store.put_file(&file)? == m.artifact,
            "shard changed during import"
        );
        for mut t in m.tensors {
            ensure!(
                index.weight_map.get(&t.name) == Some(&name),
                "index tensor/shard mismatch"
            );
            t.shard = Some(name.clone());
            tensors.push(t);
        }
        shards.insert(name, m.artifact);
    }
    ensure!(
        tensors.len() == index.weight_map.len(),
        "index has missing tensors"
    );
    tensors.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(Checkpoint {
        schema: TENSOR_SCHEMA.into(),
        artifact: store.put(&index_bytes)?,
        format: "safetensors-sharded".into(),
        tensors,
        inference_artifacts: BTreeMap::new(),
        shards,
    })
}
pub fn checkpoint_files(m: &Checkpoint) -> BTreeMap<String, ContentId> {
    if m.shards.is_empty() {
        BTreeMap::from([(String::new(), m.artifact.clone())])
    } else {
        m.shards.clone()
    }
}
pub fn verify_checkpoint(store: &ArtifactStore, id: &ContentId) -> Result<Checkpoint> {
    let m: Checkpoint = store.get_json(id)?;
    ensure!(m.schema == TENSOR_SCHEMA, "unsupported checkpoint schema");
    ensure!(
        m.inference_artifacts.len() <= 128,
        "too many inference artifacts"
    );
    ensure!(
        (m.format == "safetensors" && m.shards.is_empty())
            || (m.format == "safetensors-sharded" && !m.shards.is_empty()),
        "invalid checkpoint format/shards"
    );
    let mut inventory = Vec::new();
    for (name, hash) in checkpoint_files(&m) {
        ensure!(name.is_empty() || safe_shard(&name), "unsafe shard name");
        let actual = inspect_file(&store.path(&hash))?;
        ensure!(actual.artifact == hash, "checkpoint integrity mismatch");
        for mut t in actual.tensors {
            t.shard = if name.is_empty() {
                None
            } else {
                Some(name.clone())
            };
            inventory.push(t);
        }
    }
    inventory.sort_by(|a, b| a.name.cmp(&b.name));
    ensure!(
        inventory.windows(2).all(|w| w[0].name != w[1].name),
        "duplicate tensor across shards"
    );
    ensure!(inventory == m.tensors, "checkpoint inventory mismatch");
    if !m.shards.is_empty() {
        let index: Index = store.get_json(&m.artifact)?;
        let expected: BTreeMap<_, _> = m
            .tensors
            .iter()
            .map(|t| (t.name.clone(), t.shard.clone().unwrap()))
            .collect();
        ensure!(index.weight_map == expected, "checkpoint index mismatch");
    }
    for hash in m.inference_artifacts.values() {
        store.verify(hash)?;
    }
    Ok(m)
}
fn width(dtype: &str) -> Result<usize> {
    match dtype {
        "F32" => Ok(4),
        "F16" | "BF16" => Ok(2),
        _ => anyhow::bail!("unsupported edit dtype: {dtype}; supported F32/F16/BF16"),
    }
}
fn finite(bytes: &[u8], dtype: &str) -> bool {
    match dtype {
        "F32" => bytes
            .chunks_exact(4)
            .all(|b| f32::from_le_bytes(b.try_into().unwrap()).is_finite()),
        "F16" => bytes
            .chunks_exact(2)
            .all(|b| u16::from_le_bytes(b.try_into().unwrap()) & 0x7c00 != 0x7c00),
        "BF16" => bytes
            .chunks_exact(2)
            .all(|b| u16::from_le_bytes(b.try_into().unwrap()) & 0x7f80 != 0x7f80),
        _ => false,
    }
}
fn copy_exact(input: &mut impl Read, output: &mut impl Write, mut n: u64) -> Result<()> {
    let mut buffer = vec![0; IO_BUFFER_BYTES];
    while n > 0 {
        let len = n.min(buffer.len() as u64) as usize;
        input.read_exact(&mut buffer[..len])?;
        output.write_all(&buffer[..len])?;
        n -= len as u64;
    }
    Ok(())
}
fn replace_files(
    store: &ArtifactStore,
    base: &Checkpoint,
    ops: &[Replacement],
    expected: Option<&BTreeMap<String, ContentId>>,
) -> Result<BTreeMap<String, ContentId>> {
    ensure!(
        !ops.is_empty() && ops.len() <= MAX_OPERATIONS,
        "invalid operation count"
    );
    let mut grouped: BTreeMap<String, Vec<&Replacement>> = BTreeMap::new();
    for op in ops {
        let t = base
            .tensors
            .iter()
            .find(|t| t.name == op.tensor)
            .context("unknown tensor")?;
        let w = width(&op.dtype)?;
        ensure!(
            t.dtype == op.dtype && t.shape == op.shape,
            "tensor shape/dtype mismatch"
        );
        let end = op.offset.checked_add(op.count).context("region overflow")?;
        ensure!(op.count > 0 && end <= t.bytes / w, "region out of bounds");
        ensure!(
            store.verify(&op.payload)?
                == op.count.checked_mul(w).context("payload overflow")? as u64,
            "payload length mismatch"
        );
        grouped
            .entry(t.shard.clone().unwrap_or_default())
            .or_default()
            .push(op);
    }
    let mut result = BTreeMap::new();
    for (name, hash) in checkpoint_files(base) {
        let Some(ops) = grouped.get(&name) else {
            result.insert(name, hash);
            continue;
        };
        let l = layout(&store.path(&hash))?;
        let mut ranges = Vec::new();
        for op in ops {
            let t = l.metadata.info(&op.tensor).context("tensor missing")?;
            let w = width(&op.dtype)?;
            let start = l.header_len + t.data_offsets.0 as u64 + (op.offset * w) as u64;
            ranges.push((start, start + (op.count * w) as u64, *op));
        }
        ranges.sort_by_key(|r| r.0);
        ensure!(
            ranges.windows(2).all(|w| w[0].1 <= w[1].0),
            "overlapping patch regions"
        );
        let mut input = File::open(store.path(&hash))?;
        let mut output = store.stage()?;
        let mut pos = 0;
        for (start, end, op) in ranges {
            copy_exact(&mut input, &mut output, start - pos)?;
            let mut payload = store.open_verified(&op.payload)?;
            let mut remaining = end - start;
            let mut buffer = vec![0; IO_BUFFER_BYTES];
            while remaining > 0 {
                let n = remaining.min(buffer.len() as u64) as usize;
                payload.read_exact(&mut buffer[..n])?;
                ensure!(finite(&buffer[..n], &op.dtype), "non-finite patch value");
                output.write_all(&buffer[..n])?;
                remaining -= n as u64;
            }
            input.seek(SeekFrom::Start(end))?;
            pos = end;
        }
        let len = input.metadata()?.len();
        copy_exact(&mut input, &mut output, len - pos)?;
        output.flush()?;
        let digest = hash_file(output.path())?;
        if let Some(expected) = expected {
            ensure!(
                expected.get(&name) == Some(&digest),
                "result artifact mismatch"
            );
        }
        layout(output.path())?;
        result.insert(name, store.commit(output, &digest)?);
    }
    if let Some(expected) = expected {
        ensure!(&result == expected, "result shard manifest mismatch");
    }
    Ok(result)
}
pub fn create_patch(
    store: &ArtifactStore,
    parent: &ContentId,
    author: String,
    operations: Vec<Replacement>,
    hypothesis: Option<String>,
) -> Result<ContentId> {
    ensure!(
        !author.is_empty() && author.len() <= 256,
        "invalid author identity"
    );
    ensure!(
        hypothesis.as_ref().is_none_or(|s| s.len() <= 8192),
        "hypothesis too large"
    );
    let m = verify_checkpoint(store, parent)?;
    let results = replace_files(store, &m, &operations, None)?;
    let result_artifact = if m.shards.is_empty() {
        results[""].clone()
    } else {
        m.artifact.clone()
    };
    store.put_json(&Patch {
        schema: "nc/replace-flat/v2".into(),
        author,
        parent: parent.clone(),
        operations,
        result_artifact,
        result_shards: if m.shards.is_empty() {
            BTreeMap::new()
        } else {
            results
        },
        hypothesis,
    })
}
pub fn apply_patch(
    store: &ArtifactStore,
    parent: &ContentId,
    patch_id: &ContentId,
) -> Result<ContentId> {
    let p: Patch = store.get_json(patch_id)?;
    ensure!(
        p.schema == PATCH_SCHEMA || p.schema == "nc/replace-flat/v2",
        "unsupported patch schema"
    );
    ensure!(&p.parent == parent, "wrong parent checkpoint");
    let mut m = verify_checkpoint(store, parent)?;
    let expected = if m.shards.is_empty() {
        ensure!(p.result_shards.is_empty(), "unexpected shards");
        BTreeMap::from([(String::new(), p.result_artifact.clone())])
    } else {
        ensure!(p.result_artifact == m.artifact, "shard index cannot change");
        p.result_shards.clone()
    };
    replace_files(store, &m, &p.operations, Some(&expected))?;
    m.artifact = p.result_artifact;
    m.shards = p.result_shards;
    store.put_json(&m)
}
/// Diff compatible serializations; layouts/header bytes must agree so byte identity is unambiguous.
pub fn diff_patch(
    store: &ArtifactStore,
    parent: &ContentId,
    candidate: &ContentId,
    author: String,
    hypothesis: Option<String>,
) -> Result<ContentId> {
    let a = verify_checkpoint(store, parent)?;
    let b = verify_checkpoint(store, candidate)?;
    ensure!(
        a.tensors == b.tensors
            && a.format == b.format
            && a.inference_artifacts == b.inference_artifacts,
        "checkpoint layouts/inference artifacts differ"
    );
    let af = checkpoint_files(&a);
    let bf = checkpoint_files(&b);
    let mut ops = Vec::new();
    for (name, hash) in &af {
        let mut left = File::open(store.path(hash))?;
        let mut right = File::open(store.path(&bf[name]))?;
        let l = layout(&store.path(hash))?;
        let r = layout(&store.path(&bf[name]))?;
        ensure!(l.header_len == r.header_len, "serialization header differs");
        let mut lh = vec![0; l.header_len as usize];
        let mut rh = vec![0; r.header_len as usize];
        left.read_exact(&mut lh)?;
        right.read_exact(&mut rh)?;
        ensure!(lh == rh, "serialization header differs");
        for tensor in l.metadata.offset_keys() {
            let t = l.metadata.info(&tensor).unwrap();
            let dtype = format!("{:?}", t.dtype);
            let len = t.data_offsets.1 - t.data_offsets.0;
            let mut offset = 0;
            while offset < len {
                let n = (len - offset).min(IO_BUFFER_BYTES);
                let mut x = vec![0; n];
                let mut y = vec![0; n];
                left.read_exact(&mut x)?;
                right.read_exact(&mut y)?;
                if x != y {
                    let w = width(&dtype)?;
                    ensure!(n % w == 0, "unaligned diff");
                    ops.push(Replacement {
                        tensor: tensor.clone(),
                        dtype: dtype.clone(),
                        shape: t.shape.clone(),
                        offset: offset / w,
                        count: n / w,
                        payload: store.put(&y)?,
                    });
                    ensure!(ops.len() <= MAX_OPERATIONS, "diff has too many operations");
                }
                offset += n;
            }
        }
    }
    ensure!(!ops.is_empty(), "checkpoints have no tensor differences");
    let patch = create_patch(store, parent, author, ops, hypothesis)?;
    ensure!(
        apply_patch(store, parent, &patch)? == *candidate,
        "candidate serialization differs from reconstructed checkpoint"
    );
    Ok(patch)
}
pub fn export_checkpoint(store: &ArtifactStore, id: &ContentId, dir: &Path) -> Result<()> {
    let m = verify_checkpoint(store, id)?;
    std::fs::create_dir(dir)?;
    for (name, hash) in checkpoint_files(&m) {
        let name = if name.is_empty() {
            "model.safetensors".to_owned()
        } else {
            name
        };
        let mut out = File::create(dir.join(name))?;
        copy_exact(
            &mut store.open_verified(&hash)?,
            &mut out,
            store.verify(&hash)?,
        )?;
        out.sync_all()?;
    }
    if !m.shards.is_empty() {
        std::fs::copy(
            store.path(&m.artifact),
            dir.join("model.safetensors.index.json"),
        )?;
    }
    for (name, hash) in m.inference_artifacts {
        ensure!(safe_shard(&name), "unsafe inference artifact name");
        std::fs::copy(store.path(&hash), dir.join(format!("inference-{name}")))?;
    }
    Ok(())
}
