use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
};

pub fn folders(raw: Option<&str>, kind: &str, hidden: bool) -> Result<Value> {
    ensure!(["task", "model"].contains(&kind), "Unsupported folder type");
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .context("Home folder unavailable")?;
    let workspace = std::env::current_dir()?;
    let requested = raw
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            if kind == "model" {
                home.join("Downloads")
            } else {
                workspace.clone()
            }
        });
    ensure!(requested.is_absolute(), "Choose an absolute folder path");
    let path = requested
        .canonicalize()
        .context("Folder does not exist or is not accessible")?;
    ensure!(path.is_dir(), "Choose a folder, not a file");
    let mut entries = Vec::new();
    let mut truncated = false;
    for item in fs::read_dir(&path).context("Cannot read this folder")? {
        let item = item?;
        let name = item.file_name().to_string_lossy().to_string();
        if !hidden && name.starts_with('.') {
            continue;
        }
        if !item.path().is_dir() {
            continue;
        }
        if entries.len() >= 2000 {
            truncated = true;
            break;
        }
        entries.push(json!({"name":name,"path":item.path()}));
    }
    entries.sort_by_key(|v| v["name"].as_str().unwrap_or("").to_lowercase());
    let (checks, selectable, message) = check_folder(&path, kind);
    Ok(
        json!({"path":path,"parent":path.parent(),"entries":entries,"truncated":truncated,
        "shortcuts":[{"name":"Workspace","path":workspace},{"name":"Downloads","path":home.join("Downloads")},{"name":"Home","path":home}],
        "checks":checks,"selectable":selectable,"message":message}),
    )
}
fn check_folder(path: &Path, kind: &str) -> (Vec<Value>, bool, String) {
    let mut names = if kind == "task" {
        vec![
            "config.json",
            "development.json",
            "selection.json",
            "heldout.json",
            "policy.json",
            "source.json",
        ]
    } else {
        vec![
            "model.safetensors",
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ]
    };
    if kind == "task"
        && let Ok(bytes) = nc_core::read_bounded(&path.join("config.json"), 32 * 1024 * 1024)
        && let Ok(config) = serde_json::from_slice::<Value>(&bytes)
        && config.get("guard").is_some()
    {
        names.extend(["guard.json", "guard-config.json"]);
    }
    let checks: Vec<_> = names
        .iter()
        .map(|name| json!({"name":name,"present":path.join(name).is_file()}))
        .collect();
    let all = checks.iter().all(|v| v["present"] == true);
    let sharded = kind == "model" && path.join("model.safetensors.index.json").exists();
    let message = if sharded {
        "Choose a single-file Safetensors model; sharded models are not supported by this runner."
    } else if all {
        "Required files found. Contents are validated when you start."
    } else {
        "Open a folder containing the required files below."
    };
    (checks, all && !sharded, message.into())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn folder_checks_and_listing_do_not_accept_incomplete_tasks() {
        let temp = tempfile::tempdir().unwrap();
        let p = temp.path();
        fs::create_dir(p.join("visible")).unwrap();
        fs::create_dir(p.join(".hidden")).unwrap();
        let result = folders(p.to_str(), "task", false).unwrap();
        assert_eq!(result["entries"].as_array().unwrap().len(), 1);
        assert_eq!(result["selectable"], false);
        for file in [
            "config",
            "development",
            "selection",
            "heldout",
            "policy",
            "source",
        ] {
            fs::write(p.join(format!("{file}.json")), b"{}").unwrap();
        }
        assert_eq!(
            folders(p.to_str(), "task", true).unwrap()["selectable"],
            true
        );
        fs::write(p.join("config.json"), br#"{"guard":{}}"#).unwrap();
        assert_eq!(
            folders(p.to_str(), "task", true).unwrap()["selectable"],
            false
        );
        assert!(folders(Some("relative"), "task", false).is_err());
        assert!(folders(p.to_str(), "unknown", false).is_err());
    }
}
