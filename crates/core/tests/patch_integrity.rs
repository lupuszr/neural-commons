use nc_core::*;
use std::collections::BTreeMap;

fn fixture(name: &str, shape: Vec<usize>, data: Vec<f32>) -> Vec<u8> {
    encode_f32(BTreeMap::from([
        (name.into(), (shape, data)),
        ("untouched".into(), (vec![], vec![42.])),
    ]))
    .unwrap()
}
#[test]
fn unrelated_layouts_patch_deterministically_and_preserve_every_other_byte() {
    for (name, shape, data, offset) in [
        ("projection", vec![2, 3], vec![0.; 6], 4),
        ("strange/name/β", vec![1, 2, 2, 2], vec![1.; 8], 2),
        ("scalar", vec![], vec![3.], 0),
    ] {
        let tmp = tempfile::tempdir().unwrap();
        let store = ArtifactStore::open(tmp.path()).unwrap();
        let bytes = fixture(name, shape.clone(), data);
        let parent = register(&store, &bytes).unwrap();
        let payload = store.put(&9f32.to_le_bytes()).unwrap();
        let op = Replacement {
            tensor: name.into(),
            dtype: "F32".into(),
            shape,
            offset,
            count: 1,
            payload,
        };
        let patch = create_patch(&store, &parent, "test-author".into(), vec![op], None).unwrap();
        let result = apply_patch(&store, &parent, &patch).unwrap();
        assert_eq!(result, apply_patch(&store, &parent, &patch).unwrap());
        let (_, out) = load_checkpoint(&store, &result).unwrap();
        assert_eq!(f32_tensor(&out, name).unwrap().1[offset], 9.);
        assert_eq!(f32_tensor(&out, "untouched").unwrap().1, vec![42.]);
        assert_eq!(store.get(&digest(&bytes)).unwrap(), bytes);
        assert!(bytes.iter().zip(out.iter()).filter(|(a, b)| a != b).count() <= 4);
    }
}
#[test]
fn rejects_bad_regions_wrong_parents_tampering_and_nonfinite_values() {
    let tmp = tempfile::tempdir().unwrap();
    let s = ArtifactStore::open(tmp.path()).unwrap();
    let parent = register(&s, &fixture("x", vec![2], vec![0., 1.])).unwrap();
    let payload = s.put(&2f32.to_le_bytes()).unwrap();
    let op = Replacement {
        tensor: "x".into(),
        dtype: "F32".into(),
        shape: vec![2],
        offset: 1,
        count: 1,
        payload: payload.clone(),
    };
    for bad in [
        Replacement {
            offset: 2,
            ..op.clone()
        },
        Replacement {
            shape: vec![1, 2],
            ..op.clone()
        },
        Replacement {
            dtype: "F16".into(),
            ..op.clone()
        },
        Replacement {
            count: 2,
            offset: 0,
            ..op.clone()
        },
        Replacement {
            offset: usize::MAX,
            ..op.clone()
        },
        Replacement {
            payload: s.put(&f32::NAN.to_le_bytes()).unwrap(),
            ..op.clone()
        },
    ] {
        assert!(create_patch(&s, &parent, "a".into(), vec![bad], None).is_err());
    }
    assert!(create_patch(&s, &parent, "a".into(), vec![op.clone(), op.clone()], None).is_err());
    let patch = create_patch(&s, &parent, "a".into(), vec![op], None).unwrap();
    let other = register(&s, &fixture("x", vec![2], vec![3., 1.])).unwrap();
    assert!(apply_patch(&s, &other, &patch).is_err());
    let mut m: Patch = s.get_json(&patch).unwrap();
    m.result_artifact = digest(b"wrong");
    assert!(apply_patch(&s, &parent, &s.put_json(&m).unwrap()).is_err());
    std::fs::write(s.path(&payload), 3f32.to_le_bytes()).unwrap();
    assert!(apply_patch(&s, &parent, &patch).is_err());
    assert!(inspect(&vec![0; MAX_METADATA_BYTES + 1]).is_err());
    assert!(ContentId::try_from("../escape".to_owned()).is_err());
}
