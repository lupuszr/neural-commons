mod fixtures;
mod journal;
mod server;
use anyhow::{Context, Result, ensure};
use clap::{Parser, Subcommand};
use nc_core::*;
use nc_dkg_client::{DkgClient, Record};
use nc_evaluator::*;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::{Duration, Instant},
};

#[derive(Parser)]
#[command(version, about = "Reproducible tensor changes and DKG evidence")]
struct Cli {
    #[arg(long, default_value = ".runtime/participant")]
    home: PathBuf,
    #[command(subcommand)]
    command: Action,
}
#[derive(Subcommand)]
enum Action {
    Init {
        #[arg(long)]
        dkg_url: String,
        #[arg(long)]
        dkg_token_file: PathBuf,
        #[arg(long)]
        context_graph: String,
    },
    Export {
        checkpoint: String,
        directory: PathBuf,
    },
    Inspect {
        file: PathBuf,
    },
    Register {
        file: PathBuf,
        #[arg(long)]
        inference_artifacts: Option<PathBuf>,
    },
    Put {
        file: PathBuf,
    },
    Patch {
        #[command(subcommand)]
        command: PatchAction,
    },
    Fixture,
    Evaluators,
    PublishCheckpoint {
        checkpoint: String,
        #[arg(long)]
        fixture: bool,
    },
    Select {
        checkpoint: String,
    },
    Evaluate {
        spec: String,
        #[arg(long)]
        retry: bool,
    },
    #[command(hide = true)]
    EvaluationWorker {
        spec: String,
    },
    Share {
        record: String,
    },
    Propose {
        spec: String,
        #[arg(long)]
        fixture: bool,
    },
    Reproduce {
        record: String,
        #[arg(long)]
        retry: bool,
    },
    Fetch {
        record: String,
    },
    Serve {
        #[arg(long, default_value_t = 19500)]
        port: u16,
    },
    State,
    Demo,
    /// Run the weight-space controller adapter (Codex login or OpenAI API).
    Agent {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
}
#[derive(Subcommand)]
enum PatchAction {
    Diff {
        parent: String,
        candidate: String,
        #[arg(long)]
        hypothesis: Option<String>,
    },
    Create {
        parent: String,
        operations: PathBuf,
        #[arg(long)]
        hypothesis: Option<String>,
    },
    Apply {
        parent: String,
        patch: String,
    },
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    dkg_url: String,
    dkg_token_file: PathBuf,
    context_graph: String,
    artifact_origin: String,
    artifact_token_file: PathBuf,
    trusted_artifact_origin: Option<String>,
    trusted_artifact_token_file: Option<PathBuf>,
}
fn config(home: &Path) -> Result<Config> {
    Ok(serde_json::from_slice(&read_bounded(
        &home.join("config.json"),
        16 * 1024,
    )?)?)
}
fn client(cfg: &Config) -> Result<DkgClient> {
    DkgClient::new(&cfg.dkg_url, &cfg.dkg_token_file, cfg.context_graph.clone())
}
fn executable() -> Result<ContentId> {
    hash_file(&std::env::current_exe()?)
}
fn id(s: String) -> Result<ContentId> {
    s.try_into()
}
fn evaluate_job(
    home: &Path,
    s: &ArtifactStore,
    j: &journal::Journal,
    spec: &ContentId,
    retry: bool,
) -> Result<ContentId> {
    if retry {
        j.retry(spec)?;
    }
    if let Some(report) = j.job(spec)? {
        s.get(&report)?;
        return Ok(report);
    }
    let definition: EvaluationSpec = s.get_json(spec)?;
    let ceiling = if definition.evaluator == EVALUATOR {
        30_000
    } else {
        configured_runners(home)?
            .get(&definition.evaluator)
            .context("evaluator not configured")?
            .max_timeout_ms
    };
    let mut command = Command::new(std::env::current_exe()?);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command
        .args(["--home"])
        .arg(home)
        .args(["evaluation-worker", &spec.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let deadline = Instant::now()
        + Duration::from_millis(definition.timeout_ms.min(ceiling).saturating_add(2000));
    let exit = loop {
        if let Some(status) = child.try_wait()? {
            break Some(status);
        }
        if Instant::now() >= deadline {
            #[cfg(unix)]
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGKILL);
            }
            #[cfg(not(unix))]
            child.kill()?;
            child.wait()?;
            break None;
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    let result_file = home.join(format!("worker-{spec}.json"));
    let report = if exit.is_some_and(|e| e.success()) {
        let report_id: ContentId = serde_json::from_slice(&read_bounded(&result_file, 256)?)?;
        let report: EvaluationReport = s.get_json(&report_id)?;
        ensure!(report.spec == *spec, "worker result spec mismatch");
        report
    } else {
        EvaluationReport {
            schema: "nc/evaluation/v1".into(),
            spec: spec.clone(),
            evaluator: EVALUATOR.into(),
            observed_executable: executable()?,
            environment: environment(),
            process_id: child.id(),
            status: if exit.is_none() {
                Status::Interrupted
            } else {
                Status::Unavailable
            },
            base_mse: None,
            candidate_mse: None,
            outputs: None,
            error: Some("worker exited or exceeded wall-clock deadline".into()),
            scores: None,
        }
    };
    let report_id = s.put_json(&report)?;
    let state = match report.status {
        Status::Interrupted => "interrupted",
        Status::Unavailable => "unavailable",
        _ => "complete",
    };
    j.complete(spec, &report_id, state)?;
    Ok(report_id)
}
fn publish(
    s: &ArtifactStore,
    j: &journal::Journal,
    dkg: &DkgClient,
    record_id: &ContentId,
) -> Result<Value> {
    let record: Record = s.get_json(record_id)?;
    ensure!(
        digest(&json_bytes(&record)?) == *record_id,
        "noncanonical record"
    );
    for artifact in &record.artifacts {
        s.verify(artifact)?;
    }
    let state = j.publication(record_id, &json!(record))?;
    if state == "shared" {
        return Ok(json!({"record":record_id,"state":"shared","reused":true}));
    }
    if state == "unknown" || state == "sending" {
        if dkg.discover(record_id)?.is_some() {
            j.publication_state(record_id, "shared", None)?;
            j.record(record_id, &json!(record), "local-shared")?;
            return Ok(json!({"record":record_id,"state":"shared","reconciled":true}));
        }
        anyhow::bail!(
            "publication outcome remains unknown: DKG readback is not yet available; retry reconciliation without resending"
        );
    }
    // Preparation stays retryable; only the actual record write is uncertain.
    dkg.upload_bundle(s, &record)?;
    j.publication_state(record_id, "sending", None)?;
    match dkg.share(&record) {
        Ok(receipt) => {
            j.publication_state(record_id, "shared", Some(&receipt))?;
            j.record(record_id, &json!(record), "local-shared")?;
            Ok(json!({"record":record_id,"state":"shared","receipt":receipt}))
        }
        Err(e) => {
            j.publication_state(record_id, "unknown", None)?;
            Err(e.context(
                "publication outcome unknown; retry share reconciles the same content identity",
            ))
        }
    }
}
fn receive(
    s: &ArtifactStore,
    j: &journal::Journal,
    _cfg: &Config,
    dkg: &DkgClient,
    record_id: &ContentId,
) -> Result<Record> {
    let record = dkg
        .discover(record_id)?
        .context("record unavailable in DKG shared memory")?;
    dkg.download_bundle(s, &record)?;
    ensure!(
        s.put_json(&record)? == *record_id,
        "record integrity mismatch"
    );
    j.record(record_id, &json!(record), "remote-dkg-readback")?;
    Ok(record)
}
fn run() -> Result<()> {
    let cli = Cli::parse();
    if let Action::Agent { args } = &cli.command {
        let status = Command::new("python3")
            .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts/weight_agent.py"))
            .args(args)
            .status()?;
        ensure!(
            status.success(),
            "weight agent failed; inspect its transcript"
        );
        return Ok(());
    }
    if matches!(cli.command, Action::Demo) {
        let status = Command::new("python3")
            .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts/demo.py"))
            .status()?;
        ensure!(
            status.success(),
            "demo failed; inspect its validation record"
        );
        return Ok(());
    }
    if let Action::Inspect { file } = &cli.command {
        println!("{}", serde_json::to_string_pretty(&inspect_file(file)?)?);
        return Ok(());
    }
    let store = ArtifactStore::open(cli.home.join("artifacts"))?;
    if let Action::EvaluationWorker { spec } = cli.command {
        // Retain an execution lock even if the supervisor dies. A retried job
        // cannot overlap an orphaned evaluator from an interrupted parent.
        let execution_lock = std::fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(cli.home.join("execution.lock"))?;
        fs2::FileExt::try_lock_exclusive(&execution_lock)
            .context("another evaluator process is still executing")?;
        #[cfg(unix)]
        {
            use std::os::fd::AsRawFd;
            // Retain the execution lease in a configured evaluator if its worker is killed.
            let fd = execution_lock.as_raw_fd();
            unsafe {
                let flags = libc::fcntl(fd, libc::F_GETFD);
                ensure!(
                    flags >= 0 && libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) >= 0,
                    "execution lease inheritance failed"
                );
            }
        }
        let spec = id(spec)?;
        let definition: EvaluationSpec = store.get_json(&spec)?;
        let report = if definition.evaluator == EVALUATOR {
            evaluate(&store, &spec, &executable()?)
        } else {
            let runners = configured_runners(&cli.home)?;
            evaluate_external(
                &store,
                &spec,
                runners
                    .get(&definition.evaluator)
                    .context("evaluator not configured")?,
            )
        };
        let report_id = store.put_json(&report)?;
        let path = cli.home.join(format!("worker-{spec}.json"));
        let mut tmp = tempfile::NamedTempFile::new_in(&cli.home)?;
        use std::io::Write;
        tmp.write_all(&json_bytes(&report_id)?)?;
        tmp.as_file().sync_all()?;
        tmp.persist(path)?;
        return Ok(());
    }
    if let Action::Serve { port } = cli.command {
        let cfg = config(&cli.home)?;
        return server::serve(cli.home, store, &cfg.artifact_token_file, port);
    }
    if matches!(cli.command, Action::State) {
        println!(
            "{}",
            serde_json::to_string_pretty(&journal::snapshot(&cli.home)?)?
        );
        return Ok(());
    }
    let j = journal::Journal::open(&cli.home)?;
    let output = match cli.command {
        Action::PublishCheckpoint {
            checkpoint,
            fixture,
        } => {
            let checkpoint = id(checkpoint)?;
            let m = verify_checkpoint(&store, &checkpoint)?;
            let cfg = config(&cli.home)?;
            let dkg = client(&cfg)?;
            let mut artifacts = vec![checkpoint.clone(), m.artifact];
            artifacts.extend(m.shards.values().cloned());
            artifacts.extend(m.inference_artifacts.values().cloned());
            artifacts.sort_by_key(|id| id.to_string());
            artifacts.dedup();
            let record = Record {
                schema: "nc/record/v1".into(),
                kind: "ModelVersion".into(),
                author: dkg.identity()?.address,
                context_graph: cfg.context_graph,
                artifact: checkpoint,
                artifacts,
                artifact_origin: "dkg".into(),
                relates_to: None,
                fixture,
            };
            publish(&store, &j, &dkg, &store.put_json(&record)?)?
        }
        Action::Select { checkpoint } => {
            let checkpoint = id(checkpoint)?;
            verify_checkpoint(&store, &checkpoint)?;
            let mut file = tempfile::NamedTempFile::new_in(&cli.home)?;
            use std::io::Write;
            file.write_all(&json_bytes(
                &json!({"checkpoint":checkpoint,"selection":"operator"}),
            )?)?;
            file.as_file().sync_all()?;
            file.persist(cli.home.join("selected.json"))?;
            json!({"selected":checkpoint})
        }
        Action::Evaluators => {
            let runners = configured_runners(&cli.home)?;
            let mut identities = serde_json::Map::new();
            identities.insert(
                EVALUATOR.into(),
                json!({"build":executable()?,"backend":environment()}),
            );
            for (name, runner) in runners {
                identities.insert(
                    name,
                    json!({"build":runner_identity(&runner)?,"backend":runner.backend}),
                );
            }
            json!(identities)
        }
        Action::Init {
            dkg_url,
            dkg_token_file,
            context_graph,
        } => {
            ensure!(
                !cli.home.join("config.json").exists(),
                "participant already initialized"
            );
            let cfg = Config {
                dkg_url,
                dkg_token_file: std::fs::canonicalize(dkg_token_file)?,
                context_graph,
                artifact_origin: "dkg".into(),
                artifact_token_file: cli.home.join("ui.token"),
                trusted_artifact_origin: None,
                trusted_artifact_token_file: None,
            };
            let dkg = client(&cfg)?;
            let identity = dkg.identity()?;
            dkg.check_graph_access()?;
            std::fs::write(
                &cfg.artifact_token_file,
                format!(
                    "{}{}",
                    uuid::Uuid::new_v4().simple(),
                    uuid::Uuid::new_v4().simple()
                ),
            )?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&cli.home, std::fs::Permissions::from_mode(0o700))?;
                std::fs::set_permissions(
                    &cfg.artifact_token_file,
                    std::fs::Permissions::from_mode(0o600),
                )?;
            }
            std::fs::write(
                cli.home.join("config.json"),
                serde_json::to_vec_pretty(&cfg)?,
            )?;
            json!({"identity":identity,"context_graph":cfg.context_graph,"transport":"dkg"})
        }
        Action::Export {
            checkpoint,
            directory,
        } => {
            export_checkpoint(&store, &id(checkpoint)?, &directory)?;
            json!({"directory":directory})
        }
        Action::Register {
            file,
            inference_artifacts,
        } => {
            let mut manifest = register_file(&store, &file)?;
            if let Some(mapping) = inference_artifacts {
                let paths: std::collections::BTreeMap<String, PathBuf> =
                    serde_json::from_slice(&read_bounded(&mapping, 64 * 1024)?)?;
                ensure!(paths.len() <= 32, "too many inference artifacts");
                for (name, path) in paths {
                    manifest
                        .inference_artifacts
                        .insert(name, store.put_file(&path)?);
                }
            }
            let cp = store.put_json(&manifest)?;
            j.checkpoint(&cp)?;
            json!({"checkpoint":cp})
        }
        Action::Put { file } => {
            json!({"artifact":store.put_file(&file)?})
        }
        Action::Patch { command } => match command {
            PatchAction::Diff {
                parent,
                candidate,
                hypothesis,
            } => {
                let author = client(&config(&cli.home)?)?.identity()?.address;
                json!({"patch":diff_patch(&store,&id(parent)?,&id(candidate)?,author,hypothesis)?})
            }
            PatchAction::Create {
                parent,
                operations,
                hypothesis,
            } => {
                let author = client(&config(&cli.home)?)?.identity()?.address;
                let ops = serde_json::from_slice(&read_bounded(&operations, 1024 * 1024)?)?;
                json!({"patch":create_patch(&store,&id(parent)?,author,ops,hypothesis)?})
            }
            PatchAction::Apply { parent, patch } => {
                let candidate = apply_patch(&store, &id(parent)?, &id(patch)?)?;
                j.checkpoint(&candidate)?;
                json!({"checkpoint":candidate})
            }
        },
        Action::Fixture => {
            let author = client(&config(&cli.home)?)?.identity()?.address;
            let result = fixtures::generate(&store, &author, &executable()?)?;
            for field in ["base", "unrelated_checkpoint"] {
                j.checkpoint(&serde_json::from_value(result[field].clone())?)?;
            }
            for label in ["repair", "regression"] {
                j.checkpoint(&serde_json::from_value(
                    result["candidates"][label]["candidate"].clone(),
                )?)?;
            }
            result
        }
        Action::Evaluate { spec, retry } => {
            let spec = id(spec)?;
            let r = evaluate_job(&cli.home, &store, &j, &spec, retry)?;
            json!({"report":r,"evaluation":store.get_json::<EvaluationReport>(&r)?})
        }
        Action::Share { record } => {
            publish(&store, &j, &client(&config(&cli.home)?)?, &id(record)?)?
        }
        Action::Propose { spec, fixture } => {
            let cfg = config(&cli.home)?;
            let dkg = client(&cfg)?;
            let spec = id(spec)?;
            let definition: EvaluationSpec = store.get_json(&spec)?;
            let patch: Patch = store.get_json(&definition.patch)?;
            let identity = dkg.identity()?;
            ensure!(
                patch.author == identity.address,
                "patch author differs from authenticated participant"
            );
            let record = Record {
                schema: "nc/record/v1".into(),
                kind: "PatchProposal".into(),
                author: identity.address,
                context_graph: cfg.context_graph,
                artifact: spec.clone(),
                artifacts: fixtures::spec_bundle(&store, &spec)?,
                artifact_origin: "dkg".into(),
                relates_to: Some(definition.base.clone()),
                fixture,
            };
            let derived=store.put_json(&json!({"schema":"nc/derived-version/v1","parent":definition.base,"checkpoint":definition.candidate,"ordered_patches":[definition.patch],"status":"candidate"}))?;
            let mut related = Vec::new();
            for (kind, artifact) in [
                ("ModelVersion", definition.base.clone()),
                ("DerivedVersion", derived),
            ] {
                let mut entity = record.clone();
                entity.kind = kind.into();
                entity.artifact = artifact.clone();
                if !entity.artifacts.contains(&artifact) {
                    entity.artifacts.push(artifact);
                }
                related.push(publish(&store, &j, &dkg, &store.put_json(&entity)?)?);
            }
            if let Some(claim) = patch.hypothesis {
                let hypothesis=store.put_json(&json!({"schema":"nc/hypothesis/v1","author":record.author,"claim":claim,"patch":definition.patch,"regions":patch.operations}))?;
                let mut entity = record.clone();
                entity.kind = "Hypothesis".into();
                entity.artifact = hypothesis.clone();
                entity.artifacts.push(hypothesis);
                related.push(publish(&store, &j, &dkg, &store.put_json(&entity)?)?);
            }
            let mut published = publish(&store, &j, &dkg, &store.put_json(&record)?)?;
            published["related_records"] = json!(related);
            published
        }
        Action::Fetch { record } => {
            let cfg = config(&cli.home)?;
            let r = receive(&store, &j, &cfg, &client(&cfg)?, &id(record)?)?;
            json!(r)
        }
        Action::Reproduce { record, retry } => {
            let cfg = config(&cli.home)?;
            let dkg = client(&cfg)?;
            let record_id = id(record)?;
            let record = receive(&store, &j, &cfg, &dkg, &record_id)?;
            ensure!(
                record.kind == "PatchProposal",
                "reproduce requires proposal"
            );
            let definition: EvaluationSpec = store.get_json(&record.artifact)?;
            j.checkpoint(&definition.base)?;
            j.checkpoint(&definition.candidate)?;
            let patch: Patch = store.get_json(&definition.patch)?;
            ensure!(
                patch.author == record.author,
                "patch and DKG authors disagree"
            );
            let report_id = evaluate_job(&cli.home, &store, &j, &record.artifact, retry)?;
            let report: EvaluationReport = store.get_json(&report_id)?;
            let mut artifacts = record.artifacts.clone();
            artifacts.push(report_id.clone());
            if let Some(outputs) = &report.outputs {
                artifacts.push(outputs.clone());
            }
            let evidence = Record {
                schema: "nc/record/v1".into(),
                kind: "Evaluation".into(),
                author: dkg.identity()?.address,
                context_graph: cfg.context_graph,
                artifact: report_id.clone(),
                artifacts,
                artifact_origin: "dkg".into(),
                relates_to: Some(record_id),
                fixture: record.fixture,
            };
            let published = publish(&store, &j, &dkg, &store.put_json(&evidence)?)?;
            let review_id=store.put_json(&json!({"schema":"nc/review/v1","reviewer":evidence.author,"evaluation":report_id,"spec":record.artifact,"policy":definition.policy,"verdict":report.status}))?;
            let mut review = evidence.clone();
            review.kind = "Review".into();
            review.artifact = review_id.clone();
            review.artifacts.push(review_id);
            review.relates_to = Some(store.put_json(&evidence)?);
            let review_publication = publish(&store, &j, &dkg, &store.put_json(&review)?)?;
            json!({"publication":published,"review":review_publication,"report":report_id,"evaluation":report})
        }
        _ => unreachable!(),
    };
    println!("{}", serde_json::to_string_pretty(&output)?);
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("{e:#}");
        std::process::exit(1)
    }
}
