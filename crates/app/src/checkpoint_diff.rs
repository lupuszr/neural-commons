//! Read-only, bounded-memory comparison of the actual saved checkpoint bytes.
use anyhow::{Result, ensure};
use nc_core::*;
use serde_json::{Value, json};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
};

fn number(dtype: &str, bytes: &[u8]) -> f64 {
    match dtype {
        "F32" => f32::from_le_bytes(bytes.try_into().unwrap()) as f64,
        "BF16" => {
            f32::from_bits((u16::from_le_bytes(bytes.try_into().unwrap()) as u32) << 16) as f64
        }
        "F16" => {
            let bits = u16::from_le_bytes(bytes.try_into().unwrap());
            let sign = if bits & 0x8000 != 0 { -1.0 } else { 1.0 };
            let exp = (bits >> 10) & 31;
            let fraction = bits & 1023;
            sign * match exp {
                0 => (fraction as f64) * 2f64.powi(-24),
                31 => {
                    if fraction == 0 {
                        f64::INFINITY
                    } else {
                        f64::NAN
                    }
                }
                _ => (1.0 + fraction as f64 / 1024.0) * 2f64.powi(exp as i32 - 15),
            }
        }
        _ => unreachable!(),
    }
}
fn value(n: f64) -> Value {
    if n.is_finite() {
        json!(n)
    } else if n.is_nan() {
        json!("NaN")
    } else if n.is_sign_positive() {
        json!("Infinity")
    } else {
        json!("-Infinity")
    }
}
pub fn compare(
    store: &ArtifactStore,
    base: &ContentId,
    candidate: &ContentId,
    filter: Option<&str>,
    offset: usize,
    limit: usize,
) -> Result<Value> {
    ensure!(
        (1..=200).contains(&limit),
        "Page size must be between 1 and 200"
    );
    let a = verify_checkpoint(store, base)?;
    let b = verify_checkpoint(store, candidate)?;
    ensure!(
        a.tensors == b.tensors,
        "Checkpoints have different tensor layouts"
    );
    ensure!(
        filter.is_none_or(|name| a.tensors.iter().any(|t| t.name == name)),
        "Unknown tensor"
    );
    let left = checkpoint_files(&a);
    let right = checkpoint_files(&b);
    ensure!(
        left.keys().eq(right.keys()),
        "Checkpoint shard layouts differ"
    );
    let mut summaries = Vec::new();
    let mut changes = Vec::new();
    let mut total = 0usize;
    let mut matched = 0usize;
    let mut x = vec![0; 1024 * 1024];
    let mut y = vec![0; 1024 * 1024];
    for (shard, id) in left {
        let lp = store.path(&id);
        let rp = store.path(&right[&shard]);
        let l = layout(&lp)?;
        let r = layout(&rp)?;
        let lt = l.metadata.tensors();
        let rt = r.metadata.tensors();
        let mut lf = File::open(lp)?;
        let mut rf = File::open(rp)?;
        for t in a
            .tensors
            .iter()
            .filter(|t| t.shard.as_deref().unwrap_or("") == shard)
        {
            let width = match t.dtype.as_str() {
                "F32" => 4,
                "F16" | "BF16" => 2,
                _ => 0,
            };
            lf.seek(SeekFrom::Start(
                l.header_len + lt[&t.name].data_offsets.0 as u64,
            ))?;
            rf.seek(SeekFrom::Start(
                r.header_len + rt[&t.name].data_offsets.0 as u64,
            ))?;
            let mut changed = 0usize;
            let mut max_delta = 0.0f64;
            let mut start = 0usize;
            while start < t.bytes {
                let n = (t.bytes - start).min(x.len());
                lf.read_exact(&mut x[..n])?;
                rf.read_exact(&mut y[..n])?;
                if x[..n] != y[..n] {
                    ensure!(
                        width > 0,
                        "Changed tensor has unsupported dtype: {}",
                        t.dtype
                    );
                    for pos in (0..n).step_by(width) {
                        if x[pos..pos + width] == y[pos..pos + width] {
                            continue;
                        }
                        changed += 1;
                        total += 1;
                        let before = number(&t.dtype, &x[pos..pos + width]);
                        let after = number(&t.dtype, &y[pos..pos + width]);
                        let delta = after - before;
                        if delta.is_finite() {
                            max_delta = max_delta.max(delta.abs());
                        }
                        if filter.is_none_or(|name| name == t.name) {
                            if matched >= offset && changes.len() < limit {
                                let index = (start + pos) / width;
                                let mut flat = index;
                                let mut coordinates = Vec::new();
                                for dim in t.shape.iter().rev() {
                                    coordinates.push(flat % dim);
                                    flat /= dim;
                                }
                                coordinates.reverse();
                                changes.push(json!({"tensor":t.name,"index":index,"coordinates":coordinates,"before":value(before),"after":value(after),"delta":value(delta)}));
                            }
                            matched += 1;
                        }
                    }
                }
                start += n;
            }
            summaries.push(json!({"name":t.name,"changed":changed,"values":t.shape.iter().product::<usize>(),"max_abs_delta":max_delta}));
        }
    }
    Ok(
        json!({"base":base,"candidate":candidate,"changed":total,"changed_tensors":summaries.iter().filter(|t|t["changed"].as_u64().unwrap_or(0)>0).count(),"tensors":summaries,"changes":changes,"matching_changes":matched,"offset":offset,"limit":limit,"has_more":offset.saturating_add(limit)<matched,"comparison":"stored-value-bits"}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    #[test]
    fn counts_actual_changes_and_pages_values_not_patch_ranges() {
        let temp = tempfile::tempdir().unwrap();
        let store = ArtifactStore::open(temp.path()).unwrap();
        let model = |v| {
            register(
                &store,
                &encode_f32(BTreeMap::from([("layer.weight".into(), (vec![2, 2], v))])).unwrap(),
            )
            .unwrap()
        };
        let a = model(vec![1., 2., 3., 4.]);
        let b = model(vec![1., 2.5, 3., -4.]);
        let d = compare(&store, &a, &b, None, 0, 1).unwrap();
        assert_eq!(d["changed"], 2);
        assert_eq!(d["has_more"], true);
        assert_eq!(d["changes"][0]["coordinates"], json!([0, 1]));
        assert_eq!(d["changes"][0]["delta"], 0.5);
        let next = compare(&store, &a, &b, Some("layer.weight"), 1, 1).unwrap();
        assert_eq!(next["changes"][0]["before"], 4.);
        assert_eq!(next["changes"][0]["after"], -4.);
        assert_eq!(next["has_more"], false);
        assert_eq!(compare(&store, &a, &a, None, 0, 100).unwrap()["changed"], 0);
        assert!(compare(&store, &a, &b, Some("missing"), 0, 100).is_err());
    }
    #[test]
    fn decode_low_precision_without_rounding_away_changes() {
        assert_eq!(number("BF16", &0x3f80u16.to_le_bytes()), 1.);
        assert_eq!(number("BF16", &0x3f81u16.to_le_bytes()), 1.0078125);
        assert_eq!(number("F16", &0x3c00u16.to_le_bytes()), 1.);
        assert_eq!(number("F16", &1u16.to_le_bytes()), 2f64.powi(-24));
        assert_eq!(
            value(number("F16", &0x7c00u16.to_le_bytes())),
            json!("Infinity")
        );
    }
}
