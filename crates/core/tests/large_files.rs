use nc_core::*;
use std::{
    collections::BTreeMap,
    fs::File,
    io::{Seek, SeekFrom, Write},
};
fn tensor_file(path: &std::path::Path, dtype: &str, elements: usize, width: usize) {
    let header=serde_json::to_vec(&serde_json::json!({"weights":{"dtype":dtype,"shape":[elements],"data_offsets":[0,elements*width]}})).unwrap();
    let mut f = File::create(path).unwrap();
    f.write_all(&(header.len() as u64).to_le_bytes()).unwrap();
    f.write_all(&header).unwrap();
    f.set_len(8 + header.len() as u64 + (elements * width) as u64)
        .unwrap();
}
#[test]
fn large_checkpoint_streams_and_reconstructs_byte_exactly() {
    let dir = tempfile::tempdir().unwrap();
    let s = ArtifactStore::open(dir.path().join("store")).unwrap();
    let path = dir.path().join("large.safetensors");
    tensor_file(&path, "F32", 20 * 1024 * 1024, 4);
    let base = register_file(&s, &path).unwrap();
    let base_id = s.put_json(&base).unwrap();
    let mut candidate = File::options().write(true).open(&path).unwrap();
    candidate.seek(SeekFrom::End(-4)).unwrap();
    candidate.write_all(&7f32.to_le_bytes()).unwrap();
    drop(candidate);
    let changed = register_file(&s, &path).unwrap();
    let changed_id = s.put_json(&changed).unwrap();
    let patch = diff_patch(&s, &base_id, &changed_id, "author".into(), None).unwrap();
    assert_eq!(apply_patch(&s, &base_id, &patch).unwrap(), changed_id);
    assert!(s.verify(&base.artifact).unwrap() > 64 * 1024 * 1024);
    let output = dir.path().join("export");
    export_checkpoint(&s, &changed_id, &output).unwrap();
    assert_eq!(
        hash_file(&output.join("model.safetensors")).unwrap(),
        changed.artifact
    );
}
#[test]
fn sharded_half_precision_edits_validate_and_preserve_other_shards() {
    let dir = tempfile::tempdir().unwrap();
    let s = ArtifactStore::open(dir.path().join("store")).unwrap();
    tensor_file(&dir.path().join("a.safetensors"), "F16", 8, 2);
    let b = encode_f32(BTreeMap::from([("other".into(), (vec![1], vec![9.]))])).unwrap();
    std::fs::write(dir.path().join("b.safetensors"), b).unwrap();
    let index = dir.path().join("model.safetensors.index.json");
    std::fs::write(
        &index,
        r#"{"weight_map":{"weights":"a.safetensors","other":"b.safetensors"}}"#,
    )
    .unwrap();
    let m = register_file(&s, &index).unwrap();
    let parent = s.put_json(&m).unwrap();
    let op = Replacement {
        tensor: "weights".into(),
        dtype: "F16".into(),
        shape: vec![8],
        offset: 2,
        count: 1,
        payload: s.put(&0x3c00u16.to_le_bytes()).unwrap(),
    };
    let p = create_patch(&s, &parent, "author".into(), vec![op.clone()], None).unwrap();
    let out = verify_checkpoint(&s, &apply_patch(&s, &parent, &p).unwrap()).unwrap();
    assert_eq!(out.shards["b.safetensors"], m.shards["b.safetensors"]);
    assert_ne!(out.shards["a.safetensors"], m.shards["a.safetensors"]);
    let invalid = Replacement {
        payload: s.put(&0x7c00u16.to_le_bytes()).unwrap(),
        ..op
    };
    assert!(create_patch(&s, &parent, "author".into(), vec![invalid], None).is_err());
    tensor_file(&dir.path().join("bf.safetensors"), "BF16", 3, 2);
    let bf = register_file(&s, &dir.path().join("bf.safetensors")).unwrap();
    let bf = s.put_json(&bf).unwrap();
    for (value, valid) in [(0x3f80u16, true), (0x7f80, false), (0x7fc0, false)] {
        let op = Replacement {
            tensor: "weights".into(),
            dtype: "BF16".into(),
            shape: vec![3],
            offset: 0,
            count: 1,
            payload: s.put(&value.to_le_bytes()).unwrap(),
        };
        assert_eq!(
            create_patch(&s, &bf, "author".into(), vec![op], None).is_ok(),
            valid
        );
    }
    std::fs::write(&index, r#"{"weight_map":{"weights":"../escape"}}"#).unwrap();
    assert!(register_file(&s, &index).is_err());
}
