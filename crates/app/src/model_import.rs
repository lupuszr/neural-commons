//! Import a local Transformers model folder without requiring a mapping file.
use anyhow::{Context, Result, ensure};
use nc_core::{ArtifactStore, ContentId, read_bounded, register_file};
use serde_json::{Value, json};
use std::path::Path;

pub fn import(store: &ArtifactStore, directory: &Path) -> Result<(ContentId, String)> {
    ensure!(
        directory.is_absolute(),
        "Enter the full path to your model folder"
    );
    ensure!(directory.is_dir(), "Model folder does not exist");
    ensure!(
        !directory.join("model.safetensors.index.json").exists(),
        "This experiment runner currently supports a single model.safetensors file; sharded models are not supported here"
    );
    let required = [
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ];
    let missing: Vec<_> = required
        .iter()
        .filter(|name| !directory.join(name).is_file())
        .copied()
        .collect();
    ensure!(
        missing.is_empty(),
        "Model folder is missing: {}",
        missing.join(", ")
    );
    // Read/validate metadata before importing the large weights. Preserve exact bytes.
    let mut metadata = Vec::new();
    for (key, name) in [
        ("model_config", "config.json"),
        ("tokenizer", "tokenizer.json"),
        ("tokenizer_config", "tokenizer_config.json"),
    ] {
        let bytes = read_bounded(&directory.join(name), 32 * 1024 * 1024)?;
        let value: Value =
            serde_json::from_slice(&bytes).with_context(|| format!("Invalid JSON in {name}"))?;
        ensure!(value.is_object(), "{name} must contain a JSON object");
        metadata.push((key, bytes, value));
    }
    let special = directory.join("special_tokens_map.json");
    let special_bytes = if special.is_file() {
        let bytes = read_bounded(&special, 1024 * 1024)?;
        let value: Value =
            serde_json::from_slice(&bytes).context("Invalid JSON in special_tokens_map.json")?;
        ensure!(
            value.is_object(),
            "special_tokens_map.json must contain a JSON object"
        );
        bytes
    } else {
        // Transformers also stores these fields in tokenizer_config.json.
        let config = &metadata[2].2;
        let mut values = serde_json::Map::new();
        for key in [
            "bos_token",
            "eos_token",
            "unk_token",
            "sep_token",
            "pad_token",
            "cls_token",
            "mask_token",
            "additional_special_tokens",
        ] {
            if let Some(value) = config.get(key) {
                values.insert(key.into(), value.clone());
            }
        }
        serde_json::to_vec(&values)?
    };
    let name = metadata[0]
        .2
        .get("_name_or_path")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| {
            directory
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned()
        });
    let mut manifest = register_file(store, &directory.join("model.safetensors"))?;
    for (key, bytes, _) in metadata {
        manifest
            .inference_artifacts
            .insert(key.into(), store.put(&bytes)?);
    }
    manifest
        .inference_artifacts
        .insert("special_tokens".into(), store.put(&special_bytes)?);
    manifest.inference_artifacts.insert(
        "source".into(),
        store.put_json(&json!({"model":name,"import":"local-folder"}))?,
    );
    Ok((store.put_json(&manifest)?, name))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{collections::BTreeMap, fs};
    fn fixture() -> (tempfile::TempDir, ArtifactStore, std::path::PathBuf) {
        let temp = tempfile::tempdir().unwrap();
        let folder = temp.path().join("my-model");
        fs::create_dir(&folder).unwrap();
        fs::write(
            folder.join("model.safetensors"),
            nc_core::encode_f32(BTreeMap::from([("weight".into(), (vec![1], vec![1.0]))])).unwrap(),
        )
        .unwrap();
        fs::write(
            folder.join("config.json"),
            br#"{"_name_or_path":"Example/model"}"#,
        )
        .unwrap();
        fs::write(folder.join("tokenizer.json"), b"{}").unwrap();
        fs::write(
            folder.join("tokenizer_config.json"),
            br#"{"eos_token":"</s>"}"#,
        )
        .unwrap();
        let store = ArtifactStore::open(temp.path().join("artifacts")).unwrap();
        (temp, store, folder)
    }
    #[test]
    fn imports_inference_files_idempotently_without_modifying_source() {
        let (_temp, store, folder) = fixture();
        let (id, name) = import(&store, &folder).unwrap();
        assert_eq!(name, "Example/model");
        let model = nc_core::verify_checkpoint(&store, &id).unwrap();
        let special: Value = store
            .get_json(&model.inference_artifacts["special_tokens"])
            .unwrap();
        assert_eq!(special["eos_token"], "</s>");
        assert!(!folder.join("special_tokens_map.json").exists());
        assert_eq!(import(&store, &folder).unwrap().0, id);
        fs::write(
            folder.join("special_tokens_map.json"),
            br#"{"pad_token":"<pad>"}"#,
        )
        .unwrap();
        let (other, _) = import(&store, &folder).unwrap();
        let model = nc_core::verify_checkpoint(&store, &other).unwrap();
        let special: Value = store
            .get_json(&model.inference_artifacts["special_tokens"])
            .unwrap();
        assert_eq!(special["pad_token"], "<pad>");
    }
    #[test]
    fn rejects_missing_invalid_and_sharded_models() {
        let (_temp, store, folder) = fixture();
        fs::remove_file(folder.join("tokenizer.json")).unwrap();
        assert!(
            import(&store, &folder)
                .unwrap_err()
                .to_string()
                .contains("tokenizer.json")
        );
        fs::write(folder.join("tokenizer.json"), b"invalid").unwrap();
        assert!(
            import(&store, &folder)
                .unwrap_err()
                .to_string()
                .contains("Invalid JSON")
        );
        fs::write(folder.join("model.safetensors.index.json"), b"{}").unwrap();
        assert!(
            import(&store, &folder)
                .unwrap_err()
                .to_string()
                .contains("sharded")
        );
    }
}
