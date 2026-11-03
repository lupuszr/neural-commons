//! Repeatable memory acceptance gate; intentionally larger than the working buffers.
use nc_core::*;
use std::{fs::File, io::Write};
fn main() -> anyhow::Result<()> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("large.safetensors");
    let elements = 128 * 1024 * 1024;
    let header = serde_json::to_vec(
        &serde_json::json!({"weights":{"dtype":"F32","shape":[elements],"data_offsets":[0,elements*4]}}),
    )?;
    let mut f = File::create(&path)?;
    f.write_all(&(header.len() as u64).to_le_bytes())?;
    f.write_all(&header)?;
    f.set_len(8 + header.len() as u64 + (elements * 4) as u64)?;
    drop(f);
    let store = ArtifactStore::open(dir.path().join("store"))?;
    let m = register_file(&store, &path)?;
    let parent = store.put_json(&m)?;
    let patch = create_patch(
        &store,
        &parent,
        "memory-benchmark".into(),
        vec![Replacement {
            tensor: "weights".into(),
            dtype: "F32".into(),
            shape: vec![elements],
            offset: elements - 1,
            count: 1,
            payload: store.put(&1f32.to_le_bytes())?,
        }],
        None,
    )?;
    let candidate = apply_patch(&store, &parent, &patch)?;
    let output = verify_checkpoint(&store, &candidate)?;
    assert_ne!(m.artifact, output.artifact);
    println!(
        "{}",
        serde_json::json!({"status":"passed","file_bytes":std::fs::metadata(path)?.len(),"io_buffer_bytes":IO_BUFFER_BYTES,"base":parent,"candidate":candidate,"patch":patch})
    );
    Ok(())
}
