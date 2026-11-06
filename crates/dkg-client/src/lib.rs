//! Authenticated named Knowledge Assets; no public-chain publication.
mod artifacts;
use anyhow::{Context, Result, ensure};
use nc_core::*;
use reqwest::{Url, blocking::Client, redirect::Policy};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{io::Read, path::Path, time::Duration};

pub const NS: &str = "urn:neural-commons:v1:";
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub schema: String,
    pub kind: String,
    pub author: String,
    pub context_graph: String,
    pub artifact: ContentId,
    pub artifacts: Vec<ContentId>,
    pub artifact_origin: String,
    pub relates_to: Option<ContentId>,
    pub fixture: bool,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Identity {
    #[serde(rename = "agentAddress")]
    pub address: String,
    #[serde(rename = "peerId")]
    pub peer_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}
#[derive(Debug, Serialize)]
pub struct SharedProposal {
    pub id: ContentId,
    pub record: Record,
}
#[derive(Debug, Serialize)]
pub struct SharedProposals {
    pub records: Vec<SharedProposal>,
    pub offset: usize,
    pub next_offset: Option<usize>,
}
pub struct DkgClient {
    client: Client,
    base: Url,
    token: String,
    pub graph: String,
}
fn local_url(s: &str) -> Result<Url> {
    let u = Url::parse(s)?;
    ensure!(
        u.scheme() == "http"
            && u.host_str() == Some("127.0.0.1")
            && u.port().is_some()
            && u.username().is_empty()
            && u.password().is_none()
            && u.path() == "/"
            && u.query().is_none()
            && u.fragment().is_none(),
        "v1 supports explicitly configured loopback HTTP origins only"
    );
    Ok(u)
}
pub fn read_token(path: &Path) -> Result<String> {
    let value = String::from_utf8(read_bounded(path, 4096)?)?
        .trim()
        .to_owned();
    ensure!(
        value.len() >= 32
            && value
                .bytes()
                .all(|x| x.is_ascii_alphanumeric() || b"-_.".contains(&x)),
        "invalid token file"
    );
    Ok(value)
}
fn client() -> Result<Client> {
    Ok(Client::builder()
        .timeout(Duration::from_secs(30))
        .connect_timeout(Duration::from_secs(3))
        .redirect(Policy::none())
        .no_proxy()
        .build()?)
}
fn response(r: reqwest::blocking::Response) -> Result<Value> {
    let status = r.status();
    let mut bytes = Vec::new();
    r.take(2 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 2 * 1024 * 1024, "DKG response exceeds limit");
    if !status.is_success() {
        let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
        anyhow::bail!(
            "DKG HTTP {}: {}",
            status.as_u16(),
            body.get("code")
                .or_else(|| body.get("error"))
                .and_then(Value::as_str)
                .unwrap_or("request failed")
        );
    }
    Ok(serde_json::from_slice(&bytes)?)
}
impl DkgClient {
    pub fn new(base: &str, token_file: &Path, graph: String) -> Result<Self> {
        ensure!(
            !graph.is_empty()
                && graph.len() <= 256
                && graph
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_/".contains(&b)),
            "invalid demo graph id"
        );
        Ok(Self {
            client: client()?,
            base: local_url(base)?,
            token: read_token(token_file)?,
            graph,
        })
    }
    fn post(&self, path: &str, body: &Value) -> Result<Value> {
        response(
            self.client
                .post(self.base.join(path)?)
                .bearer_auth(&self.token)
                .json(body)
                .send()?,
        )
    }
    pub fn identity(&self) -> Result<Identity> {
        Ok(serde_json::from_value(response(
            self.client
                .get(self.base.join("api/agent/identity")?)
                .bearer_auth(&self.token)
                .send()?,
        )?)?)
    }
    /// Read the configured graph's roster. Public access is not a closed member list.
    pub fn context_graph_collaborators(&self) -> Result<Value> {
        let mut url = self.base.clone();
        url.path_segments_mut()
            .map_err(|_| anyhow::anyhow!("invalid DKG origin"))?
            .extend(["api", "context-graph", &self.graph, "participants"]);
        let roster = response(self.client.get(url).bearer_auth(&self.token).send()?)?;
        let inventory = response(
            self.client
                .get(self.base.join("api/context-graph/list")?)
                .bearer_auth(&self.token)
                .send()?,
        )?;
        let mut result = graph_collaborators(&self.graph, &roster, &inventory)?;
        // Identity is useful presentation context, but not proof of graph membership.
        if let Ok(identity) = self.identity() {
            result["local_identity"] = serde_json::to_value(identity)?;
        }
        Ok(result)
    }
    /// Native DKG invite: graph ID followed by the curator's libp2p peer ID.
    /// Checking the curator-only route prevents emitting a member's peer ID as curator.
    pub fn context_graph_invite(&self) -> Result<String> {
        self.check_graph_access()?;
        let mut url = self.base.clone();
        url.path_segments_mut()
            .map_err(|_| anyhow::anyhow!("invalid DKG origin"))?
            .extend(["api", "context-graph", &self.graph, "join-requests"]);
        let requests = response(self.client.get(url).bearer_auth(&self.token).send()?)?;
        ensure!(
            requests["contextGraphId"] == self.graph && requests["requests"].is_array(),
            "DKG curator response does not match the configured context graph"
        );
        let identity = self.identity()?;
        let peer = &identity.peer_id;
        let base58 = peer
            .bytes()
            .all(|b| b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz".contains(&b));
        ensure!(
            base58
                && ((peer.starts_with("12D3Koo") && (52..=60).contains(&peer.len()))
                    || (peer.starts_with("Qm") && peer.len() == 46)),
            "DKG returned an invalid curator peer ID"
        );
        Ok(format!("{}\n{}", self.graph, peer))
    }
    pub fn share(&self, record: &Record) -> Result<Value> {
        validate_record(record)?;
        ensure!(
            record.context_graph == self.graph && self.identity()?.address == record.author,
            "record must use authenticated author and configured graph"
        );
        let bytes = json_bytes(record)?;
        let id = digest(&bytes);
        // Stable content identity makes reconciliation and retry use the same KA.
        let subject = format!("{NS}{id}");
        let literal = serde_json::to_string(&String::from_utf8(bytes)?)?;
        let mut quads = json!([
            {"subject":subject,"predicate":"http://www.w3.org/1999/02/22-rdf-syntax-ns#type","object":format!("{NS}{}",record.kind),"graph":""},
            {"subject":subject,"predicate":format!("{NS}record"),"object":literal,"graph":""},
            {"subject":subject,"predicate":format!("{NS}artifact"),"object":format!("urn:sha256:{}",record.artifact),"graph":""},
            {"subject":subject,"predicate":format!("{NS}author"),"object":format!("did:dkg:agent:{}",record.author),"graph":""},
            {"subject":subject,"predicate":format!("{NS}contextGraph"),"object":format!("did:dkg:context-graph:{}",record.context_graph),"graph":""}
        ]);
        if let Some(parent) = &record.relates_to {
            quads.as_array_mut().unwrap().push(json!({"subject":subject,"predicate":format!("{NS}relatesTo"),"object":format!("urn:sha256:{parent}"),"graph":""}));
        }
        let result=self.post("api/knowledge-assets",&json!({"contextGraphId":self.graph,"name":format!("nc-{id}"),"quads":quads,"finalize":true,"alsoShareSwm":true,"alsoPublishVm":false}))?;
        ensure!(
            result.get("status").and_then(Value::as_str) == Some("swm-shared"),
            "DKG share incomplete; reconcile stable asset before retry"
        );
        Ok(result)
    }
    pub fn discover(&self, id: &ContentId) -> Result<Option<Record>> {
        self.check_graph_access()?;
        let query = format!(
            "SELECT ?g ?record WHERE {{ GRAPH ?g {{ <{NS}{id}> <{NS}record> ?record }} }} LIMIT 2"
        );
        let result = self.post(
            "api/query",
            &json!({"contextGraphId":self.graph,"graphSuffix":"_shared_memory","sparql":query}),
        )?;
        let rows = result
            .pointer("/result/bindings")
            .and_then(Value::as_array)
            .context("unexpected DKG bindings envelope")?;
        if rows.is_empty() {
            // Query deliberately hides denied graphs as empty. Recheck the
            // explicit authority gate so a revocation is reported as denial.
            self.check_graph_access()?;
            return Ok(None);
        }
        ensure!(rows.len() == 1, "ambiguous record");
        let raw = rows[0]
            .get("record")
            .and_then(Value::as_str)
            .context("missing record literal")?;
        let raw = if raw.starts_with('"') {
            serde_json::from_str::<String>(raw)?
        } else {
            raw.to_owned()
        };
        let record: Record = serde_json::from_str(&raw)?;
        ensure!(
            digest(&json_bytes(&record)?) == *id && record.context_graph == self.graph,
            "DKG record identity mismatch"
        );
        validate_record(&record)?;
        // RFC-64 applies verified author-catalog rows into a graph keyed by the
        // authenticated author and reserved KA number. Names are local aliases
        // and need not exist on the replica; bind claims to this accepted placement.
        let graph = rows[0]
            .get("g")
            .and_then(Value::as_str)
            .context("missing authenticated KA graph")?;
        verify_placement(&self.graph, &record.author, graph)?;
        Ok(Some(record))
    }
    pub fn shared_proposals(&self, offset: usize) -> Result<SharedProposals> {
        ensure!(offset <= 100_000, "discovery offset exceeds limit");
        self.check_graph_access()?;
        let query = format!(
            "SELECT ?g ?subject ?record WHERE {{ GRAPH ?g {{ ?subject <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{NS}PatchProposal> ; <{NS}record> ?record }} }} ORDER BY ?subject ?g LIMIT 21 OFFSET {offset}"
        );
        let result = self.post(
            "api/query",
            &json!({"contextGraphId":self.graph,"graphSuffix":"_shared_memory","sparql":query}),
        )?;
        // Query APIs can represent denied access as an empty result. Do not
        // turn a revoked or unavailable graph into an empty catalogue.
        self.check_graph_access()?;
        proposal_page(&self.graph, offset, &result)
    }
    pub fn check_graph_access(&self) -> Result<()> {
        let mut url = self.base.clone();
        url.path_segments_mut()
            .map_err(|_| anyhow::anyhow!("invalid DKG origin"))?
            .extend(["api", "context-graph", &self.graph, "participants"]);
        response(self.client.get(url).bearer_auth(&self.token).send()?)?;
        Ok(())
    }
}
fn agent_address(raw: &str) -> Result<String> {
    let value = raw.strip_prefix("did:dkg:agent:").unwrap_or(raw);
    ensure!(
        value.len() == 42
            && value.starts_with("0x")
            && value[2..].bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid graph participant identity"
    );
    Ok(value.to_lowercase())
}
fn graph_collaborators(graph: &str, roster: &Value, inventory: &Value) -> Result<Value> {
    ensure!(
        roster["contextGraphId"] == graph,
        "DKG roster belongs to another graph"
    );
    let agents = roster["allowedAgents"]
        .as_array()
        .context("missing DKG participant list")?;
    let graphs = inventory["contextGraphs"]
        .as_array()
        .context("missing DKG graph inventory")?;
    let matches: Vec<_> = graphs.iter().filter(|g| g["id"] == graph).collect();
    ensure!(
        matches.len() == 1,
        "configured graph is absent or ambiguous in DKG inventory"
    );
    let metadata = matches[0];
    let curator = metadata
        .get("curator")
        .and_then(Value::as_str)
        .map(agent_address)
        .transpose()?;
    let mut participants = std::collections::BTreeSet::new();
    for agent in agents {
        participants.insert(agent_address(
            agent.as_str().context("invalid DKG participant")?,
        )?);
    }
    if let Some(address) = &curator {
        participants.insert(address.clone());
    }
    Ok(json!({
        "context_graph":graph,
        "name":metadata.get("name").and_then(Value::as_str),
        "access_policy":metadata.get("accessPolicy").and_then(Value::as_str).unwrap_or("unknown"),
        "curator":curator,
        "participants":participants,
    }))
}
fn proposal_page(graph: &str, offset: usize, result: &Value) -> Result<SharedProposals> {
    let rows = result
        .pointer("/result/bindings")
        .and_then(Value::as_array)
        .context("unexpected DKG bindings envelope")?;
    ensure!(rows.len() <= 21, "DKG discovery page exceeds limit");
    let mut records = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for row in rows.iter().take(20) {
        let subject = row["subject"]
            .as_str()
            .context("missing proposal subject")?;
        let id = ContentId::try_from(
            subject
                .strip_prefix(NS)
                .context("invalid proposal subject")?
                .to_owned(),
        )?;
        let literal = row["record"].as_str().context("missing proposal record")?;
        let raw = if literal.starts_with('"') {
            serde_json::from_str::<String>(literal)?
        } else {
            literal.to_owned()
        };
        let record: Record = serde_json::from_str(&raw)?;
        validate_record(&record)?;
        ensure!(
            record.kind == "PatchProposal"
                && record.context_graph == graph
                && digest(&json_bytes(&record)?) == id,
            "DKG proposal identity mismatch"
        );
        verify_placement(
            graph,
            &record.author,
            row["g"]
                .as_str()
                .context("missing authenticated KA graph")?,
        )?;
        ensure!(
            seen.insert(id.clone()),
            "ambiguous proposal in DKG discovery"
        );
        records.push(SharedProposal { id, record });
    }
    Ok(SharedProposals {
        records,
        offset,
        next_offset: (rows.len() > 20).then_some(offset + 20),
    })
}
pub fn validate_record(r: &Record) -> Result<()> {
    ensure!(
        r.schema == "nc/record/v1"
            && [
                "ModelVersion",
                "Hypothesis",
                "PatchProposal",
                "Evaluation",
                "Review",
                "DerivedVersion"
            ]
            .contains(&r.kind.as_str()),
        "unsupported semantic record"
    );
    ensure!(
        r.author.len() == 42
            && r.author.starts_with("0x")
            && r.author[2..].bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid DKG author"
    );
    ensure!(
        !r.artifacts.is_empty() && r.artifacts.len() <= 4096 && r.artifacts.contains(&r.artifact),
        "invalid artifact bundle"
    );
    ensure!(
        r.artifact_origin == "dkg",
        "legacy artifact transport is unsupported; republish through DKG"
    );
    Ok(())
}
fn verify_placement(context_graph: &str, author: &str, graph: &str) -> Result<()> {
    let graph = graph
        .strip_prefix('<')
        .and_then(|g| g.strip_suffix('>'))
        .unwrap_or(graph);
    let prefix = format!(
        "did:dkg:context-graph:{context_graph}/_shared_memory/{}/",
        author.to_lowercase()
    );
    let number = graph
        .strip_prefix(&prefix)
        .context("DKG authenticated author/graph differs from record claim")?;
    ensure!(
        !number.is_empty() && number.len() <= 29 && number.bytes().all(|b| b.is_ascii_digit()),
        "invalid KA coordinate"
    );
    let n: u128 = number.parse()?;
    ensure!(n < (1u128 << 96), "KA number out of range");
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn graph_roster_keeps_public_access_distinct_and_includes_the_curator_once() {
        let a = "0x1111111111111111111111111111111111111111";
        let b = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd";
        let roster = json!({"contextGraphId":"demo","allowedAgents":[b,b.to_uppercase().replacen("0X","0x",1)]});
        let inventory = json!({"contextGraphs":[{"id":"demo","name":"Team","accessPolicy":"public","curator":format!("did:dkg:agent:{a}")}]});
        let result = graph_collaborators("demo", &roster, &inventory).unwrap();
        assert_eq!(result["participants"], json!([a, b]));
        assert_eq!(result["access_policy"], "public");
        assert!(graph_collaborators("other", &roster, &inventory).is_err());
        assert!(
            graph_collaborators("demo", &json!({"contextGraphId":"demo"}), &inventory).is_err()
        );
        assert!(graph_collaborators("demo", &roster, &json!({"contextGraphs":[]})).is_err());
        assert!(
            graph_collaborators(
                "demo",
                &json!({"contextGraphId":"demo","allowedAgents":["not-an-identity"]}),
                &inventory
            )
            .is_err()
        );
        let open = graph_collaborators(
            "demo",
            &json!({"contextGraphId":"demo","allowedAgents":[]}),
            &inventory,
        )
        .unwrap();
        assert_eq!(open["participants"], json!([a]));
        assert_eq!(open["access_policy"], "public");
    }
    fn proposal_row(n: usize) -> Value {
        let record = Record {
            schema: "nc/record/v1".into(),
            kind: "PatchProposal".into(),
            author: "0x1111111111111111111111111111111111111111".into(),
            context_graph: "demo".into(),
            artifact: digest(n.to_string().as_bytes()),
            artifacts: vec![digest(n.to_string().as_bytes())],
            artifact_origin: "dkg".into(),
            relates_to: None,
            fixture: true,
        };
        let id = digest(&json_bytes(&record).unwrap());
        json!({"subject":format!("{NS}{id}"),"record":serde_json::to_string(&record).unwrap(),"g":format!("did:dkg:context-graph:demo/_shared_memory/{}/{}",record.author,n)})
    }
    #[test]
    fn discovery_pages_are_bounded_and_verify_each_proposal() {
        let rows: Vec<_> = (0..21).map(proposal_row).collect();
        let page = proposal_page("demo", 20, &json!({"result":{"bindings":rows}})).unwrap();
        assert_eq!(page.records.len(), 20);
        assert_eq!(page.next_offset, Some(40));
        assert!(
            proposal_page("demo", 0, &json!({"result":{"bindings":[]}}))
                .unwrap()
                .records
                .is_empty()
        );
        for key in ["subject", "g", "record"] {
            let mut row = proposal_row(0);
            row[key] = json!("tampered");
            assert!(proposal_page("demo", 0, &json!({"result":{"bindings":[row]}})).is_err());
        }
        let mut row = proposal_row(0);
        row["record"] = json!(serde_json::to_string(row["record"].as_str().unwrap()).unwrap());
        assert_eq!(
            proposal_page("demo", 0, &json!({"result":{"bindings":[row]}}))
                .unwrap()
                .records
                .len(),
            1
        );
        assert!(
            proposal_page(
                "other",
                0,
                &json!({"result":{"bindings":[proposal_row(0)]}})
            )
            .is_err()
        );
        assert!(
            proposal_page(
                "demo",
                0,
                &json!({"result":{"bindings":[proposal_row(0),proposal_row(0)]}})
            )
            .is_err()
        );
        assert!(
            proposal_page(
                "demo",
                0,
                &json!({"result":{"bindings":(0..22).map(proposal_row).collect::<Vec<_>>()}})
            )
            .is_err()
        );
    }
    #[test]
    fn remote_claim_must_match_authenticated_catalog_placement() {
        let author = "0x1111111111111111111111111111111111111111";
        assert!(
            verify_placement(
                "demo",
                author,
                &format!("did:dkg:context-graph:demo/_shared_memory/{author}/42")
            )
            .is_ok()
        );
        for graph in [
            format!("did:dkg:context-graph:other/_shared_memory/{author}/42"),
            "did:dkg:context-graph:demo/_shared_memory/0x2222222222222222222222222222222222222222/42".to_owned(),
            format!("did:dkg:context-graph:demo/_shared_memory/{author}/42/extra"),
            format!(
                "did:dkg:context-graph:demo/_shared_memory/{author}/79228162514264337593543950336"
            ),
        ] {
            assert!(verify_placement("demo", author, &graph).is_err());
        }
    }
}
