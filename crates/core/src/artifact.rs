use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File},
    io::{Read, Write},
    path::{Path, PathBuf},
};

/// Limits structured metadata and convenience in-memory reads, never file imports.
pub const MAX_METADATA_BYTES: usize = 32 * 1024 * 1024;
pub const IO_BUFFER_BYTES: usize = 1024 * 1024;

pub fn hash_reader(mut input: impl Read) -> Result<ContentId> {
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; IO_BUFFER_BYTES];
    loop {
        let n = input.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(ContentId(hex::encode(hasher.finalize())))
}
pub fn hash_file(path: &Path) -> Result<ContentId> {
    hash_reader(File::open(path)?)
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct ContentId(String);
impl TryFrom<String> for ContentId {
    type Error = anyhow::Error;
    fn try_from(s: String) -> Result<Self> {
        ensure!(
            s.len() == 64
                && s.bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)),
            "invalid SHA-256 content identity"
        );
        Ok(Self(s))
    }
}
impl From<ContentId> for String {
    fn from(id: ContentId) -> Self {
        id.0
    }
}
impl std::fmt::Display for ContentId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}
pub fn digest(bytes: &[u8]) -> ContentId {
    ContentId(hex::encode(Sha256::digest(bytes)))
}
pub fn json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(value)?)
}
pub fn read_bounded(path: &Path, limit: usize) -> Result<Vec<u8>> {
    let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    ensure!(
        file.metadata()?.len() <= limit as u64,
        "artifact exceeds byte limit"
    );
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= limit, "artifact exceeds byte limit");
    Ok(bytes)
}

/// Local private store. Writers publish atomically without replacing a digest path.
#[derive(Clone)]
pub struct ArtifactStore {
    root: PathBuf,
}
impl ArtifactStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        fs::create_dir_all(root.as_ref())?;
        Ok(Self {
            root: fs::canonicalize(root)?,
        })
    }
    pub fn path(&self, id: &ContentId) -> PathBuf {
        self.root.join(&id.0)
    }
    pub fn put(&self, bytes: &[u8]) -> Result<ContentId> {
        self.put_reader(bytes)
    }
    pub fn put_file(&self, path: &Path) -> Result<ContentId> {
        self.put_reader(File::open(path)?)
    }
    pub fn put_reader(&self, mut input: impl Read) -> Result<ContentId> {
        let mut temp = self.stage()?;
        let mut hasher = Sha256::new();
        let mut buf = vec![0u8; IO_BUFFER_BYTES];
        loop {
            let n = input.read(&mut buf)?;
            if n == 0 {
                break;
            }
            temp.write_all(&buf[..n])?;
            hasher.update(&buf[..n]);
        }
        self.commit(temp, &ContentId(hex::encode(hasher.finalize())))
    }
    pub fn stage(&self) -> Result<tempfile::NamedTempFile> {
        Ok(tempfile::NamedTempFile::new_in(&self.root)?)
    }
    pub fn commit(&self, temp: tempfile::NamedTempFile, expected: &ContentId) -> Result<ContentId> {
        ensure!(
            hash_file(temp.path())? == *expected,
            "artifact integrity mismatch"
        );
        temp.as_file().sync_all()?;
        if let Err(e) = temp.persist_noclobber(self.path(expected)) {
            if e.error.kind() != std::io::ErrorKind::AlreadyExists {
                return Err(e.error.into());
            }
            self.verify(expected)?;
        }
        File::open(&self.root)?.sync_all()?;
        Ok(expected.clone())
    }
    pub fn verify(&self, id: &ContentId) -> Result<u64> {
        let path = self.path(id);
        ensure!(
            fs::symlink_metadata(&path)?.file_type().is_file(),
            "artifact must be a regular file"
        );
        ensure!(hash_file(&path)? == *id, "artifact integrity mismatch");
        Ok(fs::metadata(path)?.len())
    }
    pub fn open_verified(&self, id: &ContentId) -> Result<File> {
        self.verify(id)?;
        Ok(File::open(self.path(id))?)
    }
    pub fn get(&self, id: &ContentId) -> Result<Vec<u8>> {
        let path = self.path(id);
        ensure!(
            !fs::symlink_metadata(&path)?.file_type().is_symlink(),
            "artifact cannot be a symlink"
        );
        let bytes = read_bounded(&path, MAX_METADATA_BYTES)?;
        ensure!(&digest(&bytes) == id, "artifact integrity mismatch");
        Ok(bytes)
    }
    pub fn put_json<T: Serialize>(&self, v: &T) -> Result<ContentId> {
        let bytes = json_bytes(v)?;
        ensure!(bytes.len() <= MAX_METADATA_BYTES, "metadata exceeds limit");
        self.put(&bytes)
    }
    pub fn get_json<T: serde::de::DeserializeOwned>(&self, id: &ContentId) -> Result<T> {
        Ok(serde_json::from_slice(&self.get(id)?)?)
    }
}
