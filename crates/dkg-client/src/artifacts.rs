//! DKG is the only peer artifact transport. Bounded blobs adapt its buffered upload API.
use super::*;
use base64::{Engine, engine::general_purpose::STANDARD};
use std::io::{Seek, SeekFrom, Write};
const BLOB_BYTES: usize = 8 * 1024 * 1024;
const PAGE_BYTES: usize = 1024 * 1024;
const DELIVERY: &str = "urn:neural-commons:delivery:v1";
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Blob {
    sha256: ContentId,
    dkg_hash: String,
    assertion_uri: String,
    peer_id: String,
    size: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FileManifest {
    schema: String,
    artifact: ContentId,
    size: u64,
    parts: Vec<Blob>,
}
impl DkgClient {
    fn read_delivery(&self, id: &ContentId, author: &str) -> Result<Option<Blob>> {
        let q = format!(
            "SELECT ?g ?delivery WHERE {{ GRAPH ?g {{ <urn:sha256:{id}> <{DELIVERY}> ?delivery }} }} LIMIT 64"
        );
        let value = self.post(
            "api/query",
            &json!({"contextGraphId":self.graph,"graphSuffix":"_shared_memory","sparql":q}),
        )?;
        let rows = value
            .pointer("/result/bindings")
            .and_then(Value::as_array)
            .context("missing delivery bindings")?;
        let mut found = None;
        for row in rows {
            let graph = row["g"].as_str().context("missing authenticated graph")?;
            if verify_placement(&self.graph, author, graph).is_err() {
                continue;
            }
            let raw = row["delivery"]
                .as_str()
                .context("missing delivery literal")?;
            let raw = if raw.starts_with('"') {
                serde_json::from_str::<String>(raw)?
            } else {
                raw.to_string()
            };
            let blob: Blob = serde_json::from_str(&raw)?;
            ensure!(found.is_none(), "ambiguous DKG artifact delivery");
            found = Some(blob);
        }
        Ok(found)
    }
    fn upload_blob(&self, bytes: Vec<u8>, identity: &Identity) -> Result<Blob> {
        let sha256 = digest(&bytes);
        let size = bytes.len() as u64;
        let name = format!("nc-blob-{sha256}");
        // A lost response is safe to repeat while the deterministic blob KA stays in WM.
        // Blob authorization metadata stays on its owning daemon; the signed delivery KA
        // publishes the immutable locator and both hashes to peers.
        let form = reqwest::blocking::multipart::Form::new()
            .text("contextGraphId", self.graph.clone())
            .text("contentType", "application/octet-stream")
            .part(
                "file",
                reqwest::blocking::multipart::Part::bytes(bytes)
                    .file_name("blob.bin")
                    .mime_str("application/octet-stream")?,
            );
        let result = response(
            self.client
                .post(
                    self.base
                        .join(&format!("api/knowledge-assets/{name}/wm/import-file"))?,
                )
                .bearer_auth(&self.token)
                .multipart(form)
                .send()?,
        )?;
        let hash = result["fileHash"]
            .as_str()
            .context("DKG upload missing fileHash")?
            .to_string();
        let assertion = result["assertionUri"]
            .as_str()
            .context("DKG upload missing assertionUri")?
            .to_string();
        ensure!(
            hash.starts_with("keccak256:") && hash.len() == 74,
            "invalid DKG content identity"
        );
        Ok(Blob {
            sha256,
            dkg_hash: hash,
            assertion_uri: assertion,
            peer_id: identity.peer_id.clone(),
            size,
        })
    }
    pub fn upload_bundle(&self, store: &ArtifactStore, record: &Record) -> Result<()> {
        validate_record(record)?;
        self.check_graph_access()?;
        let identity = self.identity()?;
        ensure!(
            identity.address == record.author,
            "artifact author mismatch"
        );
        for id in &record.artifacts {
            if self.read_delivery(id, &identity.address)?.is_some() {
                continue;
            }
            let size = store.verify(id)?;
            let mut file = store.open_verified(id)?;
            let mut parts = Vec::new();
            loop {
                let mut bytes = Vec::new();
                Read::by_ref(&mut file)
                    .take(BLOB_BYTES as u64)
                    .read_to_end(&mut bytes)?;
                if bytes.is_empty() {
                    break;
                }
                parts.push(self.upload_blob(bytes, &identity)?);
            }
            let manifest = FileManifest {
                schema: "nc/dkg-file/v1".into(),
                artifact: id.clone(),
                size,
                parts,
            };
            let bytes = json_bytes(&manifest)?;
            ensure!(
                bytes.len() <= BLOB_BYTES,
                "artifact part manifest exceeds metadata budget"
            );
            let root = self.upload_blob(bytes, &identity)?;
            let subject = format!("urn:sha256:{id}");
            let literal = serde_json::to_string(&serde_json::to_string(&root)?)?;
            let mut quads =
                vec![json!({"subject":subject,"predicate":DELIVERY,"object":literal,"graph":""})];
            for blob in std::iter::once(&root).chain(manifest.parts.iter()) {
                quads.push(json!({"subject":blob.assertion_uri,"predicate":"http://dkg.io/ontology/sourceFile","object":format!("urn:dkg:file:{}",blob.dkg_hash),"graph":""}));
                quads.push(json!({"subject":blob.assertion_uri,"predicate":"http://dkg.io/ontology/sourceContentType","object":"\"application/octet-stream\"","graph":""}));
            }
            let receipt=self.post("api/knowledge-assets",&json!({"contextGraphId":self.graph,"name":format!("nc-file-{id}"),"finalize":true,"alsoShareSwm":true,"alsoPublishVm":false,"quads":quads}))?;
            ensure!(
                receipt["status"] == "swm-shared",
                "DKG artifact delivery share incomplete; retry reconciles deterministic name"
            );
        }
        Ok(())
    }
    fn download_blob(&self, blob: &Blob, author: &str, mut output: impl Write) -> Result<()> {
        ensure!(
            blob.size <= BLOB_BYTES as u64,
            "DKG blob exceeds page adapter budget"
        );
        let prefix = format!("did:dkg:context-graph:{}/assertion/{}/", self.graph, author);
        ensure!(
            blob.assertion_uri
                .to_lowercase()
                .starts_with(&prefix.to_lowercase()),
            "blob ownership/graph mismatch"
        );
        ensure!(
            blob.dkg_hash.starts_with("keccak256:")
                && blob.dkg_hash.len() == 74
                && blob.dkg_hash[10..].bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid DKG hash"
        );
        let mut offset = 0;
        let mut all = Vec::with_capacity(blob.size as usize);
        while offset < blob.size {
            let page=self.post("api/knowledge-assets/import-artifact/read",&json!({"contextGraphId":self.graph,"assertionUri":blob.assertion_uri,"kind":"source","hash":blob.dkg_hash,"sourcePeerId":blob.peer_id,"offset":offset,"maxBytes":PAGE_BYTES,"cache":false}))?;
            let status = page["status"].as_str().unwrap_or("missing");
            ensure!(
                ["local", "fetched", "unverified"].contains(&status),
                "DKG artifact unavailable: {status}"
            );
            ensure!(
                page["hash"] == blob.dkg_hash
                    && page["offset"].as_u64() == Some(offset)
                    && page["size"].as_u64() == Some(blob.size),
                "DKG artifact page identity/size mismatch"
            );
            let bytes =
                STANDARD.decode(page["bytesB64"].as_str().context("missing page bytes")?)?;
            ensure!(
                !bytes.is_empty()
                    && bytes.len() <= PAGE_BYTES
                    && offset + bytes.len() as u64 <= blob.size,
                "invalid artifact page range"
            );
            offset += bytes.len() as u64;
            ensure!(
                page["truncated"].as_bool() == Some(offset < blob.size),
                "invalid truncated flag"
            );
            if offset < blob.size {
                ensure!(
                    page["nextOffset"].as_u64() == Some(offset),
                    "noncontiguous artifact pages"
                );
            }
            all.extend_from_slice(&bytes);
        }
        ensure!(
            digest(&all) == blob.sha256,
            "downloaded blob integrity mismatch"
        );
        output.write_all(&all)?;
        Ok(())
    }
    pub fn download_bundle(&self, store: &ArtifactStore, record: &Record) -> Result<()> {
        validate_record(record)?;
        self.check_graph_access()?;
        for id in &record.artifacts {
            if store.path(id).exists() {
                store.verify(id)?;
                continue;
            }
            let root = self
                .read_delivery(id, &record.author)?
                .context("DKG artifact delivery unavailable")?;
            let mut manifest_bytes = Vec::new();
            self.download_blob(&root, &record.author, &mut manifest_bytes)?;
            let manifest: FileManifest = serde_json::from_slice(&manifest_bytes)?;
            ensure!(
                manifest.schema == "nc/dkg-file/v1" && manifest.artifact == *id,
                "artifact manifest identity mismatch"
            );
            let size = manifest.parts.iter().try_fold(0u64, |a, b| {
                a.checked_add(b.size).context("artifact size overflow")
            })?;
            ensure!(size == manifest.size, "artifact manifest size mismatch");
            // Verified individual blobs survive retries; they are local cache, never another transport.
            let mut staged = store.stage()?;
            for part in &manifest.parts {
                if !store.path(&part.sha256).exists() {
                    let mut file = store.stage()?;
                    self.download_blob(part, &record.author, &mut file)?;
                    store.commit(file, &part.sha256)?;
                }
                let mut cached = store.open_verified(&part.sha256)?;
                ensure!(
                    cached.metadata()?.len() == part.size,
                    "cached blob size mismatch"
                );
                std::io::copy(&mut cached, &mut staged)?;
            }
            staged.seek(SeekFrom::Start(0))?;
            store.commit(staged, id)?;
        }
        Ok(())
    }
}
