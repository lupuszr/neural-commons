use anyhow::{Context, Result};
use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use nc_core::*;
use std::{
    path::{Path as FsPath, PathBuf},
    sync::Arc,
};
struct App {
    home: PathBuf,
    store: ArtifactStore,
    token: Option<String>,
    port: u16,
    permits: Arc<tokio::sync::Semaphore>,
    commands: Arc<tokio::sync::Semaphore>,
    controller_python: PathBuf,
}
struct GuardedBytes {
    bytes: Vec<u8>,
    _permit: tokio::sync::OwnedSemaphorePermit,
}
impl AsRef<[u8]> for GuardedBytes {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}
// Token-free mode is for the loopback UI only. Reject foreign web origins and
// non-loopback Host values, including DNS-rebinding requests.
fn local_request(headers: &HeaderMap, port: u16) -> bool {
    let host = headers
        .get(header::HOST)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    if host != format!("127.0.0.1:{port}") && host != format!("localhost:{port}") {
        return false;
    }
    if let Some(origin) = headers.get(header::ORIGIN)
        && origin.to_str().ok() != Some(format!("http://{host}").as_str())
    {
        return false;
    }
    !headers
        .get("sec-fetch-site")
        .is_some_and(|v| v != "same-origin" && v != "none")
}
fn authorized(headers: &HeaderMap, token: Option<&str>, port: u16) -> bool {
    let Some(token) = token else {
        return local_request(headers, port);
    };
    let expected = format!("Bearer {token}");
    let value = headers
        .get(header::AUTHORIZATION)
        .map(|h| h.as_bytes())
        .unwrap_or(&[]);
    value.len() == expected.len()
        && value
            .iter()
            .zip(expected.as_bytes())
            .fold(0u8, |a, (x, y)| a | (x ^ y))
            == 0
}
async fn artifact(
    State(app): State<Arc<App>>,
    Path(raw): Path<String>,
    headers: HeaderMap,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    let Ok(id) = ContentId::try_from(raw) else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    match app.store.get(&id) {
        Ok(bytes) => (
            [
                (header::CONTENT_TYPE, "application/octet-stream"),
                (header::CACHE_CONTROL, "no-store"),
                (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            ],
            bytes::Bytes::from_owner(GuardedBytes {
                bytes,
                _permit: permit,
            }),
        )
            .into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}
async fn state(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(_permit) = app.permits.try_acquire() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match crate::journal::snapshot(&app.home) {
        Ok(v) => Json(v).into_response(),
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "Journal unavailable").into_response(),
    }
}

async fn research_list(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        crate::research::list(&app.home)
    })
    .await
    {
        Ok(result) => run_response(result),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}

#[derive(serde::Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum UserAction {
    ImportModel {
        directory: String,
    },
    Register {
        file: String,
        mapping: Option<String>,
    },
    Put {
        file: String,
    },
    Diff {
        parent: String,
        candidate: String,
    },
    Apply {
        parent: String,
        patch: String,
    },
    Evaluate {
        spec: String,
    },
    Propose {
        spec: String,
    },
    Reproduce {
        record: String,
        #[serde(default)]
        retry: bool,
    },
    Fetch {
        record: String,
    },
    Select {
        checkpoint: String,
    },
    Export {
        checkpoint: String,
        directory: String,
    },
}
async fn action(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Json(request): Json<UserAction>,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.commands.clone().try_acquire_owned() else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "Another operation is running",
        )
            .into_response();
    };
    let args = match request {
        UserAction::ImportModel { directory } => vec!["import-model".into(), directory],
        UserAction::Register { file, mapping } => {
            let mut a = vec!["register".into(), file];
            if let Some(m) = mapping.filter(|m| !m.is_empty()) {
                a.extend(["--inference-artifacts".into(), m]);
            }
            a
        }
        UserAction::Put { file } => vec!["put".into(), file],
        UserAction::Diff { parent, candidate } => {
            vec!["patch".into(), "diff".into(), parent, candidate]
        }
        UserAction::Apply { parent, patch } => vec!["patch".into(), "apply".into(), parent, patch],
        UserAction::Evaluate { spec } => vec!["evaluate".into(), spec],
        UserAction::Propose { spec } => vec!["propose".into(), spec],
        UserAction::Reproduce { record, retry } => {
            let mut args = vec!["reproduce".into(), record];
            if retry {
                args.push("--retry".into());
            }
            args
        }
        UserAction::Fetch { record } => vec!["fetch".into(), record],
        UserAction::Select { checkpoint } => vec!["select".into(), checkpoint],
        UserAction::Export {
            checkpoint,
            directory,
        } => vec!["export".into(), checkpoint, directory],
    };
    if args.iter().any(|a| a.len() > 8192 || a.contains('\0')) {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let home = app.home.clone();
    let result = tokio::task::spawn_blocking(move || -> anyhow::Result<serde_json::Value> {
        let _permit = permit;
        let controller_lease = crate::continuations::lease(&home)?;
        let result = std::process::Command::new(std::env::current_exe()?)
            .arg("--home")
            .arg(home)
            .args(args)
            .stdin(std::process::Stdio::from(controller_lease))
            .output()?;
        anyhow::ensure!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        Ok(serde_json::from_slice(&result.stdout)?)
    })
    .await;
    match result {
        Ok(Ok(value)) => Json(value).into_response(),
        Ok(Err(error)) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error.to_string()})),
        )
            .into_response(),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
fn run_response(result: Result<serde_json::Value>) -> Response {
    match result {
        Ok(value) => Json(value).into_response(),
        Err(error) => {
            let message = error.to_string();
            let code = if message.contains("active")
                || message.contains("already bound")
                || message.contains("being processed")
            {
                StatusCode::CONFLICT
            } else {
                StatusCode::BAD_REQUEST
            };
            (code, Json(serde_json::json!({"error":message}))).into_response()
        }
    }
}
async fn continuation_list(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        crate::continuations::list(&app.home)
    })
    .await
    {
        Ok(result) => run_response(result),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
async fn continuation_start(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Json(request): Json<crate::continuations::Request>,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.commands.clone().try_acquire_owned() else {
        return StatusCode::CONFLICT.into_response();
    };
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        crate::continuations::start(&app.home, &app.controller_python, request)
    })
    .await
    {
        Ok(result) => run_response(result),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
async fn experiment_start(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Json(request): Json<crate::continuations::Request>,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    if request.proposal.is_some() || request.report.is_some() || request.name.is_none() {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error":"A new experiment needs a name and starting checkpoint, without parent proposal/report"}))).into_response();
    }
    continuation_start(State(app), headers, Json(request)).await
}
async fn continuation_control(
    State(app): State<Arc<App>>,
    Path((id, operation)): Path<(String, String)>,
    headers: HeaderMap,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.commands.clone().try_acquire_owned() else {
        return StatusCode::CONFLICT.into_response();
    };
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        crate::continuations::control(&app.home, &app.controller_python, &id, &operation)
    })
    .await
    {
        Ok(result) => run_response(result),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
#[derive(serde::Deserialize)]
struct FolderQuery {
    path: Option<String>,
    kind: String,
    #[serde(default)]
    hidden: bool,
}
async fn context_graph_share(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || -> anyhow::Result<serde_json::Value> {
        let _permit = permit;
        let cfg = crate::config(&app.home)?;
        let dkg = crate::client(&cfg)?;
        let mut value = serde_json::json!({"context_graph":cfg.context_graph,"dkg_url":cfg.dkg_url});
        match dkg.context_graph_invite() {
            Ok(code) => value["invite_code"] = code.into(),
            Err(_) => value["error"] = "Invite unavailable. Start the configured DKG node and check that it can access and manage this context graph. Only the graph curator can generate this invite; use DKG to check permissions.".into(),
        }
        Ok(value)
    }).await {
        Ok(Ok(value)) => Json(value).into_response(),
        _ => (StatusCode::SERVICE_UNAVAILABLE, Json(serde_json::json!({"error":"Could not read the local DKG configuration."}))).into_response(),
    }
}
async fn context_graph_collaborators(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || -> anyhow::Result<serde_json::Value> {
        let _permit = permit;
        let cfg = crate::config(&app.home)?;
        let mut result = crate::client(&cfg)?.context_graph_collaborators()?;
        result["dkg_url"] = cfg.dkg_url.into();
        Ok(result)
    }).await {
        Ok(Ok(value)) => Json(value).into_response(),
        _ => (StatusCode::SERVICE_UNAVAILABLE, Json(serde_json::json!({"error":"Graph membership is unavailable. Check the configured DKG node and graph access. Recorded contributions can still be inspected locally."}))).into_response(),
    }
}
#[derive(serde::Deserialize)]
struct SharedQuery {
    #[serde(default)]
    offset: usize,
}
async fn shared_experiments(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Query(q): Query<SharedQuery>,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    if q.offset > 100_000 {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || -> anyhow::Result<serde_json::Value> {
        let _permit = permit;
        let cfg = crate::config(&app.home)?;
        let page = crate::client(&cfg)?.shared_proposals(q.offset)?;
        let records: Vec<_> = page.records.into_iter().map(|item| {
            let downloaded = app.store.get_json::<nc_dkg_client::Record>(&item.id).is_ok();
            serde_json::json!({"id":item.id,"record":item.record,"downloaded":downloaded})
        }).collect();
        Ok(serde_json::json!({"context_graph":cfg.context_graph,"records":records,"offset":page.offset,"next_offset":page.next_offset}))
    }).await {
        Ok(Ok(value)) => Json(value).into_response(),
        _ => (StatusCode::SERVICE_UNAVAILABLE, Json(serde_json::json!({"error":"Shared experiments are unavailable. Check the DKG node, graph access and synchronization; no catalogue could be verified."}))).into_response(),
    }
}
async fn folder_choices(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Query(q): Query<FolderQuery>,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        crate::workspace_choices::folders(q.path.as_deref(), &q.kind, q.hidden)
    })
    .await
    {
        Ok(result) => run_response(result),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
#[derive(serde::Deserialize)]
struct ModelsQuery {
    backend: String,
}
async fn controller_models(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Query(q): Query<ModelsQuery>,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    if !["codex", "openai"].contains(&q.backend.as_str()) {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || -> Result<serde_json::Value> {
        let _permit = permit;
        let output = std::process::Command::new(&app.controller_python)
            .arg(FsPath::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts/controller_models.py"))
            .args(["--backend", &q.backend])
            .output()
            .context("Controller catalog runtime unavailable")?;
        anyhow::ensure!(output.status.success(), "Controller catalog unavailable");
        Ok(serde_json::from_slice(&output.stdout)?)
    })
    .await
    {
        Ok(result) => run_response(result),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
#[derive(serde::Deserialize)]
struct DiffQuery {
    base: ContentId,
    candidate: ContentId,
    tensor: Option<String>,
    #[serde(default)]
    offset: usize,
    #[serde(default = "diff_limit")]
    limit: usize,
}
fn diff_limit() -> usize {
    100
}
async fn checkpoint_diff(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Query(q): Query<DiffQuery>,
) -> Response {
    if !authorized(&headers, app.token.as_deref(), app.port) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        crate::checkpoint_diff::compare(
            &app.store,
            &q.base,
            &q.candidate,
            q.tensor.as_deref(),
            q.offset,
            q.limit,
        )
    })
    .await
    {
        Ok(result) => run_response(result),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
pub fn serve(
    home: PathBuf,
    store: ArtifactStore,
    token_file: &FsPath,
    port: u16,
    controller_python: PathBuf,
    require_token: bool,
) -> Result<()> {
    let app = Arc::new(App {
        home: std::fs::canonicalize(home)?,
        controller_python,
        store,
        token: if require_token {
            Some(nc_dkg_client::read_token(token_file)?)
        } else {
            None
        },
        port,
        permits: Arc::new(tokio::sync::Semaphore::new(2)),
        commands: Arc::new(tokio::sync::Semaphore::new(1)),
    });
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let router=Router::new().route("/",get(||async {Html(include_str!("../../../web/index.html"))}))
            .route("/app.js",get(||async {([(header::CONTENT_TYPE,"text/javascript")],include_str!("../../../web/app.js"))}))
            .route("/api/checkpoint-diff",get(checkpoint_diff))
            .route("/api/folders",get(folder_choices))
            .route("/api/controller-models",get(controller_models))
            .route("/api/context-graph/share",get(context_graph_share))
            .route("/api/context-graph/collaborators",get(context_graph_collaborators))
            .route("/api/shared-experiments",get(shared_experiments))
            .route("/api/ui-config",get(|State(app): State<Arc<App>>| async move { Json(serde_json::json!({"require_token":app.token.is_some()})) }))
            .route("/api/state",get(state)).route("/api/actions",post(action)).route("/api/artifact-metadata/{id}",get(artifact))
            .route("/api/continuations",get(continuation_list).post(continuation_start))
            .route("/api/experiments",post(experiment_start))
            .route("/api/research",get(research_list))
            .route("/api/continuations/{id}/{operation}",post(continuation_control)).with_state(app)
            .layer(axum::middleware::from_fn(|req:axum::extract::Request,next:axum::middleware::Next|async move {
                let mut r=next.run(req).await;
                r.headers_mut().insert(header::CONTENT_SECURITY_POLICY,"default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'".parse().unwrap());
                r.headers_mut().insert(header::CACHE_CONTROL,"no-store".parse().unwrap());r
            }));
        let listener=tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST,port)).await?;
        eprintln!("Neural Commons http://127.0.0.1:{port}");
        axum::serve(listener,router).with_graceful_shutdown(async{let _=tokio::signal::ctrl_c().await;}).await?;Ok(())
    })
}

#[cfg(test)]
mod auth_tests {
    use super::*;
    #[test]
    fn local_default_and_opt_in_token_are_distinct() {
        let mut headers = HeaderMap::new();
        headers.insert(header::HOST, "127.0.0.1:19500".parse().unwrap());
        assert!(authorized(&headers, None, 19500));
        assert!(!authorized(&headers, Some("secret"), 19500));
        headers.insert(header::AUTHORIZATION, "Bearer wrong".parse().unwrap());
        assert!(!authorized(&headers, Some("secret"), 19500));
        headers.insert(header::AUTHORIZATION, "Bearer secret".parse().unwrap());
        assert!(authorized(&headers, Some("secret"), 19500));
        headers.insert(header::ORIGIN, "https://foreign.example".parse().unwrap());
        assert!(!authorized(&headers, None, 19500));
        headers.insert(header::ORIGIN, "null".parse().unwrap());
        assert!(!authorized(&headers, None, 19500));
        headers.insert(header::ORIGIN, "http://127.0.0.1:19500".parse().unwrap());
        assert!(authorized(&headers, None, 19500));
        headers.insert("sec-fetch-site", "cross-site".parse().unwrap());
        assert!(!authorized(&headers, None, 19500));
        headers.remove("sec-fetch-site");
        headers.remove(header::ORIGIN);
        headers.insert(header::HOST, "rebound.example:19500".parse().unwrap());
        assert!(!authorized(&headers, None, 19500));
        headers.insert(header::HOST, "localhost:19500".parse().unwrap());
        assert!(authorized(&headers, None, 19500));
    }
}
